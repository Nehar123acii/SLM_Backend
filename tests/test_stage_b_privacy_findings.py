"""Stage B tests: contextual_privacy_findings."""

from __future__ import annotations

import json
from ai.client import OllamaClient
from ai.config import AIConfig
from ai.findings import contextual_privacy_findings


def test_contextual_privacy_findings_contract_example_mock() -> None:
    """Verify the exact synthetic example from contracts/AI_BACKEND_CONTRACT.md in mock mode."""
    payload = {
        "schema_version": "1.0",
        "request_id": "req_find_9002",
        "task": "contextual_privacy_findings",
        "dataset_metadata": {
            "dataset_id": "ds_510",
            "dataset_name": "festive_coupon_signups.csv",
            "business_purpose": "promotional_discount_newsletter",
            "stated_retention_days": None,
            "has_consent_notice_linked": False,
            "access_scope": "ALL_STAFF",
            "third_party_sharing": True,
        },
        "classified_columns": [
            {
                "column_name": "customer_name",
                "data_category": "IDENTITY_DEMOGRAPHIC",
                "specific_identifier_type": "PERSON_NAME",
                "sensitivity_tier": "GENERAL_PERSONAL",
            },
            {
                "column_name": "mobile_no",
                "data_category": "CONTACT_INFO",
                "specific_identifier_type": "PHONE_NUMBER",
                "sensitivity_tier": "GENERAL_PERSONAL",
            },
            {
                "column_name": "aadhaar_number",
                "data_category": "GOVERNMENT_ID",
                "specific_identifier_type": "AADHAAR",
                "sensitivity_tier": "CRITICAL_PERSONAL",
            },
        ],
        "version_diff_summary": {
            "added_columns": ["aadhaar_number"],
            "removed_columns": [],
            "tier_escalations": [],
        },
    }

    resp = contextual_privacy_findings(payload, config=AIConfig(mock_mode=True))
    assert resp.status == "ok"
    assert resp.overall_risk_level == "CRITICAL"
    assert resp.needs_human_review is True

    finding_types = {f.finding_type for f in resp.findings}
    assert "OVER_COLLECTION" in finding_types
    assert "EXCESSIVE_ACCESS" in finding_types
    assert "MISSING_CONSENT_BASIS" in finding_types
    assert "VERSION_DRIFT_ESCALATION" in finding_types


def test_contextual_privacy_findings_children_and_public_link_and_i18n() -> None:
    """Verify CHILDREN_DATA, PUBLIC_LINK, and Hindi/Kannada localized explanations."""
    payload = {
        "schema_version": "1.0",
        "request_id": "req_find_9003",
        "task": "contextual_privacy_findings",
        "dataset_metadata": {
            "dataset_id": "ds_511",
            "dataset_name": "summer_camp_students.csv",
            "business_purpose": "student_enrollment",
            "stated_retention_days": 90,
            "has_consent_notice_linked": True,
            "access_scope": "PUBLIC_LINK",
            "third_party_sharing": False,
        },
        "classified_columns": [
            {
                "column_name": "student_under_18_flag",
                "data_category": "CHILDREN_DATA",
                "specific_identifier_type": "MINOR_INDICATOR",
                "sensitivity_tier": "CRITICAL_PERSONAL",
            }
        ],
        "version_diff_summary": None,
        "language": "hi",
    }

    resp = contextual_privacy_findings(payload, config=AIConfig(mock_mode=True))
    assert resp.needs_human_review is True
    assert resp.overall_risk_level == "CRITICAL"
    types = {f.finding_type for f in resp.findings}
    assert "CHILDREN_DATA_SAFEGUARD_REQUIRED" in types
    assert "EXCESSIVE_ACCESS" in types
    assert any("DPDP" in f.explanation or "डेटा" in f.explanation for f in resp.findings)

    kn_resp = contextual_privacy_findings(
        {**payload, "language": "kn"}, config=AIConfig(mock_mode=True)
    )
    assert any("ಡೇಟಾ" in f.explanation for f in kn_resp.findings)


def test_contextual_privacy_findings_ollama_retry_and_fallback() -> None:
    """Verify bounded retry and fallback when SLM output is invalid."""
    calls = {"n": 0}

    def bad_json_transport(url: str, payload: dict, timeout: float) -> str:
        calls["n"] += 1
        return json.dumps({"response": '{"overall_risk_level": "INVALID_ENUM"}'})

    cfg = AIConfig(mock_mode=False, max_retries=1, fallback_on_model_error=True)
    client = OllamaClient(config=cfg, transport=bad_json_transport)

    payload = {
        "schema_version": "1.0",
        "request_id": "req_find_retry",
        "task": "contextual_privacy_findings",
        "dataset_metadata": {
            "dataset_id": "ds_1",
            "dataset_name": "staff.csv",
            "business_purpose": "payroll",
            "stated_retention_days": 365,
            "has_consent_notice_linked": True,
            "access_scope": "ROLE_RESTRICTED",
            "third_party_sharing": False,
        },
        "classified_columns": [
            {
                "column_name": "employee_name",
                "data_category": "IDENTITY_DEMOGRAPHIC",
                "specific_identifier_type": "PERSON_NAME",
                "sensitivity_tier": "GENERAL_PERSONAL",
            }
        ],
        "version_diff_summary": None,
    }

    resp = contextual_privacy_findings(payload, config=cfg, client=client)
    assert calls["n"] == 2
    assert resp.status == "ok"
    assert resp.needs_human_review is True
    assert any("MODEL_OUTPUT_INVALID" in r for r in resp.review_reasons)
