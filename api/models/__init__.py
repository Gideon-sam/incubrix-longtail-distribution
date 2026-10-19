# api/models/__init__.py — import all models so Base.metadata sees them
from api.models.job import Job
from api.models.destination import Destination
from api.models.idempotency import IdempotencyRecord
from api.models.certification import CertificationRecord
from api.models.rule import DestinationRule, RuleProposal
from api.models.cleanup import PendingCleanup
from api.models.alert import Alert
from api.models.metric import MetricSnapshot

__all__ = [
    "Job",
    "Destination",
    "IdempotencyRecord",
    "CertificationRecord",
    "DestinationRule",
    "RuleProposal",
    "PendingCleanup",
    "Alert",
    "MetricSnapshot",
]
