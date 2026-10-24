from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.db.models import Incident
from backend.ai_client.mock_client import get_ai_client

logger = logging.getLogger("incidents_service")

STANDARD_BREACH_CHECKLIST = [
    {"step": 1, "task": "Confirm incident scope and affected systems", "completed": False},
    {"step": 2, "task": "Isolate / contain the breach", "completed": False},
    {"step": 3, "task": "Preserve evidence (logs, screenshots, access records)", "completed": False},
    {"step": 4, "task": "Assess affected data categories and number of principals", "completed": False},
    {"step": 5, "task": "Determine notification obligation (DPDP Act Section 8)", "completed": False},
    {"step": 6, "task": "Notify Data Protection Board if required", "completed": False},
    {"step": 7, "task": "Notify affected data principals if required", "completed": False},
    {"step": 8, "task": "Document all response actions", "completed": False},
    {"step": 9, "task": "Conduct post-incident review", "completed": False},
    {"step": 10, "task": "Implement remediation measures", "completed": False},
]


def generate_incident_ref(db: Session) -> str:
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"inc_{today_str}_"
    count = db.query(Incident).filter(Incident.incident_ref.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:03d}"


class IncidentService:
    @staticmethod
    def create_incident(
        db: Session,
        report_text: str,
        reporter_role: Optional[str] = None,
        discovery_datetime_hint: Optional[str] = None,
    ) -> Incident:
        incident_ref = generate_incident_ref(db)

        # Call AI mock client
        ai_client = get_ai_client()
        ai_resp = ai_client.invoke({
            "task": "extract_breach_details",
            "version": "1",
            "payload": {
                "incident_ref": incident_ref,
                "report_text": report_text,
                "reporter_role": reporter_role,
                "report_timestamp": discovery_datetime_hint or datetime.now(timezone.utc).isoformat(),
            },
        })

        ai_result = ai_resp.get("result", {})
        incident_type = ai_result.get("incident_type", "UNAUTHORISED_ACCESS")
        discovery_hint = ai_result.get("discovery_datetime_hint") or discovery_datetime_hint
        affected_categories = ai_result.get("affected_data_categories", [])
        estimated_count = ai_result.get("estimated_affected_count")
        count_confidence = ai_result.get("count_confidence", "UNKNOWN")
        potential_harm = ai_result.get("potential_harm", [])
        containment_steps = ai_result.get("containment_steps_mentioned", [])
        notif_required = ai_result.get("notification_likely_required", False)
        notif_reasoning = ai_result.get("notification_reasoning")
        draft_summary = ai_result.get("draft_summary")
        open_questions = ai_result.get("open_questions", [])
        needs_human_review = ai_resp.get("needs_human_review", True)

        logger.info(
            "Created incident %s (type=%s, estimated_count=%s)",
            incident_ref,
            incident_type,
            estimated_count,
        )

        incident_obj = Incident(
            incident_ref=incident_ref,
            reporter_role=reporter_role,
            report_text=report_text,
            incident_type=incident_type,
            discovery_datetime_hint=discovery_hint,
            affected_data_categories=json.dumps(affected_categories),
            estimated_affected_count=estimated_count,
            count_confidence=count_confidence,
            potential_harm=json.dumps(potential_harm),
            containment_steps=json.dumps(containment_steps),
            notification_likely_required=notif_required,
            notification_reasoning=notif_reasoning,
            draft_summary=draft_summary,
            open_questions=json.dumps(open_questions),
            status="DRAFT",
            needs_human_review=needs_human_review,
            checklist=json.dumps(STANDARD_BREACH_CHECKLIST),
            evidence_refs=json.dumps([]),
        )

        db.add(incident_obj)
        db.commit()
        db.refresh(incident_obj)
        return incident_obj

    @staticmethod
    def update_status(db: Session, incident_ref: str, new_status: str) -> Optional[Incident]:
        incident = db.query(Incident).filter_by(incident_ref=incident_ref).first()
        if not incident:
            return None
        incident.status = new_status
        db.commit()
        db.refresh(incident)
        return incident

    @staticmethod
    def update_checklist(db: Session, incident_ref: str, new_checklist: List[Any]) -> Optional[Incident]:
        incident = db.query(Incident).filter_by(incident_ref=incident_ref).first()
        if not incident:
            return None
        incident.checklist = json.dumps(new_checklist)
        db.commit()
        db.refresh(incident)
        return incident

    @staticmethod
    def append_evidence(db: Session, incident_ref: str, evidence_ref: str) -> Optional[Incident]:
        incident = db.query(Incident).filter_by(incident_ref=incident_ref).first()
        if not incident:
            return None
        current_refs: List[str] = json.loads(incident.evidence_refs) if incident.evidence_refs else []
        current_refs.append(evidence_ref)
        incident.evidence_refs = json.dumps(current_refs)
        db.commit()
        db.refresh(incident)
        return incident
