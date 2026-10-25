from .inventory import router as inventory_router
from .privacy_requests import router as privacy_requests_router
from .incidents import router as incidents_router
from .purposes import router as purposes_router
from .ledger import router as ledger_router
from .evidence import router as evidence_router
from .rules import router as flags_router
from .erasure import erasure_router

__all__ = [
    "inventory_router",
    "privacy_requests_router",
    "incidents_router",
    "purposes_router",
    "ledger_router",
    "evidence_router",
    "flags_router",
    "erasure_router",
]
