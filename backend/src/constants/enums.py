from enum import StrEnum


class Role(StrEnum):
    VIEWER = 'viewer'
    ANALYST = 'analyst'
    SUPERVISOR = 'supervisor'


class RunStatus(StrEnum):
    QUEUED = 'queued'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'


class RunKind(StrEnum):
    FIRST = 'first'
    SUPPLEMENT = 'supplement'


class SupplementStatus(StrEnum):
    OPEN = 'open'
    READY = 'ready'
    QUEUED = 'queued'
    COMPLETED = 'completed'
    FAILED = 'failed'


class Decision(StrEnum):
    APPROVED = 'approved'
    RETURNED = 'returned'
