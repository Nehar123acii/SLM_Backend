import json
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.db.models import PrivacyRequest
from backend.schemas import (
    PrivacyRequestCreate,
    PrivacyRequestResponse,
    PrivacyRequestStatusUpdate,
    PrivacyRequestChecklistUpdate,
)
from backend.services.privacy_requests import PrivacyRequestService

# TODO: Add authentication & authorization layer before production deployment

router = APIRouter(prefix="/api/v1/privacy-requests", tags=["privacy-requests"])


def serialize_privacy_request(req: PrivacyRequest) -> dict:
    return {
        "request_id": req.request_id,
        "submission_channel": req.submission_channel,
        "request_types": json.loads(req.request_types) if req.request_types else [],
        "is_composite": req.is_composite,
        "urgency": req.urgency,
        "status": req.status,
        "needs_human_review": req.needs_human_review,
        "ai_confidence": req.ai_confidence,
        "subject_reference": req.subject_reference,
        "data_scope_hint": req.data_scope_hint,
        "suggested_response_outline": req.suggested_response_outline,
        "ambiguities": json.loads(req.ambiguities) if req.ambiguities else [],
        "checklist": json.loads(req.checklist) if req.checklist else [],
        "sla_deadline": req.sla_deadline,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
    }


@router.post("", response_model=PrivacyRequestResponse, status_code=status.HTTP_201_CREATED)
def create_privacy_request(
    payload: PrivacyRequestCreate,
    db: Session = Depends(get_db),
):
    """
    Submits a data principal rights request.
    Invokes mock AI classification, calculates statutory SLA, and generates fulfillment checklist.
    """
    req_obj = PrivacyRequestService.create_request(
        db=db,
        raw_text=payload.raw_text,
        submission_channel=payload.submission_channel,
    )
    return serialize_privacy_request(req_obj)


@router.get("", response_model=List[PrivacyRequestResponse])
def list_privacy_requests(
    status: Optional[str] = Query(None),
    urgency: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Lists data principal requests with optional filtering by status and urgency.
    """
    query = db.query(PrivacyRequest)
    if status:
        query = query.filter(PrivacyRequest.status == status)
    if urgency:
        query = query.filter(PrivacyRequest.urgency == urgency)

    results = query.order_by(PrivacyRequest.created_at.desc()).all()
    return [serialize_privacy_request(r) for r in results]


@router.get("/{request_id}", response_model=PrivacyRequestResponse)
def get_privacy_request(
    request_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves full details of a privacy request.
    """
    req_obj = db.query(PrivacyRequest).filter_by(request_id=request_id).first()
    if not req_obj:
        raise HTTPException(status_code=404, detail=f"Privacy request '{request_id}' not found.")
    return serialize_privacy_request(req_obj)


@router.patch("/{request_id}/status", response_model=PrivacyRequestResponse)
def update_privacy_request_status(
    request_id: str,
    payload: PrivacyRequestStatusUpdate,
    db: Session = Depends(get_db),
):
    """
    Updates the workflow lifecycle status of a privacy request.
    """
    req_obj = PrivacyRequestService.update_status(db, request_id, payload.status)
    if not req_obj:
        raise HTTPException(status_code=404, detail=f"Privacy request '{request_id}' not found.")
    return serialize_privacy_request(req_obj)


@router.patch("/{request_id}/checklist", response_model=PrivacyRequestResponse)
def update_privacy_request_checklist(
    request_id: str,
    payload: PrivacyRequestChecklistUpdate,
    db: Session = Depends(get_db),
):
    """
    Updates the checklist items for a privacy request.
    """
    req_obj = PrivacyRequestService.update_checklist(db, request_id, payload.checklist)
    if not req_obj:
        raise HTTPException(status_code=404, detail=f"Privacy request '{request_id}' not found.")
    return serialize_privacy_request(req_obj)
