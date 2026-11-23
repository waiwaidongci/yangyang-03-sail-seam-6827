from fastapi import APIRouter, Depends
from sqlalchemy import select

from src.constants.enums import Role
from src.controllers.views import supplement_view
from src.models.base import Session
from src.models.workflow import AnalysisRun, Observation, Supplement, SupplementSpecimen
from src.schemas.requests import SupplementAppend, SupplementCreate
from src.services.auth import current_user, roles
from src.services.broker import wake_worker
from src.services.errors import BusinessError
from src.services.runs import append_specimens, open_supplement, retry_supplement, visible_supplements

router = APIRouter(prefix='/api/supplements')
editor = roles(Role.ANALYST, Role.SUPERVISOR)


@router.get('')
def index(plan_id: int | None = None, batch_no: str | None = None, user=Depends(current_user)):
    with Session() as db:
        return visible_supplements(db, plan_id, batch_no)


@router.post('', status_code=201)
def create(request: SupplementCreate, user=Depends(editor)):
    with Session.begin() as db:
        supplement = open_supplement(db, request.plan_id, request.batch_no, user['sub'])
        return supplement_view(db, supplement)


@router.get('/{supplement_id}')
def detail(supplement_id: int, user=Depends(current_user)):
    with Session() as db:
        supplement = db.get(Supplement, supplement_id)
        if supplement is None:
            raise BusinessError('补抽记录不存在', 404)
        return supplement_view(db, supplement)


@router.get('/{supplement_id}/candidates')
def candidates(supplement_id: int, user=Depends(current_user)):
    """Ledger rows of this ticket registered after the first-stage snapshot, not yet attached."""
    with Session() as db:
        supplement = db.get(Supplement, supplement_id)
        if supplement is None:
            raise BusinessError('补抽记录不存在', 404)
        first_run = db.get(AnalysisRun, supplement.first_run_id)
        attached = set(db.scalars(select(SupplementSpecimen.observation_id)
                                  .where(SupplementSpecimen.supplement_id == supplement.id)))
        rows = []
        for item in db.scalars(select(Observation).where(Observation.id > first_run.last_observation_id)
                               .order_by(Observation.id)):
            payload = item.payload
            if payload['batch_no'].strip() != supplement.batch_no:
                continue
            if payload['stitch_pitch'] != supplement.stitch_pitch:
                continue
            rows.append({'id': item.id, 'attached': item.id in attached, **payload})
        return rows


@router.post('/{supplement_id}/specimens', status_code=201)
def append(supplement_id: int, request: SupplementAppend, user=Depends(editor)):
    with Session.begin() as db:
        supplement = db.get(Supplement, supplement_id, with_for_update=True)
        if supplement is None:
            raise BusinessError('补抽记录不存在', 404)
        supplement, run = append_specimens(db, supplement, request.records, user['sub'],
                                           request.observation_ids)
        view = supplement_view(db, supplement)
    if run is not None:
        wake_worker()
    return view


@router.post('/{supplement_id}/retry')
def retry(supplement_id: int, user=Depends(editor)):
    with Session.begin() as db:
        supplement = db.get(Supplement, supplement_id, with_for_update=True)
        if supplement is None:
            raise BusinessError('补抽记录不存在', 404)
        supplement = retry_supplement(db, supplement, user['sub'])
        view = supplement_view(db, supplement)
    wake_worker()
    return view
