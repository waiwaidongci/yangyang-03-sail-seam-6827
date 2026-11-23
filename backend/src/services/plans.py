from sqlalchemy import select

from src.config.project import SPEC
from src.constants.enums import RunKind, RunStatus
from src.domain.analysis import alpha_budget, split_alphas
from src.models.workflow import AuditEvent, PlanBatch, SamplingPlan, Supplement
from src.services.errors import BusinessError
from src.services.validation import validated
from src.utils.formatting import timestamp


def _supplement_rows(db, plan_id):
    from src.controllers.views import supplement_view
    return [supplement_view(db, item) for item in
            db.scalars(select(Supplement).where(Supplement.plan_id == plan_id))]


def create_plan(db, request, actor):
    parameters = validated(SPEC['parameters'], request.parameters, defaults=True)
    specs = []
    seen = set()
    for item in request.batches:
        batch_no = item.batch_no.strip()
        if batch_no in seen:
            raise BusinessError(f'工票批号重复：{batch_no}')
        seen.add(batch_no)
        specs.append({'batch_no': batch_no, 'stage1_count': item.stage1_count,
                      'stage2_count': item.stage2_count})
    if not specs:
        raise BusinessError('请至少登记一张工票的两次抽检片数')

    parameters['alpha_total'] = alpha_budget(parameters['confidence_pct'], len(specs))
    plan = SamplingPlan(title=request.title, owner=actor, parameters=parameters)
    db.add(plan)
    db.flush()
    for spec in specs:
        db.add(PlanBatch(plan_id=plan.id, batch_no=spec['batch_no'],
                         stage1_count=spec['stage1_count'], stage2_count=spec['stage2_count']))
    db.flush()
    db.add(AuditEvent(actor=actor, action='plan.created',
                      detail=f'抽样方案 #{plan.id} · {len(specs)} 批 · 每批 α_b={parameters["alpha_total"]:.6g}'))
    return plan


def plan_batches(db, plan_id):
    return list(db.scalars(select(PlanBatch).where(PlanBatch.plan_id == plan_id)
                           .order_by(PlanBatch.batch_no)))


def plan_parameters(plan, batches):
    """Rebuild the frozen thresholds so each run records exactly what was pre-registered."""
    parameters = dict(plan.parameters)
    alpha_total = alpha_budget(parameters['confidence_pct'], len(batches))
    parameters['alpha_total'] = alpha_total
    parameters['batches'] = []
    for batch in batches:
        alpha1, alpha2 = split_alphas(alpha_total, batch.stage1_count, batch.stage2_count)
        parameters['batches'].append({
            'batch_no': batch.batch_no,
            'stage1_count': batch.stage1_count,
            'stage2_count': batch.stage2_count,
            'alpha1': alpha1,
            'alpha2': alpha2,
        })
    return parameters


def plan_view(db, plan, batches, first_run=None):
    from src.services.runs import first_run_for_plan

    if first_run is None:
        first_run = first_run_for_plan(db, plan.id)
    supplements = {item['batch_no']: item for item in _supplement_rows(db, plan.id)}
    alpha_total = alpha_budget(plan.parameters['confidence_pct'], len(batches))
    decisions = {}
    if first_run is not None and first_run.result:
        decisions = {row['batch_no']: row for row in first_run.result.get('rows', [])}
    rows = []
    for batch in batches:
        alpha1, alpha2 = split_alphas(alpha_total, batch.stage1_count, batch.stage2_count)
        decided = decisions.get(batch.batch_no)
        supplement = supplements.get(batch.batch_no)
        rows.append({
            'batch_no': batch.batch_no,
            'stage1_count': batch.stage1_count,
            'stage2_count': batch.stage2_count,
            'alpha1': alpha1,
            'alpha2': alpha2,
            'first_decision': decided['decision'] if decided else None,
            'first_status': decided['status'] if decided else '首检尚未算完',
            'supplement': supplement,
            'supplement_available': bool(decided and decided['decision'] == 'pending'
                                         and batch.stage2_count > 0 and not supplement),
        })
    return {
        'id': plan.id,
        'title': plan.title,
        'owner': plan.owner,
        'parameters': plan.parameters,
        'alpha_total': alpha_total,
        'created_at': timestamp(plan.created_at),
        'first_run_id': first_run.id if first_run else None,
        'first_run_status': first_run.status if first_run else None,
        'batches': rows,
    }
