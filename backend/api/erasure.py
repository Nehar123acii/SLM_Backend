"""
backend/api/erasure.py
======================
FastAPI APIRouter for DPDP erasure workflows:
- POST /api/erasure/plan
- POST /api/erasure/{id}/approve
- POST /api/erasure/{id}/execute
- GET /api/erasure/{id}/receipt
- GET /api/erasure/{id}/receipt.html
"""

import json
import os
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.engine import get_db
from backend.db.models import ErasurePlan
from backend.services.erasure import (
    compile_plan,
    approve,
    execute,
    confirm_identity_for_plan,
)

erasure_router = APIRouter()


class CompilePlanRequest(BaseModel):
    person_id: int = Field(..., description="ID of the resolved person entity")
    overrides: Optional[Dict[str, str]] = Field(None, description="Optional manual field action overrides")


class ApprovePlanRequest(BaseModel):
    confirm_hash: str = Field(..., description="SHA-256 plan_hash confirming human review")


@erasure_router.post("/plan", status_code=status.HTTP_201_CREATED)
def create_erasure_plan(
    payload: CompilePlanRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Compiles field-level erasure plan from retention matrix and person occurrences."""
    try:
        plan = compile_plan(db, person_id=payload.person_id, overrides=payload.overrides)
        return plan
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compile erasure plan: {str(e)}")


@erasure_router.post("/{plan_id}/confirm-identity")
def confirm_identity(
    plan_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Confirms identity for a probable-match plan, unblocking approval and execution."""
    try:
        return confirm_identity_for_plan(db, plan_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@erasure_router.post("/{plan_id}/approve")
def approve_erasure_plan(
    plan_id: str,
    payload: ApprovePlanRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Approves an erasure plan by validating confirm_hash matches the stored plan_hash."""
    try:
        return approve(db, plan_id=plan_id, confirm_hash=payload.confirm_hash)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@erasure_router.post("/{plan_id}/execute")
def execute_erasure_plan(
    plan_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Executes approved erasure plan without modifying original files; performs residual check."""
    try:
        receipt = execute(db, plan_id=plan_id)
        return receipt
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@erasure_router.get("/{plan_id}/receipt")
def get_erasure_receipt(
    plan_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Retrieves JSON compliance receipt for an executed erasure plan."""
    plan_row = db.query(ErasurePlan).filter(ErasurePlan.id == plan_id).first()
    if not plan_row:
        raise HTTPException(status_code=404, detail=f"Erasure plan '{plan_id}' not found")
    if not plan_row.receipt_json:
        raise HTTPException(status_code=400, detail=f"Plan '{plan_id}' has not been executed yet")
    return json.loads(plan_row.receipt_json)


@erasure_router.get("/{plan_id}/receipt.html", response_class=HTMLResponse)
def get_erasure_receipt_html(
    plan_id: str,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Retrieves self-contained printable HTML compliance receipt."""
    plan_row = db.query(ErasurePlan).filter(ErasurePlan.id == plan_id).first()
    if not plan_row:
        raise HTTPException(status_code=404, detail=f"Erasure plan '{plan_id}' not found")
    if not plan_row.receipt_html_path or not os.path.exists(plan_row.receipt_html_path):
        raise HTTPException(status_code=400, detail=f"HTML receipt for plan '{plan_id}' not available")
    with open(plan_row.receipt_html_path, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content)
