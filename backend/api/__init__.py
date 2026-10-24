from .inventory import router as inventory_router
from .privacy_requests import router as privacy_requests_router
from .incidents import router as incidents_router

__all__ = ["inventory_router", "privacy_requests_router", "incidents_router"]
