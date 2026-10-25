from contextlib import asynccontextmanager
import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.db.engine import engine
from backend.db.models import Base
from backend.api import (
    inventory_router,
    privacy_requests_router,
    incidents_router,
    purposes_router,
    ledger_router,
    evidence_router,
    flags_router,
    erasure_router,
    breach_router,
    rights_router,
    cases_router,
    graphs_router,
    reports_router,
    business_router,
)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure upload temp directory exists
    os.makedirs(settings.upload_temp_dir, exist_ok=True)
    # Retention check at app startup: if retention period expired, purge business data
    try:
        from backend.db.engine import SessionLocal
        from backend.services.purge import check_and_purge_if_expired
        session = SessionLocal()
        try:
            check_and_purge_if_expired(session)
        finally:
            session.close()
    except Exception as e:
        logger.debug("Startup retention check note: %s", e)

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables initialized. Upload directory verified at %s.", settings.upload_temp_dir)
    yield
    # Shutdown logic if needed


def create_app() -> FastAPI:
    app = FastAPI(
        title="Local-First Privacy Compliance Assistant",
        description="Backend API supporting DPDP compliance, data inventory, rights requests, and incident tracking.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Basic CORS setup for local frontend development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API Routers
    app.include_router(inventory_router)
    app.include_router(privacy_requests_router)
    app.include_router(incidents_router, prefix="/api/v1/incidents")
    app.include_router(incidents_router, prefix="/api/incidents")
    app.include_router(purposes_router)
    app.include_router(purposes_router, prefix="/api/v1")
    app.include_router(ledger_router)
    app.include_router(business_router)
    app.include_router(evidence_router)
    app.include_router(flags_router)
    app.include_router(erasure_router, prefix="/api/erasure", tags=["erasure"])
    app.include_router(breach_router)
    app.include_router(rights_router)
    app.include_router(cases_router)
    app.include_router(graphs_router)
    app.include_router(reports_router)

    @app.get("/health", tags=["health"])
    def health_check():
        return {
            "status": "healthy",
            "ai_mode": settings.ai_mode,
        }

    @app.get("/api/notices", tags=["notices"])
    def get_api_notices(lang: str = "en"):
        from backend.services.i18n import t
        header_loc = t("notices.notice_header", lang=lang)
        return {
            "header": str(header_loc),
            "sections": {
                "clause_a": str(t("notices.clause_a_title", lang=lang)),
                "clause_b": str(t("notices.clause_b_title", lang=lang)),
                "clause_c": str(t("notices.clause_c_title", lang=lang)),
                "clause_d": str(t("notices.clause_d_title", lang=lang)),
                "clause_e": str(t("notices.clause_e_title", lang=lang)),
            },
            "disclaimers": {
                "not_legal_advice": str(t("notices.not_legal_advice", lang=lang)),
                "citations_to_verify": str(t("notices.citations_to_verify", lang=lang)),
                "readiness_aid": str(t("notices.readiness_aid_body", lang=lang)),
                "footer": str(t("notices.footer", lang=lang)),
                "green_wording": str(t("notices.green_wording", lang=lang)),
            },
            "machine_translated": getattr(header_loc, "machine_translated", False),
            "lang": header_loc.lang,
        }

    @app.get("/api/checklist", tags=["checklist"])
    def get_api_checklist(lang: str = "en"):
        from backend.services.breach import get_ordered_checklist
        return get_ordered_checklist(lang=lang)

    return app


app = create_app()
