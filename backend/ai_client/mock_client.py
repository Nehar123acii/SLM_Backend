import logging
import re
from typing import Any, Dict, List, Optional
from backend.config import settings

logger = logging.getLogger("ai_client")


class AIClient:
    """
    AI module client.
    Supports 'mock' mode for deterministic testing without external SLM/Ollama services.
    """

    def __init__(self, mode: Optional[str] = None):
        self.mode = mode or settings.ai_mode

    def invoke(self, request_envelope: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processes an AI contract request envelope.
        Logs ONLY task and version — NEVER logs the payload content.
        """
        task = request_envelope.get("task", "")
        version = request_envelope.get("version", "1")
        payload = request_envelope.get("payload", {})

        # Safe logging: task and version only
        logger.info("Executing AI task '%s' (version %s)", task, version)

        if self.mode == "live":
            raise NotImplementedError(
                "Live Ollama inference endpoint is not configured. Run with AI_MODE='mock'."
            )

        if task == "classify_columns":
            return self._mock_classify_columns(task, version, payload)
        elif task == "contextual_privacy_findings":
            return self._mock_contextual_privacy_findings(task, version, payload)
        elif task == "classify_privacy_request":
            return self._mock_classify_privacy_request(task, version, payload)
        elif task == "extract_breach_details":
            return self._mock_extract_breach_details(task, version, payload)
        else:
            return {
                "task": task,
                "version": version,
                "status": "error",
                "needs_human_review": True,
                "result": None,
                "warnings": [],
                "error": {
                    "code": "INVALID_INPUT",
                    "message": f"Unknown task '{task}'",
                },
            }

    def _mock_classify_columns(
        self, task: str, version: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        columns = payload.get("columns", [])
        classifications: List[Dict[str, Any]] = []
        needs_human_review = False

        sensitive_keywords = [
            "aadhaar", "pan", "passport", "biometric", "fingerprint",
            "iris", "health", "medical",
        ]

        for col in columns:
            name = str(col.get("name", "")).lower()
            inferred_type = col.get("inferred_type", "TEXT")

            category = "NON_PERSONAL"
            sensitivity = "NON_PERSONAL_DATA"
            confidence = 0.85
            explanation = f"Evaluated column '{name}'."
            dpdp_basis: Optional[str] = None

            if any(k in name for k in ["pan", "aadhaar", "passport", "voter"]):
                category = "GOVERNMENT_ID"
                sensitivity = "SENSITIVE_PERSONAL_DATA"
                confidence = 0.95
                explanation = f"Government identifier fragment identified in {name}."
                dpdp_basis = "Section 2(t), IT Rules Schedule II"
            elif any(k in name for k in ["biometric", "fingerprint", "iris"]):
                category = "BIOMETRIC"
                sensitivity = "SENSITIVE_PERSONAL_DATA"
                confidence = 0.95
                explanation = "Biometric data requires strict processing safeguards."
                dpdp_basis = "Section 2(t)"
            elif any(k in name for k in ["health", "medical"]):
                category = "HEALTH"
                sensitivity = "SENSITIVE_PERSONAL_DATA"
                confidence = 0.92
                explanation = "Health and medical records represent sensitive personal data."
                dpdp_basis = "Section 2(t)"
            elif any(k in name for k in ["email", "phone", "mobile", "city", "pincode", "address"]) or inferred_type in ["EMAIL", "PHONE"]:
                category = "CONTACT"
                sensitivity = "PERSONAL_DATA"
                confidence = 0.90
                explanation = f"Contact or location details in column {name}."
                dpdp_basis = "Section 2(t)"
            elif any(k in name for k in ["name", "fname", "lname", "first_name", "last_name", "customer_id"]):
                category = "IDENTITY"
                sensitivity = "PERSONAL_DATA"
                confidence = 0.95
                explanation = f"Identifier directly associated with a natural person ({name})."
                dpdp_basis = "Section 2(t)"
            elif any(k in name for k in ["amount", "purchase", "salary", "price", "card", "bank"]):
                category = "FINANCIAL"
                sensitivity = "PERSONAL_DATA"
                confidence = 0.82
                explanation = f"Financial attribute linked to principal in column {name}."
                dpdp_basis = None
            else:
                category = "NON_PERSONAL"
                sensitivity = "NON_PERSONAL_DATA"
                confidence = 0.78
                explanation = f"Attribute '{name}' has general non-personal characteristics."
                dpdp_basis = None

            # Trigger check: aadhaar, pan, passport, biometric, fingerprint, iris, health, medical
            if any(k in name for k in sensitive_keywords) or sensitivity == "SENSITIVE_PERSONAL_DATA" or confidence < 0.70:
                needs_human_review = True

            classifications.append({
                "column_name": col.get("name"),
                "category": category,
                "sensitivity": sensitivity,
                "confidence": round(confidence, 2),
                "explanation": explanation[:200],
                "dpdp_basis": dpdp_basis,
            })

        return {
            "task": task,
            "version": version,
            "status": "ok",
            "needs_human_review": needs_human_review,
            "result": {"classifications": classifications},
            "warnings": [],
            "error": None,
        }

    def _mock_contextual_privacy_findings(
        self, task: str, version: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        cross_border = payload.get("cross_border", False)
        consent_collected = payload.get("consent_collected", True)
        retention_days = payload.get("retention_days")

        findings: List[Dict[str, Any]] = []

        if not consent_collected:
            findings.append({
                "finding_id": "F-001",
                "title": "Missing explicit consent basis",
                "description": "Processing data without verifiable explicit consent under the DPDP Act.",
                "severity": "HIGH",
                "category": "CONSENT",
                "recommendation": "Obtain explicit opt-in consent and provide clear notice before processing.",
                "dpdp_reference": "Section 6, DPDP Act 2023",
            })

        if retention_days is None:
            findings.append({
                "finding_id": "F-002",
                "title": "Indefinite data retention period",
                "description": "No retention period defined; personal data must not be stored beyond necessity.",
                "severity": "MEDIUM",
                "category": "RETENTION",
                "recommendation": "Define a retention policy and schedule automated review or erasure.",
                "dpdp_reference": "Section 8(7), DPDP Act 2023",
            })

        if cross_border:
            findings.append({
                "finding_id": "F-003",
                "title": "Cross-border data transfer without documented safeguard",
                "description": "Personal data is transmitted outside Indian territory without confirmed bilateral safeguards.",
                "severity": "HIGH",
                "category": "CROSS_BORDER_TRANSFER",
                "recommendation": "Verify whether destination country is permitted under government notifications.",
                "dpdp_reference": "Section 16, DPDP Act 2023",
            })

        # needs_human_review triggers:
        # - Any finding with severity HIGH or CRITICAL
        # - cross_border=True or consent_collected=False
        # - total findings >= 5
        needs_human_review = bool(
            cross_border
            or not consent_collected
            or any(f["severity"] in ["HIGH", "CRITICAL"] for f in findings)
            or len(findings) >= 5
        )

        summary = (
            f"Review identified {len(findings)} privacy issue(s). "
            + ("High-risk issues require immediate business review." if needs_human_review else "Overall posture is acceptable.")
        )

        return {
            "task": task,
            "version": version,
            "status": "ok",
            "needs_human_review": needs_human_review,
            "result": {
                "findings": findings,
                "summary": summary,
            },
            "warnings": [],
            "error": None,
        }

    def _mock_classify_privacy_request(
        self, task: str, version: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        raw_text = str(payload.get("raw_text", "")).lower()

        request_types: List[str] = []
        if any(w in raw_text for w in ["access", "summary", "copy", "know what", "stored about me", "information you have"]):
            request_types.append("ACCESS")
        if any(w in raw_text for w in ["correct", "update", "changed", "modify", "phone number has changed"]):
            request_types.append("CORRECTION")
        if any(w in raw_text for w in ["delete", "erase", "remove", "erasure"]):
            request_types.append("ERASURE")
        if any(w in raw_text for w in ["withdraw", "revoke", "consent", "stop sending"]):
            request_types.append("WITHDRAW_CONSENT")
        if any(w in raw_text for w in ["nominate", "nominee", "nomination"]):
            request_types.append("NOMINATION")
        if any(w in raw_text for w in ["grievance", "complaint", "dissatisfied"]):
            request_types.append("GRIEVANCE")

        if not request_types:
            request_types = ["ACCESS"]

        is_composite = len(request_types) > 1

        urgency = "LOW"
        if any(w in raw_text for w in ["legal", "court", "lawyer", "police", "board", "sue", "penalty", "action"]):
            urgency = "HIGH"
        elif any(w in raw_text for w in ["urgent", "immediately", "asap"]):
            urgency = "MEDIUM"

        subject_reference = "customer" if "customer" in raw_text else "data principal"

        return {
            "task": task,
            "version": version,
            "status": "ok",
            "needs_human_review": True,  # Safe default for mock
            "result": {
                "request_types": request_types,
                "is_composite": is_composite,
                "confidence": 0.91,
                "urgency": urgency,
                "subject_reference": subject_reference,
                "data_scope_hint": "Records matching data principal identification",
                "suggested_response_outline": "Acknowledge receipt and outline statutory response timeline.",
                "ambiguities": [
                    "Requester identity proof needs verification against customer records."
                ],
            },
            "warnings": [],
            "error": None,
        }

    def _mock_extract_breach_details(
        self, task: str, version: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        report_text = str(payload.get("report_text", ""))
        text_lower = report_text.lower()

        incident_type = "UNAUTHORISED_ACCESS"
        if any(w in text_lower for w in ["accidental", "mistake", "inadvertently", "bucket", "public"]):
            incident_type = "ACCIDENTAL_DISCLOSURE"
        elif "ransomware" in text_lower or "encrypt" in text_lower:
            incident_type = "RANSOMWARE"
        elif "leak" in text_lower or "dump" in text_lower:
            incident_type = "DATA_LEAK"
        elif "phish" in text_lower:
            incident_type = "PHISHING"
        elif "lost" in text_lower or "stolen" in text_lower:
            incident_type = "LOST_DEVICE"

        # Extract numbers like 3,000 or 500
        count_match = re.search(r"(\d[\d,]*)\s*(?:customers?|users?|records?|people|principals?)", text_lower)
        estimated_count: Optional[int] = None
        count_confidence = "UNKNOWN"
        if count_match:
            try:
                estimated_count = int(count_match.group(1).replace(",", ""))
                count_confidence = "ESTIMATE"
            except ValueError:
                pass

        containment_steps: List[str] = []
        if "private" in text_lower:
            containment_steps.append("Bucket permissions updated to private.")
        if "removed" in text_lower or "deleted" in text_lower:
            containment_steps.append("Exposed backup file deleted.")
        if not containment_steps:
            containment_steps.append("Investigation initiated.")

        # Notification likely required if customer count > 0 or sensitive/contact data exposed
        notification_likely = estimated_count is not None and estimated_count > 100

        return {
            "task": task,
            "version": version,
            "status": "ok",
            "needs_human_review": True,  # Mandatory per contract: always True
            "result": {
                "incident_type": incident_type,
                "discovery_datetime_hint": payload.get("report_timestamp"),
                "affected_data_categories": ["IDENTITY", "CONTACT"],
                "estimated_affected_count": estimated_count,
                "count_confidence": count_confidence,
                "potential_harm": [
                    "IDENTITY_THEFT",
                    "LOSS_OF_CONFIDENTIALITY",
                    "REPUTATIONAL_DAMAGE",
                ],
                "containment_steps_mentioned": containment_steps,
                "notification_likely_required": notification_likely,
                "notification_reasoning": "Exposed customer identity and contact information creates risk of harm under DPDP Act.",
                "draft_summary": f"Incident of type {incident_type} reported. Initial containment actions taken. Review required to determine statutory notification obligations.",
                "open_questions": [
                    "Confirm exact window of exposure.",
                    "Verify if logs show external unauthorized access during exposure.",
                ],
            },
            "warnings": [],
            "error": None,
        }


def get_ai_client() -> AIClient:
    return AIClient()
