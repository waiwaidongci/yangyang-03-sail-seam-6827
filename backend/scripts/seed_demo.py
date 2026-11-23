import json
from collections import Counter

from sqlalchemy import func, select

from src.domain.analysis import seed
from src.models.base import Base, Session, engine
from src.models.migrate import upgrade as upgrade_schema
from src.models.workflow import AnalysisRun, Observation, Review, SamplingPlan, Schedule
from src.services.observations import clean_observation, content_key
from src.services.plans import create_plan
from src.services.runs import create_first_run
from src.schemas.requests import CreatePlan, PlanBatchInput

DEMO_PLAN = {
    'title': '2026-08-14 质检班 3.5 mm',
    'parameters': {'stitch_pitch': '3.5', 'force_limit_n': 400, 'target_pct': 85, 'confidence_pct': 95},
    'batches': [
        PlanBatchInput(batch_no='BP-260810-A', stage1_count=27, stage2_count=9),
        PlanBatchInput(batch_no='BP-260811-B', stage1_count=18, stage2_count=18),
        PlanBatchInput(batch_no='BP-260812-C', stage1_count=6, stage2_count=6),
    ],
}


def seed_data():
    Base.metadata.create_all(engine)
    upgrade_schema(engine)
    rows = [clean_observation(row) for row in seed()]
    counts = Counter(content_key(row) for row in rows)
    seen = Counter()
    with Session.begin() as db:
        keys = set(db.scalars(select(Observation.source_key)))
        for row in rows:
            key = content_key(row)
            seen[key] += 1
            if counts[key] > 1 and seen[key] > 1:
                key = f'{key}:{seen[key]}'
            if key not in keys:
                db.add(Observation(source_key=key, payload=row))
        db.flush()
        _seed_demo_plan(db)
        return {model.__tablename__: db.scalar(select(func.count(model.id)))
                for model in (Observation, AnalysisRun, Review, SamplingPlan, Schedule)}


def _seed_demo_plan(db):
    """Pre-register the 08-14 review batch so the demo opens with a staged first inspection."""
    if db.scalar(select(SamplingPlan.id)):
        return
    plan = create_plan(db, CreatePlan(**DEMO_PLAN), 'analyst@demo.local')
    create_first_run(db, plan.id, 'analyst@demo.local')


if __name__ == '__main__':
    print(json.dumps(seed_data(), sort_keys=True))
