from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.db.models import PrivacyRequest, Dataset
from backend.ai_client.mock_client import get_ai_client

logger = logging.getLogger("privacy_requests_service")

SLA_DAYS = {
    "HIGH": 7,
    "MEDIUM": 15,
    "LOW": 30,
}


def generate_request_id(db: Session) -> str:
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"req_{today_str}_"
    count = db.query(PrivacyRequest).filter(PrivacyRequest.request_id.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:03d}"


class PrivacyRequestService:
    @staticmethod
    def create_request(
        db: Session,
        raw_text: str,
        submission_channel: str = "web_form",
    ) -> PrivacyRequest:
        request_id = generate_request_id(db)

        # Call AI mock client
        ai_client = get_ai_client()
        ai_resp = ai_client.invoke({
            "task": "classify_privacy_request",
            "version": "1",
            "payload": {
                "request_id": request_id,
                "raw_text": raw_text,
                "submission_channel": submission_channel,
            },
        })

        ai_result = ai_resp.get("result", {})
        request_types = ai_result.get("request_types", ["ACCESS"])
        is_composite = ai_result.get("is_composite", False)
        urgency = ai_result.get("urgency", "MEDIUM")
        confidence = ai_result.get("confidence")
        subject_ref = ai_result.get("subject_reference")
        data_scope_hint = ai_result.get("data_scope_hint")
        response_outline = ai_result.get("suggested_response_outline")
        ambiguities = ai_result.get("ambiguities", [])
        needs_human_review = ai_resp.get("needs_human_review", True)

        # Calculate SLA deadline
        now = datetime.now(timezone.utc)
        days = SLA_DAYS.get(urgency, 15)
        sla_deadline = now + timedelta(days=days)

        # Generate checklist
        datasets = db.query(Dataset).all()
        checklist_items = [
            {"task": "Verify identity of requester", "completed": False}
        ]
        if datasets:
            for ds in datasets:
                checklist_items.append({
                    "task": f"Locate relevant records in inventory dataset: {ds.dataset_id} ({ds.original_filename})",
                    "completed": False,
                })
        else:
            checklist_items.append({
                "task": "Locate all relevant data sources across systems",
                "completed": False,
            })

        checklist_items.extend([
            {"task": "Prepare response / fulfil request", "completed": False},
            {"task": "Send acknowledgement to requester", "completed": False},
            {"task": "Record outcome and close case", "completed": False},
        ])

        initial_status = "PENDING_REVIEW" if needs_human_review else "RECEIVED"

        # Log only non-PII metrics
        logger.info(
            "Created privacy request %s (urgency=%s, composite=%s, types=%s)",
            request_id,
            urgency,
            is_composite,
            request_types,
        )

        req_obj = PrivacyRequest(
            request_id=request_id,
            submission_channel=submission_channel,
            raw_text=raw_text,
            request_types=json.dumps(request_types),
            is_composite=is_composite,
            urgency=urgency,
            status=initial_status,
            needs_human_review=needs_human_review,
            ai_confidence=confidence,
            subject_reference=subject_ref,
            data_scope_hint=data_scope_hint,
            suggested_response_outline=response_outline,
            ambiguities=json.dumps(ambiguities),
            checklist=json.dumps(checklist_items),
            sla_deadline=sla_deadline,
        )
        db.add(req_obj)
        db.commit()
        db.refresh(req_obj)
        return req_obj

    @staticmethod
    def update_status(db: Session, request_id: str, new_status: str) -> Optional[PrivacyRequest]:
        req_obj = db.query(PrivacyRequest).filter_by(request_id=request_id).first()
        if not req_obj:
            return None
        req_obj.status = new_status
        db.commit()
        db.refresh(req_obj)
        return req_obj

    @staticmethod
    def update_checklist(db: Session, request_id: str, new_checklist: List[Any]) -> Optional[PrivacyRequest]:
        req_obj = db.query(PrivacyRequest).filter_by(request_id=request_id).first()
        if not req_obj:
            return None
        req_obj.checklist = json.dumps(new_checklist)
        db.commit()
        db.refresh(req_obj)
        return req_obj
