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
    get_scenario_by_id,
    load_scenarios,
    simulate_breach,
)

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
