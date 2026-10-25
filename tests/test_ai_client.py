import json
import socket
import pytest
from backend.ai_client.mock_client import AIClient
from ai.config import AIConfig
from pydantic import ValidationError

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


def test_live_mode_delegates_to_ollama_client(monkeypatch):
    """
    Unit test proving that AI_MODE='live' delegates to the configured Ollama HTTP endpoint
    and parses the returned structured inference into the agreed response envelope.
    """
    calls = []

    class MockHTTPResponse:
        def __init__(self, data: str):
            self._data = data.encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(request, timeout=None):
        calls.append(request)
        model_output = {
            "results": [
                {
                    "column_name": "customer_name",
                    "contains_personal_data": True,
                    "data_category": "IDENTITY_DEMOGRAPHIC",
                    "specific_identifier_type": "PERSON_NAME",
                    "sensitivity_tier": "GENERAL_PERSONAL",
                    "confidence": 0.95,
                    "explanation": "Customer full name identifies a natural person.",
                    "needs_human_review": False,
                    "review_reasons": [],
                },
                {
                    "column_name": "pan_number",
                    "contains_personal_data": True,
                    "data_category": "GOVERNMENT_ID",
                    "specific_identifier_type": "PAN",
                    "sensitivity_tier": "CRITICAL_PERSONAL",
                    "confidence": 0.99,
                    "explanation": "Permanent Account Number (PAN).",
                    "needs_human_review": True,
                    "review_reasons": ["CRITICAL_PERSONAL tier identifier requires review"],
                },
            ]
        }
        ollama_envelope = {
            "model": "qwen2.5:3b",
            "response": json.dumps(model_output),
            "done": True,
        }
        return MockHTTPResponse(json.dumps(ollama_envelope))

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    client = AIClient(mode="live")
    req = {
        "task": "classify_columns",
        "version": "1",
        "payload": {
            "dataset_id": "ds_live_001",
            "columns": [
                {"name": "customer_name", "inferred_type": "TEXT", "sample_values": ["Aarav"]},
                {"name": "pan_number", "inferred_type": "TEXT", "sample_values": ["ABCDE1234F"]},
            ],
        },
    }
    resp = client.invoke(req)

    # Proves delegation to Ollama endpoint
    assert len(calls) == 1
    assert "api/generate" in calls[0].full_url
    req_body = json.loads(calls[0].data.decode("utf-8"))
    assert req_body["model"] == "qwen2.5:3b"
    assert req_body["format"] == "json"

    # Verify agreed response envelope
    assert_common_envelope(resp, "classify_columns")
    assert resp["needs_human_review"] is True  # Due to pan_number
    result = resp["result"]
    assert "classifications" in result
    assert len(result["classifications"]) == 2
    pan_col = [c for c in result["classifications"] if c["column_name"] == "pan_number"][0]
    assert pan_col["category"] == "GOVERNMENT_ID"
    assert pan_col["sensitivity"] == "SENSITIVE_PERSONAL_DATA"
    assert pan_col["needs_human_review"] is True


def test_live_mode_rejects_cloud_endpoints():
    """Ensure cloud / non-local endpoints are strictly rejected in live mode."""
    with pytest.raises(ValidationError, match="Cloud or non-local host"):
        AIConfig(ollama_base_url="https://api.openai.com/v1")

    with pytest.raises(ValidationError, match="Cloud or non-local host"):
        AIConfig(ollama_base_url="http://remote-server.com:11434")


def test_live_mode_offline_fallback():
    """
    When local Ollama is offline or unreachable, AIClient gracefully triggers safe
    fallback or structured error envelope with needs_human_review=True, never crashing.
    """
    # Connect to a closed local port
    cfg = AIConfig(ollama_base_url="http://127.0.0.1:11435", max_retries=0, timeout_seconds=1.0)
    client = AIClient(mode="live", config=cfg)
    req = {
        "task": "classify_columns",
        "version": "1",
        "payload": {
            "dataset_id": "ds_offline",
            "columns": [
                {"name": "phone_num", "inferred_type": "TEXT", "sample_values": ["9876543210"]},
            ],
        },
    }
    resp = client.invoke(req)
    assert resp["task"] == "classify_columns"
    assert resp["needs_human_review"] is True
    # Safe fallback should preserve usability while flagging human review
    assert resp["status"] in {"ok", "error"}


def test_live_mode_delegates_privacy_request(monkeypatch):
    """Prove that live mode for classify_privacy_request delegates to Ollama and parses output."""
    calls = []

    class MockHTTPResponse:
        def __init__(self, data: str):
            self._data = data.encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(request, timeout=None):
        calls.append(request)
        model_output = {
            "primary_request_type": "ACCESS_SUMMARY",
            "detected_sub_types": ["ACCESS_SUMMARY", "CORRECTION_COMPLETION_UPDATING"],
            "urgency": "HIGH",
            "verification_status_advice": "REQUIRES_STANDARD_VERIFICATION",
            "target_data_categories_mentioned": ["CONTACT_INFO", "IDENTITY_DEMOGRAPHIC"],
            "legal_retention_check_required": False,
            "explanation": "Principal requests copy of records and correction of mobile number.",
            "draft_response_for_staff_review": "We acknowledge receipt of your access and correction request.",
            "confidence": 0.93,
            "needs_human_review": True,
            "review_reasons": ["Composite request requires manual verification"],
        }
        ollama_envelope = {
            "model": "qwen2.5:3b",
            "response": json.dumps(model_output),
            "done": True,
        }
        return MockHTTPResponse(json.dumps(ollama_envelope))

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    client = AIClient(mode="live")
    req = {
        "task": "classify_privacy_request",
        "version": "1",
        "payload": {
            "request_id": "req_live_001",
            "raw_text": "I want a copy of my records and update my phone number immediately.",
            "submission_channel": "web_form",
        },
    }
    resp = client.invoke(req)

    assert len(calls) == 1
    assert "api/generate" in calls[0].full_url
    assert_common_envelope(resp, "classify_privacy_request")
    assert resp["needs_human_review"] is True
    res = resp["result"]
    assert "ACCESS" in res["request_types"]
    assert "CORRECTION" in res["request_types"]
    assert res["is_composite"] is True
    assert res["urgency"] == "HIGH"


def test_live_mode_delegates_breach_extraction(monkeypatch):
    """Prove that live mode for extract_breach_details delegates to Ollama and parses output."""
    calls = []

    class MockHTTPResponse:
        def __init__(self, data: str):
            self._data = data.encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(request, timeout=None):
        calls.append(request)
        model_output = {
            "extracted_details": {
                "breach_type": "ACCIDENTAL_DISCLOSURE",
                "estimated_occurrence_time": "2026-10-24T10:00:00Z",
                "discovery_time": "2026-10-24T12:00:00Z",
                "affected_systems": ["s3_backup_bucket"],
                "affected_data_categories": ["CONTACT_INFO", "IDENTITY_DEMOGRAPHIC"],
                "affected_data_principals_estimate": 450,
                "is_ongoing": False,
                "containment_actions_taken": ["Bucket ACL modified to private"],
                "missing_critical_facts": ["Exact IP access logs during exposure"],
            },
            "assessment": {
                "severity": "HIGH",
                "dpb_notification_likely_required": True,
                "cert_in_notification_likely_required": True,
                "explanation": "Exposure of 450 principals' contact data triggers Section 8(6) notification duty.",
                "recommended_next_steps": ["Notify Data Protection Board within 72 hours"],
            },
            "draft_notifications": {
                "authority_summary_draft": "Notice to Data Protection Board regarding accidental S3 bucket exposure.",
                "data_principal_notice_draft": "Notice to affected data principals regarding exposed contact information.",
            },
            "confidence": 0.88,
            "needs_human_review": True,
            "review_reasons": ["Mandatory human review for all breach assessments"],
        }
        ollama_envelope = {
            "model": "qwen2.5:3b",
            "response": json.dumps(model_output),
            "done": True,
        }
        return MockHTTPResponse(json.dumps(ollama_envelope))

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    client = AIClient(mode="live")
    req = {
        "task": "extract_breach_details",
        "version": "1",
        "payload": {
            "incident_ref": "inc_live_001",
            "report_text": "An accidental public bucket exposure occurred with 450 customers exposed.",
            "reporter_role": "security_lead",
        },
    }
    resp = client.invoke(req)

    assert len(calls) == 1
    assert_common_envelope(resp, "extract_breach_details")
    assert resp["needs_human_review"] is True
    res = resp["result"]
    assert res["incident_type"] == "ACCIDENTAL_DISCLOSURE"
    assert res["estimated_affected_count"] == 450
    assert res["notification_likely_required"] is True


def test_live_mode_delegates_contextual_findings(monkeypatch):
    """Prove that live mode for contextual_privacy_findings delegates to Ollama and parses output."""
    calls = []

    class MockHTTPResponse:
        def __init__(self, data: str):
            self._data = data.encode("utf-8")

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(request, timeout=None):
        calls.append(request)
        model_output = {
            "overall_risk_level": "HIGH",
            "confidence": 0.91,
            "needs_human_review": True,
            "review_reasons": ["Missing consent notice and cross-border transfer detected"],
            "findings": [
                {
                    "finding_type": "THIRD_PARTY_SHARING_RISK",
                    "severity": "HIGH",
                    "dpdp_reference": "Section 16, DPDP Act 2023",
                    "affected_columns": ["col_0_contact"],
                    "explanation": "Cross border data transfer without explicit statutory safeguard.",
                    "recommended_remediation": "Verify approved destination whitelist.",
                }
            ],
        }
        ollama_envelope = {
            "model": "qwen2.5:3b",
            "response": json.dumps(model_output),
            "done": True,
        }
        return MockHTTPResponse(json.dumps(ollama_envelope))

    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    client = AIClient(mode="live")
    req = {
        "task": "contextual_privacy_findings",
        "version": "1",
        "payload": {
            "activity_id": "act_live_001",
            "activity_name": "Customer newsletter",
            "purpose": "Promotional emails",
            "data_categories": ["CONTACT"],
            "cross_border": True,
            "consent_collected": False,
        },
    }
    resp = client.invoke(req)

    assert len(calls) == 1
    assert_common_envelope(resp, "contextual_privacy_findings")
    assert resp["needs_human_review"] is True
    res = resp["result"]
    assert len(res["findings"]) == 1
    assert res["findings"][0]["severity"] == "HIGH"


def test_live_mode_integration_optional():
    """Optional live integration test executed only when a local Ollama daemon is reachable."""
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", 11434))
        s.close()
    except Exception:
        pytest.skip("Local Ollama daemon is not running at 127.0.0.1:11434")

    client = AIClient(mode="live")
    req = {
        "task": "classify_columns",
        "version": "1",
        "payload": {
            "dataset_id": "ds_live_integration",
            "columns": [
                {"name": "user_id", "inferred_type": "TEXT", "sample_values": ["USR-101"]},
            ],
        },
    }
    resp = client.invoke(req)
    assert resp["task"] == "classify_columns"
    assert resp["status"] in {"ok", "error"}
    assert isinstance(resp["needs_human_review"], bool)
