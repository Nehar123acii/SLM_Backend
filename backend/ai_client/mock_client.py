import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import urllib.error

from backend.config import settings
from ai.classifier import classify_columns
from ai.findings import contextual_privacy_findings
from ai.requests_classifier import classify_privacy_request
from ai.breach_extractor import extract_breach_details
from ai.client import OllamaClient, OllamaClientError
from ai.config import AIConfig

logger = logging.getLogger("ai_client")

# Mappings between AI module contract types and legacy backend response formats
LEGACY_CATEGORY_MAP = {
    "GOVERNMENT_ID": "GOVERNMENT_ID",
    "CONTACT_INFO": "CONTACT",
    "IDENTITY_DEMOGRAPHIC": "IDENTITY",
    "FINANCIAL_DATA": "FINANCIAL",
    "HEALTH_MEDICAL": "HEALTH",
    "CHILDREN_DATA": "IDENTITY",
    "BIOMETRIC_GENETIC": "BIOMETRIC",
    "AUTHENTICATION_SECRET": "NON_PERSONAL",
    "BEHAVIORAL_LOCATION": "LOCATION",
    "BUSINESS_NON_PERSONAL": "NON_PERSONAL",
    "UNKNOWN_AMBIGUOUS": "UNCERTAIN",
}

LEGACY_SENSITIVITY_MAP = {
    "CRITICAL_PERSONAL": "SENSITIVE_PERSONAL_DATA",
    "SENSITIVE_PERSONAL": "SENSITIVE_PERSONAL_DATA",
    "GENERAL_PERSONAL": "PERSONAL_DATA",
    "NON_PERSONAL": "NON_PERSONAL_DATA",
    "UNKNOWN": "PERSONAL_DATA",
}

LEGACY_FINDING_CATEGORY_MAP = {
    "OVER_COLLECTION": "DATA_MINIMISATION",
    "MISSING_CONSENT_BASIS": "CONSENT",
    "EXCESSIVE_ACCESS": "SECURITY",
    "MISSING_RETENTION_POLICY": "RETENTION",
    "UNSAFE_COMBINATION": "SECURITY",
    "CHILDREN_DATA_SAFEGUARD_REQUIRED": "CONSENT",
    "THIRD_PARTY_SHARING_RISK": "TRANSPARENCY",
    "VERSION_DRIFT_ESCALATION": "DATA_MINIMISATION",
    "UNSPECIFIED_PURPOSE": "PURPOSE_LIMITATION",
    "OVERRETENTION_RISK": "RETENTION",
    "EXCESSIVE_SENSITIVE_DATA": "DATA_MINIMISATION",
    "CHILDREN_DATA_RISK": "CONSENT",
    "UNGOVERNED_THIRD_PARTY_SHARING": "TRANSPARENCY",
    "CROSS_BORDER_EXPOSURE": "CROSS_BORDER_TRANSFER",
    "INSECURE_STORAGE_SCOPE": "SECURITY",
    "HIGH_RISK_DIFF_ESCALATION": "DATA_MINIMISATION",
    "CONSENT": "CONSENT",
    "RETENTION": "RETENTION",
    "SECURITY": "SECURITY",
}

LEGACY_RIGHT_TYPE_MAP = {
    "ACCESS_SUMMARY": "ACCESS",
    "THIRD_PARTY_SHARING_LIST": "ACCESS",
    "CORRECTION_COMPLETION_UPDATING": "CORRECTION",
    "ERASURE": "ERASURE",
    "CONSENT_WITHDRAWAL": "WITHDRAW_CONSENT",
    "GRIEVANCE_REDRESSAL": "GRIEVANCE",
    "NOMINATION": "NOMINATION",
    "AMBIGUOUS": "ACCESS",
    "MULTI_INTENT": "ACCESS",
    "NON_PRIVACY_SUPPORT": "UNKNOWN",
}

LEGACY_INCIDENT_TYPE_MAP = {
    "UNAUTHORIZED_ACCESS": "UNAUTHORISED_ACCESS",
    "ACCIDENTAL_DISCLOSURE": "ACCIDENTAL_DISCLOSURE",
    "RANSOMWARE_MALWARE": "RANSOMWARE",
    "LOST_OR_STOLEN_DEVICE": "LOST_DEVICE",
    "VENDOR_THIRD_PARTY_BREACH": "DATA_LEAK",
    "PHYSICAL_BREACH": "UNAUTHORISED_ACCESS",
    "UNKNOWN": "UNKNOWN",
}

TYPE_MAP = {
    "text": "string",
    "varchar": "string",
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "bigint": "integer",
    "float": "float",
    "double": "float",
    "number": "float",
    "bool": "boolean",
    "boolean": "boolean",
    "date": "date",
    "datetime": "datetime",
    "timestamp": "datetime",
    "json": "json",
}


class AIClient:
    """
    AI module client.
    Supports 'mock' mode for deterministic testing without external SLM/Ollama services.
    Supports 'live' mode delegating to local Ollama inference via the ai module.
    """

    def __init__(
        self,
        mode: Optional[str] = None,
        config: Optional[AIConfig] = None,
        client: Optional[OllamaClient] = None,
    ):
        self.mode = (mode or settings.ai_mode).lower().strip()
        if config is not None:
            self.config = config
        else:
            base_url = getattr(settings, "ai_live_url", "http://localhost:11434")
            self.config = AIConfig(
                ollama_base_url=base_url,
                mock_mode=(self.mode == "mock"),
            )
        self.ollama_client = client or OllamaClient(config=self.config)

    def invoke(self, request_envelope: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processes an AI contract request envelope.
        Logs ONLY task and version — NEVER logs the payload content.
        """
        task = request_envelope.get("task", "")
        version = request_envelope.get("version") or request_envelope.get("schema_version", "1.0")
        payload = request_envelope.get("payload")
        request_id = request_envelope.get("request_id") or f"req_{uuid.uuid4().hex[:12]}"

        # Safe logging: task, version, and mode only — NEVER logs payload content or prompt
        logger.info("Executing AI task '%s' (version %s, mode %s)", task, version, self.mode)

        if self.mode == "mock":
            if task == "classify_columns":
                return self._mock_classify_columns(task, str(version), payload or {})
            elif task == "contextual_privacy_findings":
                return self._mock_contextual_privacy_findings(task, str(version), payload or {})
            elif task == "classify_privacy_request":
                return self._mock_classify_privacy_request(task, str(version), payload or {})
            elif task == "extract_breach_details":
                return self._mock_extract_breach_details(task, str(version), payload or {})
            else:
                return {
                    "task": task,
                    "version": str(version),
                    "status": "error",
                    "needs_human_review": True,
                    "result": None,
                    "warnings": [],
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": f"Unknown task '{task}'",
                    },
                }

        # Live mode: delegate to real Ollama client / task adapters
        if self.mode == "live":
            if task == "classify_columns":
                return self._live_classify_columns(task, str(version), request_envelope, str(request_id))
            elif task == "contextual_privacy_findings":
                return self._live_contextual_privacy_findings(task, str(version), request_envelope, str(request_id))
            elif task == "classify_privacy_request":
                return self._live_classify_privacy_request(task, str(version), request_envelope, str(request_id))
            elif task == "extract_breach_details":
                return self._live_extract_breach_details(task, str(version), request_envelope, str(request_id))
            else:
                return {
                    "task": task,
                    "version": str(version),
                    "status": "error",
                    "needs_human_review": True,
                    "result": None,
                    "warnings": [],
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": f"Unknown task '{task}'",
                    },
                }

        return {
            "task": task,
            "version": str(version),
            "status": "error",
            "needs_human_review": True,
            "result": None,
            "warnings": [],
            "error": {
                "code": "INVALID_INPUT",
                "message": f"Unknown AI mode '{self.mode}'",
            },
        }

    # -------------------------------------------------------------------------
    # Live handlers delegating to the Ollama adapters in ai/
    # -------------------------------------------------------------------------

    def _live_classify_columns(
        self, task: str, version: str, request_envelope: Dict[str, Any], request_id: str
    ) -> Dict[str, Any]:
        payload = request_envelope.get("payload")
        if payload is not None:
            dataset_context = {
                "dataset_id": str(payload.get("dataset_id") or "dataset_01"),
                "dataset_name": str(payload.get("dataset_name") or payload.get("dataset_id") or "dataset.csv"),
                "business_domain": str(payload.get("business_domain") or "general"),
            }
            columns: List[Dict[str, Any]] = []
            for c in payload.get("columns", []):
                col_name = str(c.get("name") or c.get("column_name") or "")
                raw_type = str(c.get("inferred_type") or c.get("inferred_data_type") or "string").lower()
                inferred_type = TYPE_MAP.get(raw_type, "string")
                null_ratio = float(c.get("null_ratio", 0.0))
                signals = c.get("deterministic_signals") or []
                if not signals:
                    signals = ["NONE"]
                samples = c.get("masked_samples") or c.get("sample_values") or []
                columns.append({
                    "column_name": col_name,
                    "inferred_data_type": inferred_type,
                    "null_ratio": null_ratio,
                    "deterministic_signals": signals,
                    "masked_samples": [str(s) for s in samples[:5]],
                })
            req_data: Dict[str, Any] = {
                "schema_version": "1.0",
                "request_id": request_id,
                "task": "classify_columns",
                "dataset_context": dataset_context,
                "columns": columns,
                "language": payload.get("language", "en"),
            }
        else:
            req_data = dict(request_envelope)
            if "request_id" not in req_data:
                req_data["request_id"] = request_id
            if "schema_version" not in req_data:
                req_data["schema_version"] = "1.0"

        try:
            resp_obj = classify_columns(req_data, config=self.config, client=self.ollama_client)
            resp_dict = resp_obj.model_dump()
        except Exception as exc:
            logger.warning("Live classify_columns failed: %s", type(exc).__name__)
            return {
                "schema_version": "1.0",
                "version": version,
                "request_id": request_id,
                "task": task,
                "status": "error",
                "needs_human_review": True,
                "review_reasons": [f"AI inference failed: {type(exc).__name__}"],
                "result": None,
                "results": [],
                "warnings": [f"AI inference failed: {type(exc).__name__}"],
                "error": {
                    "code": "MODEL_UNAVAILABLE" if isinstance(exc, (urllib.error.URLError, ConnectionError, OSError)) else "INTERNAL_AI_ERROR",
                    "message": "AI inference service encountered an error.",
                    "retryable": True,
                    "details": {"exception": type(exc).__name__},
                },
            }

        raw_results = resp_dict.get("results") or []
        classifications: List[Dict[str, Any]] = []
        for r in raw_results:
            cat = r.get("data_category", "UNKNOWN_AMBIGUOUS")
            tier = r.get("sensitivity_tier", "UNKNOWN")
            legacy_cat = LEGACY_CATEGORY_MAP.get(cat, "UNCERTAIN")
            legacy_sens = LEGACY_SENSITIVITY_MAP.get(tier, "PERSONAL_DATA")
            explanation = str(r.get("explanation") or "")[:200]

            classifications.append({
                "column_name": r.get("column_name"),
                "category": legacy_cat,
                "data_category": cat,
                "sensitivity": legacy_sens,
                "sensitivity_tier": tier,
                "specific_identifier_type": r.get("specific_identifier_type"),
                "confidence": round(float(r.get("confidence", 0.8)), 2),
                "explanation": explanation,
                "dpdp_basis": r.get("dpdp_basis") or "Section 2(t)",
                "needs_human_review": bool(r.get("needs_human_review", False)),
                "review_reasons": r.get("review_reasons") or [],
            })

        return {
            "schema_version": resp_dict.get("schema_version", "1.0"),
            "version": version,
            "request_id": resp_dict.get("request_id", request_id),
            "task": task,
            "status": resp_dict.get("status", "ok"),
            "needs_human_review": resp_dict.get("needs_human_review", False),
            "review_reasons": resp_dict.get("review_reasons") or [],
            "results": raw_results,
            "result": {
                "classifications": classifications,
                "results": raw_results,
            },
            "warnings": resp_dict.get("review_reasons") or [],
            "error": resp_dict.get("error"),
        }

    def _live_contextual_privacy_findings(
        self, task: str, version: str, request_envelope: Dict[str, Any], request_id: str
    ) -> Dict[str, Any]:
        payload = request_envelope.get("payload")
        if payload is not None:
            dataset_metadata = {
                "dataset_id": str(payload.get("activity_id") or payload.get("dataset_id") or "ds_act"),
                "dataset_name": str(payload.get("activity_name") or payload.get("dataset_name") or "Activity Dataset"),
                "business_purpose": str(payload.get("purpose") or payload.get("business_purpose") or "Business operations"),
                "stated_retention_days": payload.get("retention_days"),
                "has_consent_notice_linked": bool(payload.get("consent_collected", True)),
                "access_scope": payload.get("access_scope", "ROLE_RESTRICTED"),
                "third_party_sharing": bool(payload.get("cross_border", False) or payload.get("third_party_sharing", False)),
            }
            classified_columns: List[Dict[str, Any]] = []
            if "classified_columns" in payload:
                classified_columns = payload["classified_columns"]
            elif "data_categories" in payload:
                for i, cat in enumerate(payload["data_categories"]):
                    c_up = str(cat).upper()
                    if c_up == "CONTACT":
                        dc, spec, tier = "CONTACT_INFO", "EMAIL_ADDRESS", "GENERAL_PERSONAL"
                    elif c_up == "IDENTITY":
                        dc, spec, tier = "IDENTITY_DEMOGRAPHIC", "PERSON_NAME", "GENERAL_PERSONAL"
                    elif c_up == "GOVERNMENT_ID":
                        dc, spec, tier = "GOVERNMENT_ID", "PAN", "CRITICAL_PERSONAL"
                    elif c_up == "FINANCIAL":
                        dc, spec, tier = "FINANCIAL_DATA", "BANK_ACCOUNT", "SENSITIVE_PERSONAL"
                    elif c_up == "HEALTH":
                        dc, spec, tier = "HEALTH_MEDICAL", "MEDICAL_RECORD", "CRITICAL_PERSONAL"
                    elif c_up == "BIOMETRIC":
                        dc, spec, tier = "BIOMETRIC_GENETIC", "OTHER_PERSONAL", "CRITICAL_PERSONAL"
                    else:
                        dc, spec, tier = "BUSINESS_NON_PERSONAL", "NON_PERSONAL", "NON_PERSONAL"
                    classified_columns.append({
                        "column_name": f"col_{i}_{c_up.lower()}",
                        "data_category": dc,
                        "specific_identifier_type": spec,
                        "sensitivity_tier": tier,
                    })
            if not classified_columns:
                classified_columns = [{
                    "column_name": "record_id",
                    "data_category": "IDENTITY_DEMOGRAPHIC",
                    "specific_identifier_type": "PERSON_NAME",
                    "sensitivity_tier": "GENERAL_PERSONAL",
                }]

            req_data: Dict[str, Any] = {
                "schema_version": "1.0",
                "request_id": request_id,
                "task": "contextual_privacy_findings",
                "dataset_metadata": dataset_metadata,
                "classified_columns": classified_columns,
                "version_diff_summary": payload.get("version_diff_summary"),
                "language": payload.get("language", "en"),
            }
        else:
            req_data = dict(request_envelope)
            if "request_id" not in req_data:
                req_data["request_id"] = request_id
            if "schema_version" not in req_data:
                req_data["schema_version"] = "1.0"

        try:
            resp_obj = contextual_privacy_findings(req_data, config=self.config, client=self.ollama_client)
            resp_dict = resp_obj.model_dump()
        except Exception as exc:
            logger.warning("Live contextual_privacy_findings failed: %s", type(exc).__name__)
            return {
                "schema_version": "1.0",
                "version": version,
                "request_id": request_id,
                "task": task,
                "status": "error",
                "needs_human_review": True,
                "review_reasons": [f"AI inference failed: {type(exc).__name__}"],
                "result": None,
                "findings": [],
                "warnings": [f"AI inference failed: {type(exc).__name__}"],
                "error": {
                    "code": "MODEL_UNAVAILABLE" if isinstance(exc, (urllib.error.URLError, ConnectionError, OSError)) else "INTERNAL_AI_ERROR",
                    "message": "AI inference service encountered an error.",
                    "retryable": True,
                    "details": {"exception": type(exc).__name__},
                },
            }

        findings_list: List[Dict[str, Any]] = []
        raw_findings = resp_dict.get("findings") or []
        for i, f in enumerate(raw_findings):
            ft = f.get("finding_type", "OTHER")
            cat = LEGACY_FINDING_CATEGORY_MAP.get(ft, "OTHER")
            findings_list.append({
                "finding_id": f"F-{i+1:03d}",
                "title": ft.replace("_", " ").title(),
                "description": f.get("explanation", ""),
                "explanation": f.get("explanation", ""),
                "severity": f.get("severity", "MEDIUM"),
                "category": cat,
                "finding_type": ft,
                "recommendation": f.get("recommended_remediation", ""),
                "dpdp_reference": f.get("dpdp_reference", "DPDP Act, 2023"),
                "affected_columns": f.get("affected_columns", []),
            })

        summary = (
            f"Review identified {len(findings_list)} privacy issue(s). "
            + ("High-risk issues require immediate business review." if resp_dict.get("needs_human_review") else "Overall posture is acceptable.")
        )

        return {
            "schema_version": resp_dict.get("schema_version", "1.0"),
            "version": version,
            "request_id": resp_dict.get("request_id", request_id),
            "task": task,
            "status": resp_dict.get("status", "ok"),
            "overall_risk_level": resp_dict.get("overall_risk_level", "LOW"),
            "confidence": resp_dict.get("confidence", 0.0),
            "needs_human_review": resp_dict.get("needs_human_review", False),
            "review_reasons": resp_dict.get("review_reasons") or [],
            "findings": raw_findings,
            "result": {
                "findings": findings_list,
                "summary": summary,
                "overall_risk_level": resp_dict.get("overall_risk_level", "LOW"),
            },
            "warnings": resp_dict.get("review_reasons") or [],
            "error": resp_dict.get("error"),
        }

    def _live_classify_privacy_request(
        self, task: str, version: str, request_envelope: Dict[str, Any], request_id: str
    ) -> Dict[str, Any]:
        payload = request_envelope.get("payload")
        if payload is not None:
            raw_channel = str(payload.get("submission_channel", "WEBFORM")).upper().replace("-", "_").replace(" ", "_")
            channel_map = {
                "WEBFORM": "WEBFORM",
                "WEB_FORM": "WEBFORM",
                "EMAIL": "EMAIL",
                "WHATSAPP": "WHATSAPP_SUPPORT",
                "WHATSAPP_SUPPORT": "WHATSAPP_SUPPORT",
                "IN_PERSON": "IN_PERSON",
                "GRIEVANCE_PORTAL": "GRIEVANCE_PORTAL",
                "POSTAL": "OTHER",
                "WRITTEN_POSTAL": "OTHER",
                "OTHER": "OTHER",
            }
            channel = channel_map.get(raw_channel, "WEBFORM")
            case_id = str(payload.get("request_id") or payload.get("case_id") or "req_001")
            request_text = str(payload.get("raw_text") or payload.get("request_text") or "")
            req_data: Dict[str, Any] = {
                "schema_version": "1.0",
                "request_id": request_id,
                "task": "classify_privacy_request",
                "case_id": case_id,
                "channel": channel,
                "received_at": payload.get("received_at") or datetime.now(timezone.utc).isoformat(),
                "requester_role_hint": payload.get("requester_role_hint", "CUSTOMER"),
                "identity_verified_by_backend": bool(payload.get("identity_verified", False)),
                "request_text": request_text,
                "language": payload.get("language", "en"),
            }
        else:
            req_data = dict(request_envelope)
            if "request_id" not in req_data:
                req_data["request_id"] = request_id
            if "schema_version" not in req_data:
                req_data["schema_version"] = "1.0"

        try:
            resp_obj = classify_privacy_request(req_data, config=self.config, client=self.ollama_client)
            resp_dict = resp_obj.model_dump()
        except Exception as exc:
            logger.warning("Live classify_privacy_request failed: %s", type(exc).__name__)
            return {
                "schema_version": "1.0",
                "version": version,
                "request_id": request_id,
                "task": task,
                "status": "error",
                "needs_human_review": True,
                "review_reasons": [f"AI inference failed: {type(exc).__name__}"],
                "result": None,
                "warnings": [f"AI inference failed: {type(exc).__name__}"],
                "error": {
                    "code": "MODEL_UNAVAILABLE" if isinstance(exc, (urllib.error.URLError, ConnectionError, OSError)) else "INTERNAL_AI_ERROR",
                    "message": "AI inference service encountered an error.",
                    "retryable": True,
                    "details": {"exception": type(exc).__name__},
                },
            }

        sub_types = resp_dict.get("detected_sub_types") or []
        primary = resp_dict.get("primary_request_type", "AMBIGUOUS")
        req_types_set = set()
        for st in sub_types:
            mapped = LEGACY_RIGHT_TYPE_MAP.get(st)
            if mapped:
                req_types_set.add(mapped)
        if primary in LEGACY_RIGHT_TYPE_MAP:
            mapped_primary = LEGACY_RIGHT_TYPE_MAP[primary]
            if mapped_primary != "UNKNOWN":
                req_types_set.add(mapped_primary)
        if not req_types_set:
            req_types_set.add("ACCESS")

        req_types = sorted(list(req_types_set))
        raw_urgency = resp_dict.get("urgency", "NORMAL")
        urgency_map = {"LOW": "LOW", "NORMAL": "MEDIUM", "HIGH": "HIGH", "CRITICAL": "HIGH"}
        mapped_urgency = urgency_map.get(raw_urgency, "MEDIUM")

        is_composite = len(req_types) > 1 or primary == "MULTI_INTENT"

        return {
            "schema_version": resp_dict.get("schema_version", "1.0"),
            "version": version,
            "request_id": resp_dict.get("request_id", request_id),
            "task": task,
            "status": resp_dict.get("status", "ok"),
            "case_id": resp_dict.get("case_id"),
            "needs_human_review": resp_dict.get("needs_human_review", True),
            "review_reasons": resp_dict.get("review_reasons") or [],
            "result": {
                "request_types": req_types,
                "is_composite": is_composite,
                "confidence": round(float(resp_dict.get("confidence", 0.9)), 2),
                "urgency": mapped_urgency,
                "subject_reference": "customer",
                "data_scope_hint": "Records matching data principal identification",
                "suggested_response_outline": resp_dict.get("draft_response_for_staff_review") or "",
                "draft_response_for_staff_review": resp_dict.get("draft_response_for_staff_review") or "",
                "explanation": resp_dict.get("explanation") or "",
                "ambiguities": resp_dict.get("review_reasons") or [],
            },
            "warnings": resp_dict.get("review_reasons") or [],
            "error": resp_dict.get("error"),
        }

    def _live_extract_breach_details(
        self, task: str, version: str, request_envelope: Dict[str, Any], request_id: str
    ) -> Dict[str, Any]:
        payload = request_envelope.get("payload")
        if payload is not None:
            incident_id = str(payload.get("incident_ref") or payload.get("incident_id") or "inc_001")
            narrative = str(payload.get("report_text") or payload.get("incident_narrative") or "")
            req_data: Dict[str, Any] = {
                "schema_version": "1.0",
                "request_id": request_id,
                "task": "extract_breach_details",
                "incident_id": incident_id,
                "reported_at": payload.get("report_timestamp") or datetime.now(timezone.utc).isoformat(),
                "reporter_role": str(payload.get("reporter_role") or "staff"),
                "incident_narrative": narrative,
                "language": payload.get("language", "en"),
            }
        else:
            req_data = dict(request_envelope)
            if "request_id" not in req_data:
                req_data["request_id"] = request_id
            if "schema_version" not in req_data:
                req_data["schema_version"] = "1.0"

        try:
            resp_obj = extract_breach_details(req_data, config=self.config, client=self.ollama_client)
            resp_dict = resp_obj.model_dump()
        except Exception as exc:
            logger.warning("Live extract_breach_details failed: %s", type(exc).__name__)
            return {
                "schema_version": "1.0",
                "version": version,
                "request_id": request_id,
                "task": task,
                "status": "error",
                "needs_human_review": True,
                "review_reasons": [f"AI inference failed: {type(exc).__name__}"],
                "result": None,
                "warnings": [f"AI inference failed: {type(exc).__name__}"],
                "error": {
                    "code": "MODEL_UNAVAILABLE" if isinstance(exc, (urllib.error.URLError, ConnectionError, OSError)) else "INTERNAL_AI_ERROR",
                    "message": "AI inference service encountered an error.",
                    "retryable": True,
                    "details": {"exception": type(exc).__name__},
                },
            }

        ext = resp_dict.get("extracted_details") or {}
        assessment = resp_dict.get("assessment") or {}
        drafts = resp_dict.get("draft_notifications") or {}

        b_type = ext.get("breach_type", "UNAUTHORIZED_ACCESS")
        legacy_type = LEGACY_INCIDENT_TYPE_MAP.get(b_type, "UNAUTHORISED_ACCESS")

        affected_cats = [
            LEGACY_CATEGORY_MAP.get(c, "IDENTITY")
            for c in ext.get("affected_data_categories", [])
        ]
        if not affected_cats:
            affected_cats = ["IDENTITY", "CONTACT"]

        est_count = ext.get("affected_data_principals_estimate")
        count_conf = "ESTIMATE" if est_count is not None else "UNKNOWN"

        notif_req = bool(
            assessment.get("dpb_notification_likely_required")
            or assessment.get("cert_in_notification_likely_required")
        )

        return {
            "schema_version": resp_dict.get("schema_version", "1.0"),
            "version": version,
            "request_id": resp_dict.get("request_id", request_id),
            "task": task,
            "status": resp_dict.get("status", "ok"),
            "incident_id": resp_dict.get("incident_id"),
            "needs_human_review": True,  # Mandatory per contract
            "review_reasons": resp_dict.get("review_reasons") or [
                "All breach incident assessments require mandatory human review."
            ],
            "extracted_details": ext,
            "assessment": assessment,
            "draft_notifications": drafts,
            "result": {
                "incident_type": legacy_type,
                "discovery_datetime_hint": ext.get("discovery_time"),
                "affected_data_categories": affected_cats,
                "estimated_affected_count": est_count,
                "count_confidence": count_conf,
                "potential_harm": [
                    "IDENTITY_THEFT",
                    "LOSS_OF_CONFIDENTIALITY",
                    "REPUTATIONAL_DAMAGE",
                ],
                "containment_steps_mentioned": ext.get("containment_actions_taken") or ["Investigation initiated."],
                "notification_likely_required": notif_req,
                "notification_reasoning": assessment.get("explanation") or "Incident assessment evaluated.",
                "draft_summary": drafts.get("authority_summary_draft") or f"Incident of type {legacy_type} reported.",
                "open_questions": ext.get("missing_critical_facts") or ["Verify exposure timeframe."],
                "extracted_details": ext,
                "assessment": assessment,
            },
            "warnings": resp_dict.get("review_reasons") or [],
            "error": resp_dict.get("error"),
        }

    # -------------------------------------------------------------------------
    # Deterministic Mock Handlers (Legacy backward compatibility)
    # -------------------------------------------------------------------------

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
