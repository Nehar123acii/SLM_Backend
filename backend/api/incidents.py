import json
from typing import Any, Dict, List, Optional
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
    NoticeSentCreate,
    NoticeSentResponse,
)
from backend.services.breach import (
    blast_radius,
    calculate_clocks,
    generate_board_detailed_report,
    generate_board_first_intimation,
    generate_individual_notice,
    get_notices_sent_summary,
    get_ordered_checklist,
)
from backend.services.incidents import IncidentService

router = APIRouter(tags=["incidents"])


def serialize_incident(inc: Incident) -> dict:
    return {
        "id": inc.id,
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
        "affected_source_ids": json.loads(inc.affected_source_ids) if getattr(inc, "affected_source_ids", None) else [],
        "aware_at": inc.aware_at.isoformat() if getattr(inc, "aware_at", None) else None,
        "board_extension_requested": getattr(inc, "board_extension_requested", False),
        "severity_level": getattr(inc, "severity_level", "MEDIUM"),
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
    Rejects report text containing raw personal data identifiers.
    Logs incident_opened to tamper-evident ledger.
    """
    try:
        inc = IncidentService.create_incident(
            db=db,
            report_text=payload.report_text,
            reporter_role=payload.reporter_role,
            discovery_datetime_hint=payload.discovery_datetime_hint,
            incident_type=payload.incident_type,
            affected_source_ids=payload.affected_source_ids,
            aware_at=payload.aware_at,
            board_extension_requested=payload.board_extension_requested,
            severity_level=payload.severity_level,
        )
        return serialize_incident(inc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Incident creation failed: {str(e)}")


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
    Retrieves full details of a breach incident (accepts numeric id or incident_ref).
    """
    inc = IncidentService.get_incident(db, incident_ref)
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
    Updates the checklist items for an incident and records incident_step in ledger.
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


@router.post("/{incident_ref}/notices-sent", response_model=NoticeSentResponse, status_code=status.HTTP_201_CREATED)
def record_notice_sent_endpoint(
    incident_ref: str,
    payload: NoticeSentCreate,
    db: Session = Depends(get_db),
):
    """
    Records a sent breach notification (recipient person_id, channel, timestamp, notice_type).
    Stores zero contact values or personal data.
    Appends notice_sent event to ledger.
    """
    inc = IncidentService.get_incident(db, incident_ref)
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_ref}' not found.")

    record = IncidentService.record_notice_sent(
        db=db,
        incident_ref_or_id=inc.id,
        recipient_ref=payload.recipient_ref,
        channel=payload.channel,
        notice_type=payload.notice_type,
        sent_at=payload.sent_at,
    )
    return {
        "id": record.id,
        "incident_id": record.incident_id,
        "incident_ref": record.incident_ref,
        "recipient_ref": record.recipient_ref,
        "channel": record.channel,
        "notice_type": record.notice_type,
        "sent_at": record.sent_at,
    }


@router.get("/{incident_ref}/clocks")
def get_incident_clocks(
    incident_ref: str,
    db: Session = Depends(get_db),
):
    """
    Returns statutory DPDP Rule 7 countdown clocks for an incident.
    Module label: 'readiness for obligations from May 2027'.
    """
    inc = IncidentService.get_incident(db, incident_ref)
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_ref}' not found.")

    aware_at = inc.aware_at or inc.created_at
    board_ext = bool(getattr(inc, "board_extension_requested", False))

    clocks = calculate_clocks(
        aware_at=aware_at,
        board_extension_requested=board_ext,
    )
    return clocks


@router.get("/{incident_ref}/checklist")
def get_incident_checklist(
    incident_ref: str,
    lang: str = "en",
    db: Session = Depends(get_db),
):
    """
    Returns the ordered 6-stage operational incident response checklist:
    1. Contain
    2. Preserve Evidence
    3. Assess
    4. Notify
    5. Recover
    6. Review
    """
    inc = IncidentService.get_incident(db, incident_ref)
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_ref}' not found.")

    return get_ordered_checklist(lang=lang)


@router.get("/{incident_ref}/notices")
def get_incident_draft_notices(
    incident_ref: str,
    lang: str = "en",
    db: Session = Depends(get_db),
):
    """
    Generates draft statutory notices keyed to required clauses.
    All outputs strictly marked DRAFT SIMULATION. Zero raw PII.
    Item (vi) of Board Detailed Report auto-populates summary from notices_sent table.
    """
    inc = IncidentService.get_incident(db, incident_ref)
    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_ref}' not found.")

    aware_at = inc.aware_at or inc.created_at
    affected_sources: List[str] = []
    if getattr(inc, "affected_source_ids", None):
        try:
            affected_sources = json.loads(inc.affected_source_ids)
        except Exception:
            pass

    # Compute blast radius from affected sources if available
    blast = blast_radius(db, affected_sources)
    categories = list(blast.get("category_breakdown", {}).keys())

    # Get notices sent summary
    notices_sent_summary = get_notices_sent_summary(db, incident_id=inc.id, incident_ref=inc.incident_ref)

    scenario_title = f"{inc.incident_type.replace('_', ' ').title()}"
    scenario_desc = inc.draft_summary or "Security incident requiring containment and regulatory assessment."

    individual_notice = generate_individual_notice(
        scenario_title=scenario_title,
        scenario_desc=scenario_desc,
        categories=categories,
        aware_at_dt=aware_at,
        lang=lang,
    )

    board_first = generate_board_first_intimation(
        scenario_title=scenario_title,
        scenario_desc=scenario_desc,
        exposure_types=["confidentiality"],
        affected_sources=affected_sources,
        records_count=blast.get("records_count", 0),
        confirmed_people=blast.get("confirmed_people", 0),
        possible_people=blast.get("possible_people", 0),
        categories=categories,
        aware_at_dt=aware_at,
    )

    board_detailed = generate_board_detailed_report(
        scenario_title=scenario_title,
        scenario_desc=scenario_desc,
        exposure_types=["confidentiality"],
        affected_sources=affected_sources,
        records_count=blast.get("records_count", 0),
        confirmed_people=blast.get("confirmed_people", 0),
        possible_people=blast.get("possible_people", 0),
        categories=categories,
        aware_at_dt=aware_at,
        notices_sent_summary=notices_sent_summary,
    )

    return {
        "incident_ref": inc.incident_ref,
        "notices": {
            "individual_notice": individual_notice,
            "board_first_intimation": board_first,
            "board_detailed_report": board_detailed,
        },
        "notices_sent_summary": notices_sent_summary,
        "only_channel_warnings": blast.get("only_channel_warnings", []),
        "watermark": "DRAFT SIMULATION",
    }
