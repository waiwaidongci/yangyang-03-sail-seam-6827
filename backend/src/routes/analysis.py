from fastapi import APIRouter, Depends
from fastapi.responses import Response

from src.config.project import SPEC
from src.constants.enums import Role, RunStatus
from src.controllers.views import review_view, run_view
from src.models.base import Session
from src.schemas.requests import CreatePlan, ReviewInput
from src.services.auth import current_user, roles
from src.services.broker import wake_worker
from src.services.errors import BusinessError
from src.services.plans import create_plan, plan_batches, plan_view
from src.services.runs import create_first_run, submit_review, visible_runs
from src.utils.formatting import csv_text

router = APIRouter(prefix='/api')


@router.get('/plans')
def plans(user=Depends(current_user)):
    from sqlalchemy import select

    from src.models.workflow import SamplingPlan
    with Session() as db:
        return [plan_view(db, item, plan_batches(db, item.id)) for item in
                db.scalars(select(SamplingPlan).order_by(SamplingPlan.id.desc()).limit(100))]


@router.post('/plans', status_code=201)
def make_plan(request: CreatePlan, user=Depends(roles(Role.ANALYST))):
    with Session.begin() as db:
        plan = create_plan(db, request, user['sub'])
        view = plan_view(db, plan, plan_batches(db, plan.id))
        run = create_first_run(db, plan.id, user['sub']) if request.run_first else None
        run_id = run.id if run else None
    wake_worker()
    return {'plan': view, 'run_id': run_id}


@router.get('/plans/{plan_id}')
def plan_detail(plan_id: int, user=Depends(current_user)):
    from src.models.workflow import SamplingPlan
    with Session() as db:
        plan = db.get(SamplingPlan, plan_id)
        if plan is None:
            raise BusinessError('抽样方案不存在', 404)
        return plan_view(db, plan, plan_batches(db, plan.id))


@router.post('/plans/{plan_id}/first-run', status_code=201)
def start_first_run(plan_id: int, user=Depends(roles(Role.ANALYST))):
    with Session.begin() as db:
        run = create_first_run(db, plan_id, user['sub'])
        view = run_view(run)
    wake_worker()
    return view


@router.get('/runs')
def index(user=Depends(current_user)):
    with Session() as db:
        return [run_view(run, review) for run, review in visible_runs(db, user)]


@router.get('/runs/{run_id}')
def detail(run_id: int, user=Depends(current_user)):
    with Session() as db:
        run, review = visible_runs(db, user, run_id)
        return run_view(run, review, include_result=True)


@router.post('/runs/{run_id}/review', status_code=201)
def decision(run_id: int, request: ReviewInput, user=Depends(roles(Role.SUPERVISOR))):
    with Session.begin() as db:
        return review_view(submit_review(db, run_id, request, user['sub']))


@router.get('/runs/{run_id}/export')
def export(run_id: int, user=Depends(current_user)):
    with Session() as db:
        run, _ = visible_runs(db, user, run_id)
        if run.status != RunStatus.SUCCEEDED:
            raise BusinessError('分析完成后才能下载明细', 409)
        result = run.result
        file = f'{SPEC["slug"]}-run-{run_id}.csv'
        return Response(csv_text(result['columns'] + result.get('trace_columns', []), result['rows']),
                        media_type='text/csv',
                        headers={'Content-Disposition': f'attachment; filename={file}'})
