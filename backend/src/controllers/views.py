from src.utils.formatting import timestamp


def review_view(item):
    return {'decision': item.decision, 'note': item.note, 'reviewer': item.reviewer,
            'at': timestamp(item.created_at)} if item else None


def run_view(item, review=None, *, include_result=False):
    view = {'id': item.id, 'title': item.title, 'owner': item.owner, 'status': item.status,
            'kind': item.kind, 'plan_id': item.plan_id, 'supplement_id': item.supplement_id,
            'parameters': item.parameters, 'sample_size': item.sample_size,
            'snapshot_id': item.last_observation_id, 'created_at': timestamp(item.created_at),
            'finished_at': timestamp(item.finished_at), 'review': review_view(review), 'error': item.error}
    if include_result:
        view['result'] = item.result
    return view


def observation_view(item):
    return {'id': item.id, 'data': item.payload, 'created_at': timestamp(item.created_at)}


def supplement_view(db, supplement):
    from src.models.workflow import AnalysisRun, Observation, SamplingPlan
    from src.services.runs import supplement_run_for, supplement_specimen_ids

    plan = db.get(SamplingPlan, supplement.plan_id)
    first_run = db.get(AnalysisRun, supplement.first_run_id)
    filled = len(supplement_specimen_ids(db, supplement.id))
    run = supplement_run_for(db, supplement.id)
    specimens = []
    for observation_id in supplement_specimen_ids(db, supplement.id):
        observation = db.get(Observation, observation_id)
        if observation:
            specimens.append({'observation_id': observation.id, **observation.payload})
    return {
        'id': supplement.id,
        'plan_id': supplement.plan_id,
        'plan_title': plan.title if plan else '',
        'batch_no': supplement.batch_no,
        'stitch_pitch': supplement.stitch_pitch,
        'stage1_count': supplement.stage1_count,
        'stage2_count': supplement.stage2_count,
        'filled_count': filled,
        'remaining': max(0, supplement.stage2_count - filled),
        'status': supplement.status,
        'requested_by': supplement.requested_by,
        'first_run_id': supplement.first_run_id,
        'first_run_status': first_run.status if first_run else None,
        'run_id': run.id if run else None,
        'run_status': run.status if run else None,
        'run_error': run.error if run else None,
        'specimens': specimens,
        'created_at': timestamp(supplement.created_at),
        'completed_at': timestamp(supplement.completed_at),
    }


def schedule_view(item):
    return {'id': item.id, 'run_id': item.run_id, 'recipient': item.recipient,
            'interval_minutes': item.interval_minutes, 'next_at': timestamp(item.next_at), 'active': item.active}


def delivery_view(delivery, schedule):
    return {'id': delivery.id, 'schedule_id': schedule.id, 'recipient': schedule.recipient,
            'run_id': schedule.run_id, 'at': timestamp(delivery.delivered_at),
            'scheduled_at': timestamp(delivery.scheduled_at)}
