"""
backend/api/reports.py
======================
FastAPI endpoints for Compliance Readiness Reporting:
- GET /api/reports/summary (JSON)
- GET /api/reports/export (Self-contained printable HTML + report_exported ledger event)
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.services.reports import (
    build_compliance_summary,
    generate_html_report,
    log_report_exported,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/summary")
def get_reports_summary(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Returns compliance readiness summary in JSON format without 0-100 score."""
    return build_compliance_summary(db)


@router.get("/export", response_class=HTMLResponse)
def export_reports_html(db: Session = Depends(get_db)) -> HTMLResponse:
    """
    Returns self-contained printable HTML compliance readiness report.
    Logs report_exported event to the cryptographic audit ledger.
    """
    summary = build_compliance_summary(db)
    log_report_exported(db, summary)
    html_content = generate_html_report(summary)
    return HTMLResponse(content=html_content, media_type="text/html")
