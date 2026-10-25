from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Union
from sqlalchemy.orm import Session

from backend.db.models import Incident, NoticeSent
from backend.ai_client.mock_client import get_ai_client
from backend.services.breach import (
    blast_radius,
    calculate_clocks,
    calculate_severity,
    generate_board_detailed_report,
    generate_board_first_intimation,
    generate_individual_notice,
    get_notices_sent_summary,
    get_ordered_checklist,
    validate_incident_text,
)
from backend.services.ledger import append_event

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
    def get_incident(db: Session, id_or_ref: Union[int, str]) -> Optional[Incident]:
        """Look up incident by integer id or string incident_ref."""
        if isinstance(id_or_ref, int) or (isinstance(id_or_ref, str) and id_or_ref.isdigit()):
            inc = db.query(Incident).filter_by(id=int(id_or_ref)).first()
            if inc:
                return inc
        return db.query(Incident).filter_by(incident_ref=str(id_or_ref)).first()

    @staticmethod
    def create_incident(
        db: Session,
        report_text: str,
        reporter_role: Optional[str] = None,
        discovery_datetime_hint: Optional[str] = None,
        incident_type: Optional[str] = None,
        affected_source_ids: Optional[List[str]] = None,
        aware_at: Optional[Union[datetime, str]] = None,
        board_extension_requested: bool = False,
        severity_level: Optional[str] = None,
    ) -> Incident:
        # PII Guard: Validate that raw personal data is never persisted in incident narrative
        validate_incident_text(report_text)

        incident_ref = generate_incident_ref(db)

        # Call AI mock client for initial assessment
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
        # If incident_type was explicitly supplied, respect it; otherwise use AI extraction
        final_incident_type = incident_type or ai_result.get("incident_type", "UNAUTHORISED_ACCESS")
        discovery_hint = ai_result.get("discovery_datetime_hint") or discovery_datetime_hint
        affected_categories = ai_result.get("affected_data_categories", [])
        estimated_count = ai_result.get("estimated_affected_count")
        count_confidence = ai_result.get("count_confidence", "UNKNOWN")
        potential_harm = ai_result.get("potential_harm", [])
        containment_steps = ai_result.get("containment_steps_mentioned", [])
        notif_required = ai_result.get("notification_likely_required", False)
        notif_reasoning = ai_result.get("notification_reasoning")
        draft_summary = ai_result.get("draft_summary")
        if draft_summary:
            validate_incident_text(draft_summary)

        open_questions = ai_result.get("open_questions", [])
        needs_human_review = ai_resp.get("needs_human_review", True)

        aware_at_dt: Optional[datetime] = None
        if aware_at:
            if isinstance(aware_at, str):
                aware_at_dt = datetime.fromisoformat(aware_at.replace("Z", "+00:00"))
            else:
                aware_at_dt = aware_at

        incident_obj = Incident(
            incident_ref=incident_ref,
            reporter_role=reporter_role,
            report_text=report_text,
            incident_type=final_incident_type,
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
            affected_source_ids=json.dumps(affected_source_ids or []),
            aware_at=aware_at_dt,
            board_extension_requested=board_extension_requested,
            severity_level=(severity_level or "MEDIUM").upper(),
        )

        db.add(incident_obj)
        db.flush()

        # Log incident_opened event to tamper-evident ledger (ids, counts, enums only)
        try:
            append_event(
                db,
                "incident_opened",
                {
                    "incident_id": incident_obj.id,
                    "incident_ref": incident_ref,
                    "incident_type": final_incident_type,
                    "status": "DRAFT",
                },
            )
        except Exception as e:
            logger.warning("Could not append incident_opened to ledger: %s", e)

        db.commit()
        db.refresh(incident_obj)

        logger.info(
            "Created incident %s (type=%s, estimated_count=%s)",
            incident_ref,
            final_incident_type,
            estimated_count,
        )
        return incident_obj

    @staticmethod
    def update_status(db: Session, incident_ref: str, new_status: str) -> Optional[Incident]:
        incident = IncidentService.get_incident(db, incident_ref)
        if not incident:
            return None
        incident.status = new_status
        db.commit()
        db.refresh(incident)
        return incident

    @staticmethod
    def update_checklist(db: Session, incident_ref: str, new_checklist: List[Any]) -> Optional[Incident]:
        incident = IncidentService.get_incident(db, incident_ref)
        if not incident:
            return None
        incident.checklist = json.dumps(new_checklist)
        db.flush()

        # Log completed steps to ledger
        try:
            completed_steps = [item.get("step") for item in new_checklist if item.get("completed") is True]
            append_event(
                db,
                "incident_step",
                {
                    "incident_id": incident.id,
                    "incident_ref": incident.incident_ref,
                    "completed_count": len(completed_steps),
                    "steps": [int(s) for s in completed_steps if s is not None],
                },
            )
        except Exception as e:
            logger.warning("Could not append incident_step to ledger: %s", e)

        db.commit()
        db.refresh(incident)
        return incident

    @staticmethod
    def append_evidence(db: Session, incident_ref: str, evidence_ref: str) -> Optional[Incident]:
        incident = IncidentService.get_incident(db, incident_ref)
        if not incident:
            return None
        current_refs: List[str] = json.loads(incident.evidence_refs) if incident.evidence_refs else []
        current_refs.append(evidence_ref)
        incident.evidence_refs = json.dumps(current_refs)
        db.commit()
        db.refresh(incident)
        return incident

    @staticmethod
    def record_notice_sent(
        db: Session,
        incident_ref_or_id: Union[str, int],
        recipient_ref: int,
        channel: str,
        notice_type: str,
        sent_at: Optional[datetime] = None,
    ) -> NoticeSent:
        """
        Records a statutory or individual notice sent.
        Appends notice_sent event to ledger (ids, counts, enums only; zero contact values).
        """
        incident = IncidentService.get_incident(db, incident_ref_or_id)
        inc_id = incident.id if incident else (int(incident_ref_or_id) if str(incident_ref_or_id).isdigit() else None)
        inc_ref = incident.incident_ref if incident else str(incident_ref_or_id)

        sent_time = sent_at or datetime.now(timezone.utc)
        record = NoticeSent(
            incident_id=inc_id,
            incident_ref=inc_ref,
            recipient_ref=recipient_ref,
            channel=channel.lower().strip(),
            notice_type=notice_type.lower().strip(),
            sent_at=sent_time,
        )
        db.add(record)
        db.flush()

        # Log notice_sent to ledger
        append_event(
            db,
            "notice_sent",
            {
                "incident_id": inc_id,
                "recipient_ref": recipient_ref,
                "channel": channel.lower().strip(),
                "notice_type": notice_type.lower().strip(),
            },
        )
        db.commit()
        db.refresh(record)
        return record
