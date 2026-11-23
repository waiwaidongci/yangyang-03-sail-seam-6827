import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.constants.enums import Decision, RunKind, RunStatus, SupplementStatus
from src.domain.analysis import analyze
from src.models.base import utc_now
from src.models.workflow import (AnalysisRun, AuditEvent, Observation, Review, SamplingPlan, Supplement,
                                 SupplementSpecimen)
from src.services.errors import BusinessError
from src.services.plans import plan_batches, plan_parameters

logger = logging.getLogger(__name__)


def create_first_run(db, plan_id, actor):
    plan = db.get(SamplingPlan, plan_id, with_for_update=True)
    if plan is None:
        raise BusinessError('抽样方案不存在', 404)
    if db.scalar(select(AnalysisRun.id).where(AnalysisRun.plan_id == plan.id)):
        raise BusinessError('这份方案已发起过首检，补抽请到台账录入。', 409)
    batches = plan_batches(db, plan.id)
    if not batches:
        raise BusinessError('方案没有登记审查批次', 409)
    pitch = plan.parameters['stitch_pitch']
    pool = list(db.execute(select(Observation.id, Observation.payload).order_by(Observation.id)))
    stage_map = {}
    used_specimens = {}
    for batch in batches:
        available = [row for row in pool
                     if row.payload['stitch_pitch'] == pitch and row.payload['batch_no'].strip() == batch.batch_no]
        picked = available[:batch.stage1_count]
        if len(picked) < batch.stage1_count:
            raise BusinessError(
                f'{batch.batch_no} 首检需 {batch.stage1_count} 片，当前 {pitch} mm 台账只有 {len(picked)} 片。'
                '请补录试片或调整方案后再发起。'
            )
        for row in picked:
            specimen = row.payload['specimen_id'].strip()
            if specimen in used_specimens:
                raise BusinessError(f'试片编号 {specimen} 同时归属 {used_specimens[specimen]} 与 {batch.batch_no}。')
            used_specimens[specimen] = batch.batch_no
        stage_map[batch.batch_no] = {'stage1': [row.id for row in picked], 'stage2': []}
    parameters = plan_parameters(plan, batches)
    parameters['stage_map'] = stage_map
    ids = sorted({item for stages in stage_map.values() for item in stages['stage1']})
    item = AnalysisRun(title=f'{plan.title}·首检', owner=actor, parameters=parameters, observation_ids=ids,
                       last_observation_id=max(ids), sample_size=len(ids), kind=RunKind.FIRST, plan_id=plan.id)
    db.add(item)
    db.flush()
    db.add(AuditEvent(actor=actor, action='run.first',
                      detail=f'方案 #{plan.id} 首检 · 分析 #{item.id} · {len(ids)} 片'))
    return item


def first_run_for_plan(db, plan_id):
    return db.scalar(select(AnalysisRun).where(AnalysisRun.plan_id == plan_id, AnalysisRun.kind == RunKind.FIRST)
                     .order_by(AnalysisRun.id.desc()).limit(1))


def supplement_run_for(db, supplement_id):
    return db.scalar(select(AnalysisRun).where(AnalysisRun.supplement_id == supplement_id)
                     .order_by(AnalysisRun.id.desc()).limit(1))


def supplement_specimen_ids(db, supplement_id):
    return sorted(db.scalars(select(SupplementSpecimen.observation_id)
                             .where(SupplementSpecimen.supplement_id == supplement_id)))


def visible_supplements(db, plan_id=None, batch_no=None):
    query = select(Supplement).order_by(Supplement.id.desc())
    if plan_id is not None:
        query = query.where(Supplement.plan_id == plan_id)
    if batch_no is not None:
        query = query.where(Supplement.batch_no == batch_no)
    from src.controllers.views import supplement_view
    return [supplement_view(db, item) for item in db.scalars(query.limit(200))]


def open_supplement(db, plan_id, batch_no, actor):
    plan = db.get(SamplingPlan, plan_id, with_for_update=True)
    if plan is None:
        raise BusinessError('抽样方案不存在', 404)
    batch_no = batch_no.strip()
    batch = next((row for row in plan_batches(db, plan.id) if row.batch_no == batch_no), None)
    if batch is None:
        raise BusinessError('这张工票不在本次审查范围内', 404)
    if batch.stage2_count <= 0:
        raise BusinessError('方案没有为这张工票安排补抽片数', 409)
    first_run = first_run_for_plan(db, plan.id)
    if first_run is None or first_run.status != RunStatus.SUCCEEDED:
        raise BusinessError('首检尚未算完，台账暂不开放补抽。', 409)
    if db.scalar(select(Supplement.id).where(Supplement.plan_id == plan.id,
                                             Supplement.batch_no == batch_no)):
        raise BusinessError('这张工票已发起过补抽，并发发起也只受理一份。', 409)
    decision = {row['batch_no']: row for row in (first_run.result or {}).get('rows', [])}.get(batch_no)
    if not decision or decision['decision'] != 'pending':
        raise BusinessError('只有首检判为待定的工票才开放补抽。', 409)
    supplement = Supplement(plan_id=plan.id, first_run_id=first_run.id, batch_no=batch_no,
                            stitch_pitch=plan.parameters['stitch_pitch'],
                            stage1_count=batch.stage1_count, stage2_count=batch.stage2_count,
                            status=SupplementStatus.OPEN, requested_by=actor)
    db.add(supplement)
    try:
        db.flush()
    except IntegrityError as exc:
        raise BusinessError('这张工票已发起过补抽，并发发起也只受理一份。', 409) from exc
    db.add(AuditEvent(actor=actor, action='supplement.opened',
                      detail=f'方案 #{plan.id} · {batch_no} 补抽 {batch.stage2_count} 片'))
    return supplement


def _committed_specimens(db, plan_id):
    specimens = set()
    first_run = first_run_for_plan(db, plan_id)
    if first_run is not None:
        ids = [item for stages in (first_run.parameters.get('stage_map') or {}).values()
               for item in stages.get('stage1') or []]
        for payload in db.scalars(select(Observation.payload).where(Observation.id.in_(ids))):
            specimens.add(payload['specimen_id'].strip())
    for supplement in db.scalars(select(Supplement).where(Supplement.plan_id == plan_id)):
        ids = supplement_specimen_ids(db, supplement.id)
        for payload in db.scalars(select(Observation.payload).where(Observation.id.in_(ids))):
            specimens.add(payload['specimen_id'].strip())
    return specimens


def append_specimens(db, supplement, rows, actor, observation_ids=None):
    """Attach specimens to an open supplement exactly once and queue the merged re-run when full."""
    rows = list(rows or [])
    observation_ids = list(observation_ids or [])
    if not rows and not observation_ids:
        raise BusinessError('请选择或录入补抽试片')
    from src.services.observations import add_observations, clean_observation, content_key

    attached = set(supplement_specimen_ids(db, supplement.id))
    committed = _committed_specimens(db, supplement.plan_id)

    if supplement.status in (SupplementStatus.QUEUED, SupplementStatus.COMPLETED):
        raise BusinessError('这份补抽已完成录入，重试不会重复计片。', 409)
    if supplement.status == SupplementStatus.FAILED:
        raise BusinessError('上次合并重算失败，请用重试入口，不要重复录片。', 409)

    keyed = {}
    for raw in rows:
        row = clean_observation(raw)
        if row['batch_no'].strip() != supplement.batch_no:
            raise BusinessError(f'补抽试片必须属于工票 {supplement.batch_no}。')
        if row['stitch_pitch'] != supplement.stitch_pitch:
            raise BusinessError(f'补抽试片针距必须为 {supplement.stitch_pitch} mm。')
        keyed.setdefault(content_key(row), row)

    existing = {item.source_key: item.id for item in db.scalars(
        select(Observation).where(Observation.source_key.in_(keyed)))}
    fresh = [row for key, row in keyed.items() if key not in existing]
    if fresh:
        for item in add_observations(db, fresh, actor, 'observation.supplement'):
            existing[item.source_key] = item.id
    candidates = list(observation_ids) + [existing[key] for key in keyed]

    accepted = []
    seen_ids = set()
    for observation_id in candidates:
        if observation_id in attached or observation_id in seen_ids:
            continue
        seen_ids.add(observation_id)
        observation = db.get(Observation, observation_id)
        if observation is None:
            raise BusinessError(f'台账记录 #{observation_id} 不存在', 404)
        if observation.payload['batch_no'].strip() != supplement.batch_no:
            raise BusinessError(f'补抽试片必须属于工票 {supplement.batch_no}。')
        if observation.payload['stitch_pitch'] != supplement.stitch_pitch:
            raise BusinessError(f'补抽试片针距必须为 {supplement.stitch_pitch} mm。')
        specimen = observation.payload['specimen_id'].strip()
        if specimen in committed:
            raise BusinessError(f'试片编号 {specimen} 已在本次方案中使用，每片只可计一次。', 409)
        committed.add(specimen)
        accepted.append(observation_id)

    current = len(attached)
    if current + len(accepted) > supplement.stage2_count:
        raise BusinessError(f'补抽只安排 {supplement.stage2_count} 片，已录入 {current} 片，本次超出上限。')
    if not accepted:
        if current >= supplement.stage2_count:
            raise BusinessError('补抽试片已凑齐，等待后台合并重算。', 409)
        raise BusinessError('这批试片已录入，重试不会重复计片。', 409)

    for observation_id in accepted:
        db.add(SupplementSpecimen(supplement_id=supplement.id, observation_id=observation_id))
    try:
        db.flush()
    except IntegrityError as exc:
        raise BusinessError('有补抽试片刚刚被另一份请求并入，请刷新后重试。', 409) from exc
    db.add(AuditEvent(actor=actor, action='supplement.specimen',
                      detail=f'{supplement.batch_no} 补抽 +{len(accepted)} 片，共 {current + len(accepted)}/{supplement.stage2_count}'))
    if current + len(accepted) < supplement.stage2_count:
        supplement.status = SupplementStatus.OPEN
        return supplement, None

    supplement.status = SupplementStatus.READY
    run = _start_supplement_run(db, supplement, actor)
    return supplement, run


def _start_supplement_run(db, supplement, actor):
    plan = db.get(SamplingPlan, supplement.plan_id)
    first_run = db.get(AnalysisRun, supplement.first_run_id)
    stage_map = {batch: {'stage1': list(stages.get('stage1') or []), 'stage2': []}
                 for batch, stages in (first_run.parameters.get('stage_map') or {}).items()}
    for item in db.scalars(select(Supplement).where(Supplement.plan_id == plan.id)):
        ids = supplement_specimen_ids(db, item.id)
        if len(ids) != item.stage2_count:
            continue
        stage_map.setdefault(item.batch_no, {'stage1': [], 'stage2': []})['stage2'] = ids
    parameters = plan_parameters(plan, plan_batches(db, plan.id))
    parameters['stage_map'] = stage_map
    ids = sorted({value for stages in stage_map.values() for values in stages.values() for value in values})
    run = AnalysisRun(title=f'{plan.title}·补抽合并 {supplement.batch_no}', owner=actor, parameters=parameters,
                      observation_ids=ids, last_observation_id=max(ids), sample_size=len(ids),
                      kind=RunKind.SUPPLEMENT, plan_id=plan.id, supplement_id=supplement.id)
    db.add(run)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise BusinessError('这份补抽的合并分析已存在，重试不会重复计片。', 409) from exc
    supplement.status = SupplementStatus.QUEUED
    db.add(AuditEvent(actor=actor, action='run.supplement',
                      detail=f'方案 #{plan.id} · {supplement.batch_no} 合并重算 · 分析 #{run.id}'))
    return run


def retry_supplement(db, supplement, actor):
    if supplement.status != SupplementStatus.FAILED:
        raise BusinessError('只有重算失败的补抽可以重试。', 409)
    run = supplement_run_for(db, supplement.id)
    if run is None:
        raise BusinessError('找不到失败的补抽分析。', 404)
    run.status = RunStatus.QUEUED
    run.error = None
    run.finished_at = None
    supplement.status = SupplementStatus.QUEUED
    db.add(AuditEvent(actor=actor, action='supplement.retry',
                      detail=f'方案 #{supplement.plan_id} · {supplement.batch_no} 重试分析 #{run.id}'))
    return supplement


def visible_runs(db, user, run_id=None):
    query = select(AnalysisRun, Review).outerjoin(Review, Review.run_id == AnalysisRun.id)
    if user['role'] == 'viewer':
        query = query.where(Review.decision == Decision.APPROVED)
    if run_id is not None:
        pair = db.execute(query.where(AnalysisRun.id == run_id)).first()
        if pair is None:
            raise BusinessError('没有可查看的分析结果', 404)
        return pair
    return db.execute(query.order_by(AnalysisRun.id.desc()).limit(100)).all()


def submit_review(db, run_id, request, actor):
    row = db.get(AnalysisRun, run_id, with_for_update=True)
    if row is None:
        raise BusinessError('分析不存在', 404)
    if row.status != RunStatus.SUCCEEDED:
        raise BusinessError('分析算完后才能复核', 409)
    if db.scalar(select(Review).where(Review.run_id == run_id)):
        raise BusinessError('这份分析已完成复核。请发起新分析并重新复核。', 409)
    if row.owner == actor:
        raise BusinessError('分析须由另一位负责人复核', 409)
    review = Review(run_id=run_id, decision=request.decision, note=request.note, reviewer=actor)
    db.add(review)
    db.add(AuditEvent(actor=actor, action=f'review.{request.decision}', detail=f'分析 #{run_id}'))
    db.flush()
    return review


def run_pending(db):
    item = db.scalar(select(AnalysisRun).where(AnalysisRun.status == RunStatus.QUEUED)
                     .order_by(AnalysisRun.id).limit(1).with_for_update(skip_locked=True))
    if item is None:
        return False
    supplement = db.get(Supplement, item.supplement_id, with_for_update=True) if item.supplement_id else None
    try:
        pairs = list(db.execute(select(Observation.id, Observation.payload)
                                .where(Observation.id.in_(item.observation_ids)).order_by(Observation.id)))
        if len(pairs) != len(item.observation_ids):
            raise ValueError('部分试片记录已不存在，无法复算。')
        result = analyze([row.payload for row in pairs], item.parameters, [row.id for row in pairs])
        if not {'headline', 'summary', 'metrics', 'columns', 'rows'} <= set(result):
            raise RuntimeError('invalid result schema')
        json.dumps(result, allow_nan=False, ensure_ascii=False)
        item.result = result
        item.status = RunStatus.SUCCEEDED
        if supplement is not None:
            supplement.status = SupplementStatus.COMPLETED
            supplement.completed_at = utc_now()
    except ValueError as exc:
        item.error = str(exc)[:600] or '本次观测数据不足以完成计算'
        item.status = RunStatus.FAILED
        if supplement is not None:
            supplement.status = SupplementStatus.FAILED
    except Exception:
        logger.exception('Analysis %s raised unexpectedly', item.id)
        item.error = '分析计算失败，请检查记录和参数后重试'
        item.status = RunStatus.FAILED
        if supplement is not None:
            supplement.status = SupplementStatus.FAILED
    item.finished_at = utc_now()
    return True
