"""
backend/api/rights.py
=====================
FastAPI routes for DPDP Rights Desk and Case Lifecycle Management.
Endpoints:
- POST /api/rights/intake
- POST /api/rights/classify
- GET  /api/cases
- GET  /api/cases/{id}
- POST /api/cases/{id}/confirm-identity
- POST /api/cases/{id}/plan
- POST /api/cases/{id}/approve
- POST /api/cases/{id}/execute
- POST /api/cases/{id}/close
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.db.models import RightsCase
from backend.services.purge import touch_activity
from backend.services.rights import (
    approve_case,
    classify_message,
    close_case,
    confirm_identity_for_case,
    create_plan_for_case,
    execute_case,
    get_case,
    parse_whatsapp_text,
    process_intake,
    serialize_case,
)

rights_router = APIRouter(prefix="/api/rights", tags=["rights"])
cases_router = APIRouter(prefix="/api/cases", tags=["cases"])


# -------------------------------------------------------------
# Request Schemas
# -------------------------------------------------------------
class IntakeRequest(BaseModel):
    text: Optional[str] = Field(None, description="Raw WhatsApp exported chat text")
    messages: Optional[List[Dict[str, str]]] = Field(None, description="Structured message dictionaries")


class ClassifyRequest(BaseModel):
    text: str = Field(..., description="Message text to classify")


class ApproveCaseRequest(BaseModel):
    confirm_hash: str = Field(..., description="SHA-256 plan hash required to confirm approval")


# -------------------------------------------------------------
# Rights Desk Endpoints
# -------------------------------------------------------------
@rights_router.post("/intake", status_code=status.HTTP_201_CREATED)
def intake_rights_requests(
    payload: IntakeRequest,
    db: Session = Depends(get_db),
):
    """
    Ingests messages from WhatsApp chat text or message list.
    Classifies intent, resolves sender via HMAC, masks raw data,
    creates RightsCase records, and logs case_received to ledger.
    """
    messages: List[Dict[str, str]] = []
    if payload.text:
        messages.extend(parse_whatsapp_text(payload.text))
    if payload.messages:
        messages.extend(payload.messages)

    if not messages:
        raise HTTPException(
            status_code=400,
            detail="No valid messages provided. Supply raw WhatsApp 'text' or a 'messages' list.",
        )

    try:
        created_cases = process_intake(session=db, messages=messages)
        touch_activity(db)
        return created_cases
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Intake processing failed: {str(e)}")


@rights_router.post("/classify", status_code=status.HTTP_200_OK)
def classify_rights_intent(payload: ClassifyRequest):
    """
    Classifies a single message text:
    1. Rules first (intents.yaml: English, Hinglish, Kannada-in-Latin).
    2. AI client fallback if rules return none (marked 'inferred').
    """
    result = classify_message(payload.text)
    return result


# -------------------------------------------------------------
# Case Lifecycle Endpoints
# -------------------------------------------------------------
@cases_router.get("", status_code=status.HTTP_200_OK)
def list_cases(
    status: Optional[str] = Query(None, description="Filter by case status"),
    intent: Optional[str] = Query(None, description="Filter by case intent"),
    db: Session = Depends(get_db),
):
    """Lists rights cases with optional status or intent filtering."""
    query = db.query(RightsCase)
    if status:
        query = query.filter(RightsCase.status == status)
    if intent:
        query = query.filter(RightsCase.intent == intent)

    cases = query.order_by(RightsCase.created_at.desc()).all()
    return [serialize_case(c) for c in cases]


@cases_router.get("/{case_id}", status_code=status.HTTP_200_OK)
def get_case_details(
    case_id: str,
    db: Session = Depends(get_db),
):
    """Retrieves full case details by integer id or case_ref."""
    case = get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    return serialize_case(case)


@cases_router.post("/{case_id}/confirm-identity", status_code=status.HTTP_200_OK)
def confirm_identity_endpoint(
    case_id: str,
    db: Session = Depends(get_db),
):
    """
    Owner confirms the identity of the requester.
    Transitions status to identity_check and unblocks probable execution.
    Logs case_identity to ledger.
    """
    try:
        case = confirm_identity_for_case(db, case_id)
        touch_activity(db)
        return serialize_case(case)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Confirm identity failed: {str(e)}")


@cases_router.post("/{case_id}/plan", status_code=status.HTTP_200_OK)
def create_plan_endpoint(
    case_id: str,
    db: Session = Depends(get_db),
):
    """
    Compiles an erasure plan for the case via K8 erasure engine.
    Transitions status to plan.
    Logs case_plan to ledger.
    """
    try:
        case = create_plan_for_case(db, case_id)
        touch_activity(db)
        return serialize_case(case)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Plan creation failed: {str(e)}")


@cases_router.post("/{case_id}/approve", status_code=status.HTTP_200_OK)
def approve_case_endpoint(
    case_id: str,
    payload: ApproveCaseRequest,
    db: Session = Depends(get_db),
):
    """
    Approves the case erasure plan using the matching SHA-256 plan hash.
    Transitions status to approved.
    Logs case_approved to ledger.
    """
    try:
        case = approve_case(db, case_id, payload.confirm_hash)
        touch_activity(db)
        return serialize_case(case)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Approve case failed: {str(e)}")


@cases_router.post("/{case_id}/execute", status_code=status.HTTP_200_OK)
def execute_case_endpoint(
    case_id: str,
    db: Session = Depends(get_db),
):
    """
    Executes the approved erasure plan.
    Enforces identity gate: probable match blocks execution without owner confirmation.
    Transitions status to executed.
    Logs case_executed to ledger.
    """
    try:
        case = execute_case(db, case_id)
        touch_activity(db)
        return serialize_case(case)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@cases_router.post("/{case_id}/close", status_code=status.HTTP_200_OK)
def close_case_endpoint(
    case_id: str,
    db: Session = Depends(get_db),
):
    """
    Closes the case after fulfillment.
    Transitions status to closed.
    Logs case_closed to ledger.
    """
    try:
        case = close_case(db, case_id)
        touch_activity(db)
        return serialize_case(case)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Close case failed: {str(e)}")
