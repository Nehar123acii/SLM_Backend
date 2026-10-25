"""
tests/test_breach.py
====================
Test suite for DPDP breach simulation and readiness module (TASK K9).
Covers:
1. Blast radius separates confirmed / possible individuals and counts minors
2. Clock test with injectable time: 72h detailed due, no deadline on first intimation, extension flag changes status
3. Draft notices: individual has clauses (a)-(e), Board detailed has items (i)-(vi) with notices_sent in (vi),
   all marked "DRAFT SIMULATION", zero sentinel values
4. Severity orders work only and does not alter whether notices are generated
5. Warning fires when individual's only registered channel is in the leaked source
6. Ledger records incident_opened, incident_step, notice_sent, breach_simulated, and chain verifies
"""

import datetime
from datetime import timezone
import json
import pytest
from httpx import AsyncClient
from sqlalchemy.orm import Session

from backend.db.models import Column, Dataset, Incident, LedgerEvent, NoticeSent, Occurrence, Person
from backend.services.breach import (
    blast_radius,
    calculate_clocks,
    calculate_severity,
    generate_board_detailed_report,
    generate_board_first_intimation,
    generate_individual_notice,
    get_ordered_checklist,
    load_scenarios,
    simulate_breach,
)
from backend.services.ledger import verify_chain


# ---------------------------------------------------------------------------
# Test 1: Blast radius separates confirmed / possible and counts minors
# ---------------------------------------------------------------------------
def test_blast_radius_confirmed_possible_and_minors(db_session: Session):
    ds = Dataset(
        dataset_id="ds_test_breach_001",
        original_filename="patients_breach.csv",
        source_type="csv",
        row_count=10,
    )
    db_session.add(ds)
    db_session.flush()

    col_name = Column(dataset_id=ds.dataset_id, column_name="name", inferred_type="TEXT", category="name", impact_tier="2")
    col_phone = Column(dataset_id=ds.dataset_id, column_name="phone", inferred_type="TEXT", category="phone", impact_tier="2")
    col_pan = Column(dataset_id=ds.dataset_id, column_name="pan", inferred_type="TEXT", category="pan", impact_tier="3")
    col_dob = Column(dataset_id=ds.dataset_id, column_name="dob", inferred_type="TEXT", category="dob", impact_tier="2")
    db_session.add_all([col_name, col_phone, col_pan, col_dob])
    db_session.flush()

    p_strong = Person(resolution="strong", confidence=1.0)
    p_prob1 = Person(resolution="probable", confidence=0.6)
    p_prob2 = Person(resolution="probable", confidence=0.6)
    db_session.add_all([p_strong, p_prob1, p_prob2])
    db_session.flush()

    # p_strong has phone and pan (tier 3)
    occ1 = Occurrence(column_id=col_phone.id, person_id=p_strong.id, value_hmac="hmac_phone_1", masked_sample="+91 98****01")
    occ2 = Occurrence(column_id=col_pan.id, person_id=p_strong.id, value_hmac="hmac_pan_1", masked_sample="ABCDE****F")

    # p_prob1 has name
    occ3 = Occurrence(column_id=col_name.id, person_id=p_prob1.id, value_hmac="hmac_name_1", masked_sample="J*** D**")

    # p_prob2 has dob with is_minor=True
    occ4 = Occurrence(column_id=col_dob.id, person_id=p_prob2.id, value_hmac="hmac_dob_1", masked_sample="****-**-**", is_minor=True)

    db_session.add_all([occ1, occ2, occ3, occ4])
    db_session.commit()

    blast = blast_radius(db_session, [ds.dataset_id])

    assert blast["confirmed_people"] == 1
    assert blast["possible_people"] == 2
    assert blast["total_people"] == 3
    assert blast["people_range"] == "1 - 3"
    assert blast["minors_involved"] == 1
    assert blast["minors_count"] == 1
    assert blast["is_minor_count"] == 1
    assert "pan" in blast["high_impact_categories"]
    assert "phone" in blast["category_breakdown"]
    assert "pan" in blast["category_breakdown"]
    assert "dob" in blast["category_breakdown"]


# ---------------------------------------------------------------------------
# Test 2: Clock test with injectable time
# ---------------------------------------------------------------------------
def test_clock_injectable_time_and_extension():
    aware_dt = datetime.datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

    # 1. 4 hours later: Stage 1 elapsed time, Stage 2 countdown, no deadline on first intimation
    t1 = aware_dt + datetime.timedelta(hours=4)
    clocks1 = calculate_clocks(aware_at=aware_dt, board_extension_requested=False, current_time=t1)

    assert clocks1["module_label"] == "readiness for obligations from May 2027"
    assert clocks1["board_first_intimation"]["deadline"] is None
    assert clocks1["board_first_intimation"]["elapsed_seconds"] == 4 * 3600
    assert "4h 0m elapsed" in clocks1["board_first_intimation"]["elapsed_display"]
    assert clocks1["board_first_intimation"]["chips"][0]["verify"] is True
    assert clocks1["board_first_intimation"]["chips"][0]["verified"] is False

    assert clocks1["board_detailed_report"]["hours_limit"] == 72
    assert clocks1["board_detailed_report"]["status"] == "countdown"
    assert clocks1["board_detailed_report"]["seconds_remaining"] == 68 * 3600
    assert clocks1["board_detailed_report"]["chips"][0]["verify"] is True

    assert clocks1["individual_notice"]["deadline"] is None
    assert clocks1["individual_notice"]["requirement"] == "without delay"

    # 2. 75 hours later without extension -> overdue
    t2 = aware_dt + datetime.timedelta(hours=75)
    clocks2 = calculate_clocks(aware_at=aware_dt, board_extension_requested=False, current_time=t2)
    assert clocks2["board_detailed_report"]["status"] == "overdue"

    # 3. 75 hours later with written extension requested -> extension requested
    clocks3 = calculate_clocks(aware_at=aware_dt, board_extension_requested=True, current_time=t2)
    assert clocks3["board_detailed_report"]["status"] == "extension requested"


# ---------------------------------------------------------------------------
# Test 3: Notices clauses (a)-(e), Board detailed (i)-(vi) with notices_sent
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_notices_clauses_and_notices_sent_in_item_vi(client: AsyncClient, db_session: Session):
    # 1. Create incident via API
    res = await client.post(
        "/api/incidents",
        json={
            "report_text": "A staff workstation with customer billing data was lost during transit.",
            "reporter_role": "compliance_lead",
            "incident_type": "lost_device",
            "aware_at": "2026-10-25T08:00:00Z",
        },
    )
    assert res.status_code == 201
    inc_data = res.json()
    incident_ref = inc_data["incident_ref"]

    # 2. Record notices sent via API
    n1 = await client.post(
        f"/api/incidents/{incident_ref}/notices-sent",
        json={"recipient_ref": 101, "channel": "email", "notice_type": "individual"},
    )
    assert n1.status_code == 201

    n2 = await client.post(
        f"/api/incidents/{incident_ref}/notices-sent",
        json={"recipient_ref": 102, "channel": "phone", "notice_type": "individual"},
    )
    assert n2.status_code == 201

    # 3. Fetch draft notices
    notices_res = await client.get(f"/api/incidents/{incident_ref}/notices")
    assert notices_res.status_code == 200
    data = notices_res.json()
    drafts = data["notices"]

    # Check watermark
    assert "DRAFT SIMULATION" in drafts["individual_notice"]
    assert "DRAFT SIMULATION" in drafts["board_first_intimation"]
    assert "DRAFT SIMULATION" in drafts["board_detailed_report"]

    # Check clauses (a) to (e) in individual notice
    indiv = drafts["individual_notice"]
    assert "Clause (a)" in indiv
    assert "Clause (b)" in indiv
    assert "Clause (c)" in indiv
    assert "Clause (d)" in indiv
    assert "Clause (e)" in indiv
    assert "[BUSINESS_NAME]" in indiv

    # Check Board First Intimation structure
    b_first = drafts["board_first_intimation"]
    assert "Nature of the Incident" in b_first
    assert "Extent of Exposure" in b_first
    assert "Timing" in b_first
    assert "Location" in b_first
    assert "Likely Impact" in b_first

    # Check Board Detailed items (i) to (vi)
    b_detailed = drafts["board_detailed_report"]
    assert "Item (i) Facts and Reasons" in b_detailed
    assert "Item (ii) Mitigation Measures" in b_detailed
    assert "Item (iii) Findings About Cause" in b_detailed
    assert "Item (iv) Remedial Measures" in b_detailed
    assert "Item (v) Attribution / Perpetrators" in b_detailed
    assert "Item (vi) Report on Intimations Sent to Individuals" in b_detailed

    # Assert Item (vi) auto-fills summary from notices_sent
    assert "Total Notices Sent:** 2" in b_detailed
    assert "Email: 1 sent" in b_detailed
    assert "Phone: 1 sent" in b_detailed


# ---------------------------------------------------------------------------
# Test 4: Severity does not alter whether notices are generated
# ---------------------------------------------------------------------------
def test_severity_does_not_alter_notification_duty(db_session: Session):
    # Case 1: Low volume, low severity
    low_blast = {
        "records_count": 2,
        "total_people": 2,
        "confirmed_people": 1,
        "possible_people": 1,
        "category_breakdown": {"name": {"category": "name", "occurrence_count": 2}},
        "high_impact_categories": [],
        "minors_involved": 0,
    }
    sev_low, score_low, _ = calculate_severity(low_blast, exposure_types=["confidentiality"], device_protected="yes")
    assert sev_low == "low"

    # Case 2: High volume with Aadhaar and minors -> High severity
    high_blast = {
        "records_count": 500,
        "total_people": 150,
        "confirmed_people": 120,
        "possible_people": 30,
        "category_breakdown": {"aadhaar": {"category": "aadhaar", "occurrence_count": 120}},
        "high_impact_categories": ["aadhaar"],
        "minors_involved": 15,
    }
    sev_high, score_high, _ = calculate_severity(high_blast, exposure_types=["availability"], device_protected="no")
    assert sev_high == "high"

    # Verify that BOTH generate individual notices and Board intimations regardless of severity level
    aware_dt = datetime.datetime.now(timezone.utc)
    indiv_low = generate_individual_notice("Test Low", "Low incident", ["name"], aware_dt)
    indiv_high = generate_individual_notice("Test High", "High incident", ["aadhaar"], aware_dt)

    assert "Clause (a)" in indiv_low and "DRAFT SIMULATION" in indiv_low
    assert "Clause (a)" in indiv_high and "DRAFT SIMULATION" in indiv_high


# ---------------------------------------------------------------------------
# Test 5: Warning fires when individual's only registered channel is in leaked source
# ---------------------------------------------------------------------------
def test_warning_when_only_channel_in_leaked_source(db_session: Session):
    # Dataset A (leaked source)
    ds_leaked = Dataset(dataset_id="ds_leaked_01", original_filename="leaked_records.csv", row_count=5)
    # Dataset B (intact secondary repository)
    ds_safe = Dataset(dataset_id="ds_safe_01", original_filename="safe_records.csv", row_count=5)
    db_session.add_all([ds_leaked, ds_safe])
    db_session.flush()

    col_leaked_phone = Column(dataset_id=ds_leaked.dataset_id, column_name="phone", inferred_type="TEXT", category="phone", impact_tier="2")
    col_safe_name = Column(dataset_id=ds_safe.dataset_id, column_name="name", inferred_type="TEXT", category="name", impact_tier="2")
    col_safe_email = Column(dataset_id=ds_safe.dataset_id, column_name="email", inferred_type="TEXT", category="email", impact_tier="2")
    db_session.add_all([col_leaked_phone, col_safe_name, col_safe_email])
    db_session.flush()

    # Person 42 has phone in leaked source and name in safe source.
    # Person 42 has NO other contact channel in safe source.
    p42 = Person(id=42, resolution="strong", confidence=1.0)
    db_session.add(p42)
    db_session.flush()

    occ_leaked_phone = Occurrence(column_id=col_leaked_phone.id, person_id=p42.id, value_hmac="hmac_p42_phone", masked_sample="+91 99****42")
    occ_safe_name = Occurrence(column_id=col_safe_name.id, person_id=p42.id, value_hmac="hmac_p42_name", masked_sample="P*** F**")
    db_session.add_all([occ_leaked_phone, occ_safe_name])
    db_session.commit()

    # Blast radius on leaked dataset only
    blast1 = blast_radius(db_session, [ds_leaked.dataset_id])
    assert any("Person #42: only registered contact channel is in the affected data source" in w for w in blast1["only_channel_warnings"])

    # Now add an alternative email in the safe repository for Person 42
    occ_safe_email = Occurrence(column_id=col_safe_email.id, person_id=p42.id, value_hmac="hmac_p42_email", masked_sample="p***@safe.in")
    db_session.add(occ_safe_email)
    db_session.commit()

    blast2 = blast_radius(db_session, [ds_leaked.dataset_id])
    # The warning should NO longer fire for Person 42 because they have an intact channel in ds_safe
    assert not any("Person #42: only registered contact channel" in w for w in blast2["only_channel_warnings"])


# ---------------------------------------------------------------------------
# Test 6: Ledger records incident_opened, incident_step, notice_sent, breach_simulated
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ledger_records_and_chain_verifies(client: AsyncClient, db_session: Session):
    # Verify initial ledger chain
    res_chain_init = verify_chain(db_session)
    assert res_chain_init["ok"] is True

    # 1. Open incident -> triggers incident_opened ledger event
    inc_res = await client.post(
        "/api/incidents",
        json={
            "report_text": "Suspected breach of billing workstation after phishing email.",
            "reporter_role": "billing_admin",
            "incident_type": "account_compromised",
        },
    )
    assert inc_res.status_code == 201
    inc_ref = inc_res.json()["incident_ref"]

    # 2. Update checklist -> triggers incident_step ledger event
    patch_res = await client.patch(
        f"/api/incidents/{inc_ref}/checklist",
        json={"checklist": [{"step": 1, "task": "Isolate system", "completed": True}]},
    )
    assert patch_res.status_code == 200

    # 3. Record notice sent -> triggers notice_sent ledger event
    notif_res = await client.post(
        f"/api/incidents/{inc_ref}/notices-sent",
        json={"recipient_ref": 88, "channel": "email", "notice_type": "individual"},
    )
    assert notif_res.status_code == 201

    # 4. Run breach simulation -> triggers breach_simulated ledger event
    sim_res = await client.post(
        "/api/breach/simulate",
        json={
            "scenario": "owner_phone_stolen",
            "device_protected": "unknown",
        },
    )
    assert sim_res.status_code == 200

    # Verify that the entire ledger chain remains cryptographically valid
    res_chain_final = verify_chain(db_session)
    assert res_chain_final["ok"] is True

    # Check ledger events recorded
    events = db_session.query(LedgerEvent).order_by(LedgerEvent.seq.asc()).all()
    event_types = [e.event_type for e in events]

    assert "incident_opened" in event_types
    assert "incident_step" in event_types
    assert "notice_sent" in event_types
    assert "breach_simulated" in event_types

    # Ensure no personal data exists in ledger payload JSONs
    for e in events:
        assert "@" not in e.payload_json, f"Email found in ledger payload: {e.payload_json}"
        assert "+91" not in e.payload_json, f"Phone found in ledger payload: {e.payload_json}"
