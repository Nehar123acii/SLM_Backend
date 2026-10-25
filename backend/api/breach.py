"""
backend/api/breach.py
=====================
FastAPI routes for breach scenarios and blast-radius simulation.
Endpoints:
- GET  /api/breach/scenarios
- POST /api/breach/simulate
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.services.breach import (
    get_ordered_checklist,
    get_scenario_by_id,
    load_scenarios,
    simulate_breach,
)
from backend.services.i18n import t

router = APIRouter(prefix="/api/breach", tags=["breach"])


class SimulateRequest(BaseModel):
    scenario: str = Field("custom", description="Scenario ID from breach_scenarios.yaml or 'custom'")
    aware_at: Optional[str] = Field(None, description="ISO timestamp when fiduciary became aware")
    sources: Optional[List[str]] = Field(None, description="List of source filenames or dataset IDs")
    device_protected: str = Field("unknown", description="'unknown' | 'yes' | 'no'")
    board_extension_requested: bool = Field(False, description="Whether written extension was requested to the Board")


@router.get("/scenarios", response_model=List[Dict[str, Any]])
def list_breach_scenarios():
    """
    Returns predefined breach simulation scenarios from rules/breach_scenarios.yaml.
    """
    scenarios = load_scenarios()
    return scenarios


@router.post("/simulate", status_code=status.HTTP_200_OK)
def run_breach_simulation(
    payload: SimulateRequest,
    db: Session = Depends(get_db),
):
    """
    Runs a breach blast-radius simulation against real or custom sources.
    Outputs:
    - Confirmed and possible affected people counts
    - High-impact data categories and minor involvement
    - Explainable severity score (orders work only; does not determine notification duties)
    - DPDP Rule 7 countdown clocks
    - Tailored draft intimations keyed to statutory clauses
    - 6-stage operational incident response checklist
    - Warnings if principal's only registered contact channel is in leaked source
    Logs simulation to tamper-evident ledger.
    """
    try:
        result = simulate_breach(
            session=db,
            scenario=payload.scenario,
            aware_at=payload.aware_at,
            sources=payload.sources,
            device_protected=payload.device_protected,
            board_extension_requested=payload.board_extension_requested,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Breach simulation failed: {str(e)}")


@router.get("/checklist", response_model=List[Dict[str, Any]])
def get_breach_checklist(lang: str = "en"):
    """
    Returns the ordered 6-stage operational incident response checklist localized by ?lang=en|hi|kn.
    """
    return get_ordered_checklist(lang=lang)


@router.get("/notices")
def get_breach_notices(lang: str = "en"):
    """
    Returns statutory notice titles, clauses, and disclaimers localized by ?lang=en|hi|kn.
    """
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
