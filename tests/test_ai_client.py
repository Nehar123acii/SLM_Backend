import pytest
from backend.ai_client.mock_client import AIClient

PERMITTED_CATEGORIES = {
    "IDENTITY", "GOVERNMENT_ID", "CONTACT", "FINANCIAL", "HEALTH",
    "BIOMETRIC", "LOCATION", "BEHAVIOURAL", "EMPLOYMENT", "NON_PERSONAL", "UNCERTAIN"
}
PERMITTED_SENSITIVITIES = {
    "SENSITIVE_PERSONAL_DATA", "PERSONAL_DATA", "NON_PERSONAL_DATA"
}
PERMITTED_SEVERITIES = {
    "INFORMATIONAL", "LOW", "MEDIUM", "HIGH", "CRITICAL"
}
PERMITTED_FINDING_CATEGORIES = {
    "CONSENT", "DATA_MINIMISATION", "RETENTION", "CROSS_BORDER_TRANSFER",
    "PURPOSE_LIMITATION", "SECURITY", "RIGHTS_FACILITATION", "TRANSPARENCY", "OTHER"
}
PERMITTED_REQUEST_TYPES = {
    "ACCESS", "CORRECTION", "ERASURE", "NOMINATION", "WITHDRAW_CONSENT", "GRIEVANCE", "UNKNOWN"
}
PERMITTED_URGENCIES = {"LOW", "MEDIUM", "HIGH"}
PERMITTED_INCIDENT_TYPES = {
    "UNAUTHORISED_ACCESS", "DATA_LEAK", "RANSOMWARE", "INSIDER_THREAT",
    "LOST_DEVICE", "PHISHING", "ACCIDENTAL_DISCLOSURE", "SYSTEM_MISCONFIGURATION", "UNKNOWN"
}
PERMITTED_COUNT_CONFIDENCE = {"EXACT", "ESTIMATE", "UNKNOWN"}
PERMITTED_POTENTIAL_HARM = {
    "IDENTITY_THEFT", "FINANCIAL_LOSS", "REPUTATIONAL_DAMAGE", "DISCRIMINATION",
    "PHYSICAL_HARM", "EMOTIONAL_DISTRESS", "LOSS_OF_CONFIDENTIALITY", "UNKNOWN"
}


def assert_common_envelope(resp: dict, expected_task: str):
    assert "status" in resp
    assert "needs_human_review" in resp
    assert "result" in resp
    assert "warnings" in resp
    assert "error" in resp
    assert resp["task"] == expected_task
    assert resp["status"] == "ok"
    assert resp["error"] is None
    assert isinstance(resp["warnings"], list)
    assert isinstance(resp["needs_human_review"], bool)


def test_classify_columns_mock():
    client = AIClient(mode="mock")
    req = {
        "task": "classify_columns",
        "version": "1",
        "payload": {
            "dataset_id": "ds_test_001",
            "columns": [
                {
                    "name": "customer_name",
                    "inferred_type": "TEXT",
                    "sample_values": ["Aarav Sharma", "Priya Patel"],
                },
                {
                    "name": "pan_number",
                    "inferred_type": "TEXT",
                    "sample_values": ["ABCDE1234F", "BCDEF2345G"],
                },
                {
                    "name": "purchase_amount_inr",
                    "inferred_type": "FLOAT",
                    "sample_values": ["1299.00", "499.50"],
                },
            ],
        },
    }
    resp = client.invoke(req)
    assert_common_envelope(resp, "classify_columns")
    assert resp["needs_human_review"] is True  # Because pan_number is present

    result = resp["result"]
    assert "classifications" in result
    for c in result["classifications"]:
        assert c["category"] in PERMITTED_CATEGORIES
        assert c["sensitivity"] in PERMITTED_SENSITIVITIES
        assert 0.0 <= c["confidence"] <= 1.0
        assert len(c["explanation"]) <= 200


def test_contextual_privacy_findings_mock():
    client = AIClient(mode="mock")
    req = {
        "task": "contextual_privacy_findings",
        "version": "1",
        "payload": {
            "activity_id": "act_test_001",
            "activity_name": "Customer newsletter",
            "purpose": "Promotional emails",
            "data_categories": ["CONTACT", "IDENTITY"],
            "cross_border": True,
            "consent_collected": False,
        },
    }
    resp = client.invoke(req)
    assert_common_envelope(resp, "contextual_privacy_findings")
    assert resp["needs_human_review"] is True  # cross_border=True & consent_collected=False

    result = resp["result"]
    assert "findings" in result
    assert "summary" in result
    for f in result["findings"]:
        assert f["severity"] in PERMITTED_SEVERITIES
        assert f["category"] in PERMITTED_FINDING_CATEGORIES


def test_classify_privacy_request_mock():
    client = AIClient(mode="mock")
    req = {
        "task": "classify_privacy_request",
        "version": "1",
        "payload": {
            "request_id": "req_test_001",
            "raw_text": "I want a copy of my records and update my phone number immediately or I will take legal action.",
            "submission_channel": "web_form",
        },
    }
    resp = client.invoke(req)
    assert_common_envelope(resp, "classify_privacy_request")
    assert resp["needs_human_review"] is True  # Safe default for mock

    result = resp["result"]
    assert isinstance(result["request_types"], list)
    for rt in result["request_types"]:
        assert rt in PERMITTED_REQUEST_TYPES
    assert result["urgency"] in PERMITTED_URGENCIES
    assert result["urgency"] == "HIGH"  # legal action
    assert result["is_composite"] is True  # ACCESS + CORRECTION


def test_extract_breach_details_mock():
    client = AIClient(mode="mock")
    req = {
        "task": "extract_breach_details",
        "version": "1",
        "payload": {
            "incident_ref": "inc_test_001",
            "report_text": "An accidental public bucket exposure occurred with 500 customers exposed.",
            "reporter_role": "security_lead",
        },
    }
    resp = client.invoke(req)
    assert_common_envelope(resp, "extract_breach_details")
    # Contract requirement: needs_human_review is always True for breach extraction
    assert resp["needs_human_review"] is True

    result = resp["result"]
    assert result["incident_type"] in PERMITTED_INCIDENT_TYPES
    assert result["count_confidence"] in PERMITTED_COUNT_CONFIDENCE
    for harm in result["potential_harm"]:
        assert harm in PERMITTED_POTENTIAL_HARM
    for cat in result["affected_data_categories"]:
        assert cat in PERMITTED_CATEGORIES


def test_live_mode_raises_not_implemented():
    client = AIClient(mode="live")
    with pytest.raises(NotImplementedError):
        client.invoke({"task": "classify_columns", "version": "1", "payload": {}})
