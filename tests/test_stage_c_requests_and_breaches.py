"""Stage C tests: classify_privacy_request and extract_breach_details."""

from __future__ import annotations

import json
from ai.breach_extractor import extract_breach_details
from ai.client import OllamaClient
from ai.config import AIConfig
from ai.requests_classifier import classify_privacy_request


def test_classify_privacy_request_contract_example_mock() -> None:
    """Verify the exact synthetic example from contracts/AI_BACKEND_CONTRACT.md in mock mode."""
    payload = {
        "schema_version": "1.0",
        "request_id": "req_dsr_9003",
        "task": "classify_privacy_request",
        "case_id": "case_2026_0041",
        "channel": "EMAIL",
        "received_at": "2026-10-24T14:20:00+05:30",
        "requester_role_hint": "CUSTOMER",
        "identity_verified_by_backend": False,
        "request_text": (
            "Hello, I closed my membership with your store last month. Under the DPDP Act, "
            "please tell me which third-party delivery or marketing companies you shared my "
            "phone number and address with, and delete all my personal records from your "
            "system immediately."
        ),
    }

    resp = classify_privacy_request(payload, config=AIConfig(mock_mode=True))
    assert resp.status == "ok"
    assert resp.case_id == "case_2026_0041"
    assert resp.primary_request_type == "MULTI_INTENT"
    assert set(resp.detected_sub_types) == {"THIRD_PARTY_SHARING_LIST", "ERASURE"}
    assert resp.urgency == "HIGH"
    assert resp.verification_status_advice == "REQUIRES_STANDARD_VERIFICATION"
    assert "CONTACT_INFO" in resp.target_data_categories_mentioned
    assert resp.legal_retention_check_required is True
    assert resp.needs_human_review is True


def test_classify_privacy_request_guardian_and_multilingual() -> None:
    """Verify guardian verification advice and Hindi/Kannada explanation templates."""
    payload = {
        "schema_version": "1.0",
        "request_id": "req_dsr_9004",
        "task": "classify_privacy_request",
        "case_id": "case_2026_0042",
        "channel": "WEBFORM",
        "received_at": "2026-10-24T15:00:00+05:30",
        "requester_role_hint": "PARENT_GUARDIAN",
        "identity_verified_by_backend": False,
        "request_text": "Please correct my child's date of birth and address in your school clinic records.",
        "language": "hi",
    }

    hi_resp = classify_privacy_request(payload, config=AIConfig(mock_mode=True))
    assert hi_resp.primary_request_type == "CORRECTION_COMPLETION_UPDATING"
    assert hi_resp.verification_status_advice == "REQUIRES_GUARDIAN_OR_NOMINEE_PROOF"
    assert hi_resp.needs_human_review is True
    assert "DPDP" in hi_resp.explanation and "सत्यापन" in hi_resp.explanation

    kn_resp = classify_privacy_request(
        {**payload, "language": "kn"}, config=AIConfig(mock_mode=True)
    )
    assert "DPDP" in kn_resp.explanation and "ಪರಿಶೀಲನೆ" in kn_resp.explanation


def test_extract_breach_details_contract_example_mock() -> None:
    """Verify the exact synthetic breach example from contracts/AI_BACKEND_CONTRACT.md in mock mode."""
    payload = {
        "schema_version": "1.0",
        "request_id": "req_inc_9004",
        "task": "extract_breach_details",
        "incident_id": "inc_2026_0009",
        "reported_at": "2026-10-24T18:00:00+05:30",
        "reporter_role": "STORE_MANAGER",
        "incident_narrative": (
            "At around 11:30 AM today (24 Oct), our billing operator accidentally emailed "
            "the October monthly GST & customer KYC spreadsheet (oct_kyc_billing.xlsx) to "
            "an external vendor distribution list instead of our internal accountant. "
            "The file had roughly 450 customer rows containing full names, phone numbers, "
            "and PAN numbers. The file was not password protected. We asked the vendor list "
            "recipients to delete the email at 2:00 PM, but we do not know if anyone "
            "downloaded or forwarded it."
        ),
    }

    resp = extract_breach_details(payload, config=AIConfig(mock_mode=True))
    assert resp.status == "ok"
    assert resp.incident_id == "inc_2026_0009"
    assert resp.needs_human_review is True
    assert resp.extracted_details is not None
    assert resp.extracted_details.breach_type == "ACCIDENTAL_DISCLOSURE"
    assert "oct_kyc_billing.xlsx" in resp.extracted_details.affected_systems
    assert set(resp.extracted_details.affected_data_categories) == {
        "IDENTITY_DEMOGRAPHIC",
        "CONTACT_INFO",
        "GOVERNMENT_ID",
    }
    assert resp.extracted_details.affected_data_principals_estimate == 450
    assert resp.assessment is not None
    assert resp.assessment.severity == "HIGH"
    assert resp.assessment.dpb_notification_likely_required is True
    assert resp.draft_notifications is not None
    assert "inc_2026_0009" in resp.draft_notifications.authority_summary_draft


def test_extract_breach_details_blocks_sql_output_and_enforces_human_review() -> None:
    """Ensure model output containing SQL/system commands is blocked by safety filter."""

    def malicious_slm_transport(url: str, payload: dict, timeout: float) -> str:
        return json.dumps(
            {
                "response": '{"extracted_details": {"breach_type": "UNKNOWN"}, "sql": "DROP TABLE incidents;"}'
            }
        )

    cfg = AIConfig(mock_mode=False, max_retries=1, fallback_on_model_error=True)
    client = OllamaClient(config=cfg, transport=malicious_slm_transport)

    payload = {
        "schema_version": "1.0",
        "request_id": "req_inc_sql",
        "task": "extract_breach_details",
        "incident_id": "inc_2026_0010",
        "reported_at": "2026-10-24T19:00:00+05:30",
        "reporter_role": "IT_ADMIN",
        "incident_narrative": "Unauthorised login detected on billing portal affecting 25 customer records.",
    }

    resp = extract_breach_details(payload, config=cfg, client=client)
    assert resp.status == "error"
    assert resp.needs_human_review is True
    assert resp.error is not None
    assert resp.error.code == "SAFETY_POLICY_BLOCKED"
