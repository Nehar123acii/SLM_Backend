import json
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.deps import get_db
from backend.db.models import Incident
from backend.schemas import (
    IncidentCreate,
    IncidentResponse,
    IncidentStatusUpdate,
    IncidentChecklistUpdate,
    IncidentEvidenceCreate,
)
from backend.services.incidents import IncidentService

# TODO: Add authentication & authorization layer before production deployment

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


def serialize_incident(inc: Incident) -> dict:
    return {
        "incident_ref": inc.incident_ref,
        "reporter_role": inc.reporter_role,
        "incident_type": inc.incident_type,
        "discovery_datetime_hint": inc.discovery_datetime_hint,
        "affected_data_categories": json.loads(inc.affected_data_categories) if inc.affected_data_categories else [],
        "estimated_affected_count": inc.estimated_affected_count,
        "count_confidence": inc.count_confidence,
        "potential_harm": json.loads(inc.potential_harm) if inc.potential_harm else [],
        "containment_steps": json.loads(inc.containment_steps) if inc.containment_steps else [],
        "notification_likely_required": inc.notification_likely_required,
        "notification_reasoning": inc.notification_reasoning,
        "draft_summary": inc.draft_summary,
        "open_questions": json.loads(inc.open_questions) if inc.open_questions else [],
        "status": inc.status,
        "needs_human_review": inc.needs_human_review,
        "checklist": json.loads(inc.checklist) if inc.checklist else [],
        "evidence_refs": json.loads(inc.evidence_refs) if inc.evidence_refs else [],
        "created_at": inc.created_at,
        "updated_at": inc.updated_at,
    }


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def create_incident(
    payload: IncidentCreate,
    db: Session = Depends(get_db),
):
    """
    Creates a new breach incident record.
    Calls mock AI breach extractor and populates 10-step regulatory response checklist.
    """
    inc = IncidentService.create_incident(
        db=db,
        report_text=payload.report_text,
        reporter_role=payload.reporter_role,
        discovery_datetime_hint=payload.discovery_datetime_hint,
    )
    return serialize_incident(inc)


@router.get("", response_model=List[IncidentResponse])
def list_incidents(
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    Lists breach incidents with optional filtering by status.
    """
    query = db.query(Incident)
    if status:
        query = query.filter(Incident.status == status)
    results = query.order_by(Incident.created_at.desc()).all()
    return [serialize_incident(i) for i in results]


@router.get("/{incident_ref}", response_model=IncidentResponse)
def get_incident(
    incident_ref: str,
    db: Session = Depends(get_db),
):
    """
    Retrieves full details of a breach incident.
    """
    inc = db.query(Incident).filter_by(incident_ref=incident_ref).first()
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_ref}' not found.")
    return serialize_incident(inc)


@router.patch("/{incident_ref}/status", response_model=IncidentResponse)
def update_incident_status(
    incident_ref: str,
    payload: IncidentStatusUpdate,
    db: Session = Depends(get_db),
):
    """
    Updates status of an incident.
    """
    inc = IncidentService.update_status(db, incident_ref, payload.status)
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_ref}' not found.")
    return serialize_incident(inc)


@router.patch("/{incident_ref}/checklist", response_model=IncidentResponse)
def update_incident_checklist(
    incident_ref: str,
    payload: IncidentChecklistUpdate,
    db: Session = Depends(get_db),
):
    """
    Updates the 10-step checklist items for an incident.
    """
    inc = IncidentService.update_checklist(db, incident_ref, payload.checklist)
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_ref}' not found.")
    return serialize_incident(inc)


@router.post("/{incident_ref}/evidence", response_model=IncidentResponse)
def append_incident_evidence(
    incident_ref: str,
    payload: IncidentEvidenceCreate,
    db: Session = Depends(get_db),
):
    """
    Appends an evidence reference string to the incident.
    """
    inc = IncidentService.append_evidence(db, incident_ref, payload.evidence_ref)
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_ref}' not found.")
    return serialize_incident(inc)
