"""
tests/test_rights.py
====================
Test suite for DPDP Rights Desk and Case Lifecycle Engine (TASK K10).
Covers:
- Intent classifier rules first (English, Hinglish, Kannada-in-Latin), AI client fallback when none.
- Sender resolution: strong via phone match, probable via name-only.
- Execution refused for probable identity until owner confirms.
- State machine lifecycle transitions; invalid jumps rejected; execution requires approved plan hash.
- Checklist items count equals independent count of sources holding the person.
- Zero raw personal values (sentinels) in DB, ledger payloads, or API responses.
- Cryptographic ledger events (case_received, case_identity, case_plan, case_approved, case_executed, case_closed) and chain verification.
"""

import datetime
from datetime import timezone
import json
import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from backend.db.models import Column, Dataset, LedgerEvent, Occurrence, Person, RightsCase
from backend.security import hmac_value, mask, normalise
from backend.services.ledger import verify_chain
from backend.services.rights import (
    classify_message,
    generate_case_checklist,
    parse_whatsapp_text,
    resolve_sender,
)


# ---------------------------------------------------------------------------
# Test 1: Intent classifier (Hinglish, Kannada-in-Latin, English)
# ---------------------------------------------------------------------------
def test_intent_classification_multilingual():
    # 1. Hinglish erasure message
    hinglish_msg = "Mera number delete kar dijiye please"
    res_hinglish = classify_message(hinglish_msg)
    assert res_hinglish["intent"] == "erase"
    assert res_hinglish["source"] == "rule"

    hinglish_msg2 = "meri details hata dijiye"
    res_hinglish2 = classify_message(hinglish_msg2)
    assert res_hinglish2["intent"] == "erase"
    assert res_hinglish2["source"] == "rule"

    # 2. Kannada-in-Latin erasure message
    kannada_msg = "Nanna details delete maadi"
    res_kannada = classify_message(kannada_msg)
    assert res_kannada["intent"] == "erase"
    assert res_kannada["source"] == "rule"

    kannada_msg2 = "nanna number delete maadi"
    res_kannada2 = classify_message(kannada_msg2)
    assert res_kannada2["intent"] == "erase"
    assert res_kannada2["source"] == "rule"

    # 3. English access message
    english_msg = "What details do you have about me?"
    res_english = classify_message(english_msg)
    assert res_english["intent"] == "access"
    assert res_english["source"] == "rule"

    english_msg2 = "send me my data"
    res_english2 = classify_message(english_msg2)
    assert res_english2["intent"] == "access"
    assert res_english2["source"] == "rule"

    # 4. Unknown/unmatched text invokes AI fallback (marked inferred)
    generic_text = "Good morning, will your office be open on Sunday?"
    res_generic = classify_message(generic_text)
    assert res_generic["source"] == "inferred"


# ---------------------------------------------------------------------------
# Test 2: Sender resolution: strong (phone) vs probable (name-only) & execution refusal
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sender_resolution_and_probable_refusal(client: AsyncClient, db_session: Session):
    # Setup test dataset with a phone and name column
    ds = Dataset(dataset_id="ds_res_01", original_filename="members.csv", source_type="csv", row_count=2)
    db_session.add(ds)
    db_session.flush()

    col_phone = Column(dataset_id=ds.dataset_id, column_name="phone", inferred_type="TEXT", category="phone", impact_tier="2")
    col_name = Column(dataset_id=ds.dataset_id, column_name="name", inferred_type="TEXT", category="name", impact_tier="2")
    db_session.add_all([col_phone, col_name])
    db_session.flush()

    # Person 10: strong phone match
    p_strong = Person(id=10, resolution="strong", confidence=1.0)
    # Person 20: probable name-only match
    p_prob = Person(id=20, resolution="probable", confidence=0.6)
    db_session.add_all([p_strong, p_prob])
    db_session.flush()

    phone_raw = "9812345678"
    p_hmac = hmac_value("phone", phone_raw)
    occ_phone = Occurrence(column_id=col_phone.id, person_id=p_strong.id, value_hmac=p_hmac, masked_sample="+91 98****78")

    name_raw = "Sunita Sharma"
    n_hmac = hmac_value("name", normalise("name", name_raw))
    occ_name = Occurrence(column_id=col_name.id, person_id=p_prob.id, value_hmac=n_hmac, masked_sample="S*** S***")
    db_session.add_all([occ_phone, occ_name])
    db_session.commit()

    # Case A: Strong phone match
    wa_strong = f"12/04/2026, 10:00 am - +91 {phone_raw}: Mera data delete kar do"
    res_a = await client.post("/api/rights/intake", json={"text": wa_strong})
    assert res_a.status_code == 201
    cases_a = res_a.json()
    assert len(cases_a) == 1
    assert cases_a[0]["person_id"] == 10
    assert cases_a[0]["resolution"] == "strong"
    assert cases_a[0]["identity_confirmed"] is True

    # Case B: Probable name-only match
    wa_prob = f"12/04/2026, 10:05 am - {name_raw}: Please delete my details"
    res_b = await client.post("/api/rights/intake", json={"text": wa_prob})
    assert res_b.status_code == 201
    cases_b = res_b.json()
    assert len(cases_b) == 1
    case_b_ref = cases_b[0]["case_ref"]
    assert cases_b[0]["person_id"] == 20
    assert cases_b[0]["resolution"] == "probable"
    assert cases_b[0]["identity_confirmed"] is False

    # Attempt to plan and approve Case B
    plan_res = await client.post(f"/api/cases/{case_b_ref}/plan")
    assert plan_res.status_code == 200
    plan_hash = plan_res.json()["plan_hash"]

    # Since identity was NOT confirmed for probable match, approving or executing directly should be refused
    app_res = await client.post(f"/api/cases/{case_b_ref}/approve", json={"confirm_hash": plan_hash})
    # Erasure engine refuses approval when probable match is unconfirmed
    assert app_res.status_code in (400, 422)

    # Now confirm identity for Case B
    confirm_res = await client.post(f"/api/cases/{case_b_ref}/confirm-identity")
    assert confirm_res.status_code == 200
    assert confirm_res.json()["identity_confirmed"] is True

    # Re-plan with confirmed identity and approve
    plan_res2 = await client.post(f"/api/cases/{case_b_ref}/plan")
    assert plan_res2.status_code == 200
    plan_hash2 = plan_res2.json()["plan_hash"]

    app_res2 = await client.post(f"/api/cases/{case_b_ref}/approve", json={"confirm_hash": plan_hash2})
    assert app_res2.status_code == 200
    assert app_res2.json()["status"] == "approved"

    # Execution now succeeds
    exec_res = await client.post(f"/api/cases/{case_b_ref}/execute")
    assert exec_res.status_code == 200
    assert exec_res.json()["status"] == "executed"


# ---------------------------------------------------------------------------
# Test 3: Lifecycle transitions and approval enforcement
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lifecycle_transitions_and_approval_enforcement(client: AsyncClient, db_session: Session):
    # Setup test person
    ds = Dataset(dataset_id="ds_trans_01", original_filename="clients.csv", source_type="csv", row_count=5)
    db_session.add(ds)
    db_session.flush()

    col = Column(dataset_id=ds.dataset_id, column_name="phone", inferred_type="TEXT", category="phone", impact_tier="2")
    db_session.add(col)
    db_session.flush()

    p = Person(id=30, resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ph = "9900112233"
    occ = Occurrence(column_id=col.id, person_id=p.id, value_hmac=hmac_value("phone", ph), masked_sample="+91 99****33")
    db_session.add(occ)
    db_session.commit()

    wa_text = f"15/05/2026, 11:30 am - +91 {ph}: Delete my records immediately"
    res = await client.post("/api/rights/intake", json={"text": wa_text})
    assert res.status_code == 201
    case = res.json()[0]
    case_ref = case["case_ref"]
    assert case["status"] == "received"

    # 1. Invalid jump: Try executing directly from received status
    exec_fail = await client.post(f"/api/cases/{case_ref}/execute")
    assert exec_fail.status_code == 400

    # 2. Invalid jump: Try approving without a plan
    app_fail = await client.post(f"/api/cases/{case_ref}/approve", json={"confirm_hash": "dummy_hash"})
    assert app_fail.status_code == 400

    # 3. Transition: received -> plan
    plan_res = await client.post(f"/api/cases/{case_ref}/plan")
    assert plan_res.status_code == 200
    plan_data = plan_res.json()
    assert plan_data["status"] == "plan"
    real_plan_hash = plan_data["plan_hash"]

    # 4. Try executing while in plan status (without approval)
    exec_fail2 = await client.post(f"/api/cases/{case_ref}/execute")
    assert exec_fail2.status_code == 400

    # 5. Try approving with wrong confirm_hash
    app_bad_hash = await client.post(f"/api/cases/{case_ref}/approve", json={"confirm_hash": "0" * 64})
    assert app_bad_hash.status_code == 400

    # 6. Approve with matching plan_hash
    app_ok = await client.post(f"/api/cases/{case_ref}/approve", json={"confirm_hash": real_plan_hash})
    assert app_ok.status_code == 200
    assert app_ok.json()["status"] == "approved"

    # 7. Execute
    exec_ok = await client.post(f"/api/cases/{case_ref}/execute")
    assert exec_ok.status_code == 200
    assert exec_ok.json()["status"] == "executed"

    # 8. Close case
    close_ok = await client.post(f"/api/cases/{case_ref}/close")
    assert close_ok.status_code == 200
    assert close_ok.json()["status"] == "closed"


# ---------------------------------------------------------------------------
# Test 4: Checklist items equal independent count of sources holding the person
# ---------------------------------------------------------------------------
def test_checklist_items_equal_source_count(db_session: Session):
    ds1 = Dataset(dataset_id="ds_check_01", original_filename="appointments.csv", source_type="csv")
    ds2 = Dataset(dataset_id="ds_check_02", original_filename="billing.xlsx", source_type="excel")
    ds3 = Dataset(dataset_id="ds_check_03", original_filename="staff_payroll.csv", source_type="csv")
    db_session.add_all([ds1, ds2, ds3])
    db_session.flush()

    col1 = Column(dataset_id=ds1.dataset_id, column_name="phone", inferred_type="TEXT", category="phone")
    col2 = Column(dataset_id=ds2.dataset_id, column_name="phone", inferred_type="TEXT", category="phone")
    col3 = Column(dataset_id=ds3.dataset_id, column_name="phone", inferred_type="TEXT", category="phone")
    db_session.add_all([col1, col2, col3])
    db_session.flush()

    # Person 50 has occurrences in ds1 and ds2 only (2 sources)
    p = Person(id=50, resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    occ1 = Occurrence(column_id=col1.id, person_id=p.id, value_hmac="hmac_50_1", masked_sample="+91 97****01")
    occ2 = Occurrence(column_id=col2.id, person_id=p.id, value_hmac="hmac_50_2", masked_sample="+91 97****02")
    db_session.add_all([occ1, occ2])
    db_session.commit()

    checklist = generate_case_checklist(db_session, p.id)
    assert len(checklist) == 2
    sources = {item["filename"] for item in checklist}
    assert sources == {"appointments.csv", "billing.xlsx"}
    assert "staff_payroll.csv" not in sources


# ---------------------------------------------------------------------------
# Test 5: Zero sentinel values in DB, ledger or responses
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_zero_sentinel_values(client: AsyncClient, db_session: Session):
    sentinel_phone = "9887766554"
    sentinel_name = "SentinelTargetPerson"
    sentinel_message_text = "I demand full erasure of my clinical record immediately"

    wa_text = f"18/06/2026, 09:15 am - {sentinel_name}: My contact is +91 {sentinel_phone}, {sentinel_message_text}"

    res = await client.post("/api/rights/intake", json={"text": wa_text})
    assert res.status_code == 201
    data = res.json()

    # 1. Assert sentinel does not appear in API response
    response_text = res.text
    assert sentinel_phone not in response_text
    assert sentinel_name not in response_text

    case_ref = data[0]["case_ref"]
    case_db = db_session.query(RightsCase).filter_by(case_ref=case_ref).first()
    assert case_db is not None

    # 2. Assert sentinel is masked in database
    assert sentinel_phone not in case_db.sender_masked
    assert sentinel_name not in case_db.sender_masked
    assert sentinel_phone not in (case_db.message_excerpt_masked or "")
    assert "[PHONE]" in (case_db.message_excerpt_masked or "")

    # 3. Assert sentinel does not appear in ledger payloads
    events = db_session.query(LedgerEvent).all()
    for e in events:
        assert sentinel_phone not in e.payload_json
        assert sentinel_name not in e.payload_json


# ---------------------------------------------------------------------------
# Test 6: Ledger records events and chain verifies
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ledger_records_and_chain_verifies(client: AsyncClient, db_session: Session):
    # Verify initial ledger chain
    init_chain = verify_chain(db_session)
    assert init_chain["ok"] is True

    # Setup a person in DB for full flow
    ds = Dataset(dataset_id="ds_led_01", original_filename="patients.csv", source_type="csv", row_count=3)
    db_session.add(ds)
    db_session.flush()

    col = Column(dataset_id=ds.dataset_id, column_name="phone", inferred_type="TEXT", category="phone", impact_tier="2")
    db_session.add(col)
    db_session.flush()

    p = Person(id=60, resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ph = "9112233445"
    occ = Occurrence(column_id=col.id, person_id=p.id, value_hmac=hmac_value("phone", ph), masked_sample="+91 91****45")
    db_session.add(occ)
    db_session.commit()

    # 1. case_received
    intake_res = await client.post("/api/rights/intake", json={"text": f"20/07/2026, 04:00 pm - +91 {ph}: Delete my data"})
    assert intake_res.status_code == 201
    case_ref = intake_res.json()[0]["case_ref"]

    # 2. case_identity
    id_res = await client.post(f"/api/cases/{case_ref}/confirm-identity")
    assert id_res.status_code == 200

    # 3. case_plan
    plan_res = await client.post(f"/api/cases/{case_ref}/plan")
    assert plan_res.status_code == 200
    plan_hash = plan_res.json()["plan_hash"]

    # 4. case_approved
    app_res = await client.post(f"/api/cases/{case_ref}/approve", json={"confirm_hash": plan_hash})
    assert app_res.status_code == 200

    # 5. case_executed
    exec_res = await client.post(f"/api/cases/{case_ref}/execute")
    assert exec_res.status_code == 200

    # 6. case_closed
    close_res = await client.post(f"/api/cases/{case_ref}/close")
    assert close_res.status_code == 200

    # Check ledger events
    events = db_session.query(LedgerEvent).order_by(LedgerEvent.seq.asc()).all()
    event_types = [e.event_type for e in events]

    assert "case_received" in event_types
    assert "case_identity" in event_types
    assert "case_plan" in event_types
    assert "case_approved" in event_types
    assert "case_executed" in event_types
    assert "case_closed" in event_types

    # Cryptographic verification
    final_chain = verify_chain(db_session)
    assert final_chain["ok"] is True
    assert final_chain["checked"] >= 6
