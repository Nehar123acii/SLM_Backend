import os
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import create_app
from backend.services.ledger import (
    GENESIS_PREV_HASH,
    append_event,
    check_payload_guard,
    repair_event,
    tamper_event,
    verify_chain,
)


@pytest.fixture
def app_client(db_session: Session):
    app = create_app()
    from backend.api.deps import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_fresh_chain_verifies_and_appends_keep_it_valid(db_session: Session):
    """Verify fresh chain verifies, and successive events maintain cryptographic validity."""
    v0 = verify_chain(db_session)
    assert v0["ok"] is True
    assert v0["checked"] == 0

    # Append 1st event
    ev1 = append_event(db_session, "scan", {"source": "patients.xlsx", "record_count": 100})
    assert ev1.seq == 1
    assert ev1.prev_hash == GENESIS_PREV_HASH

    v1 = verify_chain(db_session)
    assert v1["ok"] is True
    assert v1["checked"] == 1

    # Append 2nd event
    ev2 = append_event(db_session, "upload", {"dataset_id": "ds_123", "row_count": 50})
    assert ev2.seq == 2
    assert ev2.prev_hash == ev1.hash

    v2 = verify_chain(db_session)
    assert v2["ok"] is True
    assert v2["checked"] == 2


def test_tamper_names_seq_and_type_repair_restores_validity(db_session: Session):
    """Verify tampering turns verify to ok=False naming exact seq and event type, and repair restores it."""
    ev1 = append_event(db_session, "upload", {"dataset_id": "ds_abc", "row_count": 10})
    ev2 = append_event(db_session, "classify", {"model": "mock", "columns_classified": 5})
    ev3 = append_event(db_session, "report", {"type": "readiness_summary", "score": 90})

    # Initial chain is intact
    assert verify_chain(db_session)["ok"] is True

    # Tamper event #2
    t_res = tamper_event(db_session, seq=2)
    assert t_res["ok"] is True
    assert t_res["tampered_seq"] == 2
    assert t_res["event_type"] == "classify"

    # Verify fails and names exact seq and event type
    v_tampered = verify_chain(db_session)
    assert v_tampered["ok"] is False
    assert v_tampered["broken_at_seq"] == 2
    assert v_tampered["broken_event_type"] == "classify"
    assert "mismatch" in v_tampered["reason"].lower()

    # Repair event #2
    r_res = repair_event(db_session, seq=2)
    assert r_res["ok"] is True
    assert r_res["repaired_count"] == 1

    # Verify succeeds again
    v_repaired = verify_chain(db_session)
    assert v_repaired["ok"] is True
    assert v_repaired["checked"] == 3


def test_tamper_and_repair_endpoints_require_kavach_dev(db_session: Session, app_client: TestClient):
    """Verify /api/dev/tamper and /api/dev/repair return 404 when KAVACH_DEV != '1'."""
    append_event(db_session, "init", {"status": "started"})

    # Ensure KAVACH_DEV is unset or 0
    os.environ.pop("KAVACH_DEV", None)

    res_t = app_client.post("/api/dev/tamper", json={"seq": 1})
    assert res_t.status_code == 404

    res_r = app_client.post("/api/dev/repair", json={"seq": 1})
    assert res_r.status_code == 404

    # Now set KAVACH_DEV=1
    os.environ["KAVACH_DEV"] = "1"
    try:
        res_t2 = app_client.post("/api/dev/tamper", json={"seq": 1})
        assert res_t2.status_code == 200

        res_r2 = app_client.post("/api/dev/repair", json={"seq": 1})
        assert res_r2.status_code == 200
    finally:
        os.environ.pop("KAVACH_DEV", None)


def test_payload_guard_rejects_pii_and_freetext():
    """Verify payload guard rejects phone, email, Aadhaar, PAN, and free-text strings."""
    # 1. Valid payloads (ids, counts, hashes, timestamps, enum strings)
    valid_payload = {
        "dataset_id": "ds_987654",
        "row_count": 120,
        "file_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "status": "confirmed",
        "timestamp": "2026-10-25T12:00:00Z",
    }
    check_payload_guard(valid_payload)  # Should not raise

    # 2. Reject Phone
    with pytest.raises(ValueError, match="Phone"):
        check_payload_guard({"user_contact": "+91 9876543210"})

    # 3. Reject Email
    with pytest.raises(ValueError, match="Email"):
        check_payload_guard({"contact": "user.name@example.com"})

    # 4. Reject Aadhaar
    with pytest.raises(ValueError, match="Aadhaar"):
        check_payload_guard({"aadhaar_ref": "1234 5678 9012"})

    # 5. Reject PAN
    with pytest.raises(ValueError, match="PAN"):
        check_payload_guard({"pan_token": "ABCDE1234F"})

    # 6. Reject Free-Text sentence
    with pytest.raises(ValueError, match="Free-text"):
        check_payload_guard({"notes": "Patient requested complete deletion of all records immediately"})


def test_upload_and_answer_lifecycle_ledger_logging(db_session: Session, app_client: TestClient):
    """
    Upload a sample file and POST one answer through the API,
    then assert the ledger contains an 'upload' event and an 'answer' event,
    the chain verifies, and the answer event payload contains no name.
    """
    csv_bytes = b"customer_name,phone_number\nAlice Kumar,9876543210\n"
    files = {"file": ("test_customers.csv", csv_bytes, "text/csv")}
    upload_res = app_client.post("/api/v1/inventory/upload", files=files)
    assert upload_res.status_code == 200, f"Upload failed: {upload_res.text}"
    upload_data = upload_res.json()
    dataset_id = upload_data["dataset_id"]

    from backend.db.models import Column
    col = db_session.query(Column).filter(Column.dataset_id == dataset_id).first()
    assert col is not None
    col_id = col.id

    answer_name = "Alice Administrator"
    ans_res = app_client.post(
        "/answers",
        json={
            "column_id": col_id,
            "segment": "customer",
            "purpose_ids": ["billing_payment"],
            "answered_by": answer_name,
        },
    )
    assert ans_res.status_code == 201, f"Answer failed: {ans_res.text}"

    # Verify ledger via API
    ledger_res = app_client.get("/api/ledger")
    assert ledger_res.status_code == 200
    events = ledger_res.json()

    event_types = [ev["type"] for ev in events]
    assert "upload" in event_types, f"'upload' not in ledger events: {event_types}"
    assert "answer" in event_types, f"'answer' not in ledger events: {event_types}"

    # Verify chain
    v_res = app_client.get("/api/ledger/verify")
    assert v_res.status_code == 200
    assert v_res.json()["ok"] is True

    # Assert answer event payload contains no name
    answer_events = [ev for ev in events if ev["type"] == "answer"]
    assert len(answer_events) >= 1
    for a_ev in answer_events:
        payload_str = a_ev["payload_json"]
        assert answer_name not in payload_str, f"Raw name '{answer_name}' found in answer ledger payload!"
        assert "Alice" not in payload_str, "Name token 'Alice' found in answer ledger payload!"
        assert "answered_by_hash" in payload_str, "Missing 'answered_by_hash' in answer payload!"

