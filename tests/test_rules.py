"""
tests/test_rules.py
===================
Comprehensive tests for DPDP compliance rules engine, questionnaire,
flag snapshots, and ledger audit logging:
- Empty business returns all NOT_ASSESSED, none GREEN
- Every rule has a fixture triggering concern and a fixture with positive evidence for GREEN
- Missing data returns NOT_ASSESSED
- 'not_sure' answer never yields GREEN
- unknown_purposes transitions: empty (NOT_ASSESSED) -> tier 2 unconfirmed (YELLOW) -> tier 3 unconfirmed (RED) -> all confirmed (GREEN)
- Flag state change records 'flag_change' in hash-chained ledger and chain verifies
- Metadata checks: allowed fix_actions, verify: true, verified: false, no 'Compliant' wording
"""

import json
from typing import Dict, List
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import create_app
from backend.db.models import (
    Column,
    Dataset,
    FlagResult,
    Occurrence,
    Person,
    PurposeLink,
    QuestionnaireAnswer,
)
from backend.services.rules import (
    ALLOWED_FIX_ACTIONS,
    QUESTIONNAIRE_KEYS,
    evaluate_rules,
    load_rules,
    run_flags,
)
from backend.services.purposes import ensure_purposes_seeded


@pytest.fixture
def app_client(db_session: Session):
    app = create_app()
    from backend.db.engine import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c


def test_empty_business_all_rules_not_assessed(db_session: Session):
    """An empty business with no datasets, columns, or questionnaire answers returns all NOT_ASSESSED, none GREEN."""
    results = evaluate_rules(db_session)
    assert len(results) >= 12

    for r in results:
        assert r.state == "NOT_ASSESSED", f"Rule '{r.rule_id}' returned '{r.state}' instead of 'NOT_ASSESSED' for empty business"
        assert r.state != "GREEN", f"Rule '{r.rule_id}' returned GREEN without positive evidence"


def test_missing_input_data_returns_not_assessed(db_session: Session):
    """When only collection_notice is answered 'yes', notice_at_collection is GREEN; other rules return NOT_ASSESSED."""
    db_session.add(QuestionnaireAnswer(key="collection_notice", answer="yes"))
    db_session.commit()

    results = {r.rule_id: r.state for r in evaluate_rules(db_session)}
    assert results["notice_at_collection"] == "GREEN"
    assert results["unrestricted_shared_source"] == "NOT_ASSESSED"
    assert results["vendors_unwritten_agreement"] == "NOT_ASSESSED"
    assert results["retention_policy"] == "NOT_ASSESSED"
    assert results["aadhaar_in_chat"] == "NOT_ASSESSED"
    assert results["health_data_safeguards"] == "NOT_ASSESSED"
    assert results["unknown_purposes"] == "NOT_ASSESSED"


def test_not_sure_answer_never_produces_green(db_session: Session):
    """An answer of 'not_sure' on any questionnaire question must never result in GREEN."""
    for k in QUESTIONNAIRE_KEYS:
        db_session.add(QuestionnaireAnswer(key=k, answer="not_sure"))
    db_session.commit()

    results = evaluate_rules(db_session)
    for r in results:
        assert r.state != "GREEN", f"Rule '{r.rule_id}' was evaluated as GREEN on 'not_sure' answer"


def test_unknown_purposes_rule_lifecycle(db_session: Session):
    """
    unknown_purposes lifecycle:
    1. No columns: NOT_ASSESSED
    2. Only tier 2 unconfirmed column: YELLOW
    3. Any tier 3 unconfirmed column: RED
    4. All columns confirmed: GREEN
    """
    ensure_purposes_seeded(db_session)
    # 1. No columns
    res_map = {r.rule_id: r for r in evaluate_rules(db_session)}
    assert res_map["unknown_purposes"].state == "NOT_ASSESSED"

    # 2. Add dataset and Tier 2 unconfirmed column (phone)
    ds = Dataset(dataset_id="ds_test_1", original_filename="test_customers.csv", source_type="csv")
    db_session.add(ds)
    col_phone = Column(dataset_id="ds_test_1", column_name="phone_number", inferred_type="TEXT", category="phone", impact_tier="2")
    db_session.add(col_phone)
    db_session.commit()

    res_map = {r.rule_id: r for r in evaluate_rules(db_session)}
    assert res_map["unknown_purposes"].state == "YELLOW"

    # 3. Add Tier 3 unconfirmed column (aadhaar)
    col_aadhaar = Column(dataset_id="ds_test_1", column_name="aadhaar_num", inferred_type="TEXT", category="aadhaar", impact_tier="3")
    db_session.add(col_aadhaar)
    db_session.commit()

    res_map = {r.rule_id: r for r in evaluate_rules(db_session)}
    assert res_map["unknown_purposes"].state == "RED"

    # 4. Confirm both columns
    pmap = ensure_purposes_seeded(db_session)
    pl1 = PurposeLink(column_id=col_phone.id, segment="customer", purpose_id=pmap["billing_payment"].id, status="confirmed")
    pl2 = PurposeLink(column_id=col_aadhaar.id, segment="customer", purpose_id=pmap["tax_records"].id, status="confirmed")
    db_session.add_all([pl1, pl2])
    db_session.commit()

    res_map = {r.rule_id: r for r in evaluate_rules(db_session)}
    assert res_map["unknown_purposes"].state == "GREEN"


def test_all_14_rules_have_concern_and_positive_evidence_fixtures(db_session: Session):
    """
    Verify each of the 14 rules has:
    1. A fixture that triggers its concern state (RED or YELLOW)
    2. A fixture with positive evidence giving GREEN
    """
    pmap = ensure_purposes_seeded(db_session)
    # ---------------------------------------------------------
    # 1 & 2: breach_contact_process and no_named_contact
    # ---------------------------------------------------------
    qa_bc = QuestionnaireAnswer(key="breach_contact", answer="no")
    db_session.add(qa_bc)
    db_session.commit()
    res = {r.rule_id: r.state for r in evaluate_rules(db_session)}
    assert res["breach_contact_process"] == "RED"
    assert res["no_named_contact"] == "RED"

    qa_bc.answer = "yes"
    db_session.commit()
    res = {r.rule_id: r.state for r in evaluate_rules(db_session)}
    assert res["breach_contact_process"] == "GREEN"
    assert res["no_named_contact"] == "GREEN"

    # ---------------------------------------------------------
    # 3: notice_at_collection
    # ---------------------------------------------------------
    qa_cn = QuestionnaireAnswer(key="collection_notice", answer="no")
    db_session.add(qa_cn)
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["notice_at_collection"] == "YELLOW"

    qa_cn.answer = "yes"
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["notice_at_collection"] == "GREEN"

    # ---------------------------------------------------------
    # 4 & 5: unrestricted_shared_source and data_on_personal_phones
    # ---------------------------------------------------------
    qa_sf = QuestionnaireAnswer(key="shared_folder", answer="yes")
    qa_pp = QuestionnaireAnswer(key="personal_phones", answer="yes")
    db_session.add_all([qa_sf, qa_pp])
    db_session.commit()
    res = {r.rule_id: r.state for r in evaluate_rules(db_session)}
    assert res["unrestricted_shared_source"] == "RED"
    assert res["data_on_personal_phones"] == "RED"

    qa_sf.answer = "no"
    qa_pp.answer = "no"
    db_session.commit()
    res = {r.rule_id: r.state for r in evaluate_rules(db_session)}
    assert res["unrestricted_shared_source"] == "GREEN"
    assert res["data_on_personal_phones"] == "GREEN"

    # ---------------------------------------------------------
    # 6: vendors_unwritten_agreement
    # ---------------------------------------------------------
    qa_v = QuestionnaireAnswer(key="vendors", answer="yes")
    db_session.add(qa_v)
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["vendors_unwritten_agreement"] == "RED"

    qa_v.answer = "no"
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["vendors_unwritten_agreement"] == "GREEN"

    # ---------------------------------------------------------
    # 7: retention_policy
    # ---------------------------------------------------------
    qa_ret = QuestionnaireAnswer(key="retention_policy", answer="no")
    db_session.add(qa_ret)
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["retention_policy"] == "YELLOW"

    qa_ret.answer = "yes"
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["retention_policy"] == "GREEN"

    # ---------------------------------------------------------
    # 8: minors_parental_consent
    # ---------------------------------------------------------
    qa_ch = QuestionnaireAnswer(key="children_served", answer="yes")
    db_session.add(qa_ch)
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["minors_parental_consent"] == "RED"

    qa_ch.answer = "no"
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["minors_parental_consent"] == "GREEN"

    # ---------------------------------------------------------
    # 9: health_data_safeguards
    # ---------------------------------------------------------
    ds_h = Dataset(dataset_id="ds_health", original_filename="clinic_records.csv", source_type="csv")
    col_h = Column(dataset_id="ds_health", column_name="diagnosis_notes", inferred_type="TEXT", category="health", impact_tier="3")
    db_session.add_all([ds_h, col_h])
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["health_data_safeguards"] == "RED"

    pl_h = PurposeLink(column_id=col_h.id, segment="patient", purpose_id=pmap["medical_care"].id, status="confirmed")
    db_session.add(pl_h)
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["health_data_safeguards"] == "GREEN"

    # ---------------------------------------------------------
    # 10: aadhaar_in_chat
    # ---------------------------------------------------------
    ds_wa = Dataset(dataset_id="ds_wa", original_filename="whatsapp_export.txt", source_type="whatsapp")
    col_wa_a = Column(dataset_id="ds_wa", column_name="aadhaar_col", inferred_type="TEXT", category="aadhaar", impact_tier="3")
    db_session.add_all([ds_wa, col_wa_a])
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["aadhaar_in_chat"] == "RED"

    # Remove Aadhaar from WhatsApp dataset, replace with regular message column confirmed
    db_session.delete(col_wa_a)
    col_wa_msg = Column(dataset_id="ds_wa", column_name="message_text", inferred_type="TEXT", category="phone", impact_tier="2")
    db_session.add(col_wa_msg)
    db_session.flush()
    pl_wa = PurposeLink(column_id=col_wa_msg.id, segment="customer", purpose_id=pmap["billing_payment"].id, status="confirmed")
    db_session.add(pl_wa)
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["aadhaar_in_chat"] == "GREEN"

    # ---------------------------------------------------------
    # 11: aadhaar_multiple_files
    # ---------------------------------------------------------
    ds_f1 = Dataset(dataset_id="ds_f1", original_filename="file1.csv", source_type="csv")
    ds_f2 = Dataset(dataset_id="ds_f2", original_filename="file2.csv", source_type="csv")
    col_a_f1 = Column(dataset_id="ds_f1", column_name="uid1", inferred_type="TEXT", category="aadhaar", impact_tier="3")
    col_a_f2 = Column(dataset_id="ds_f2", column_name="uid2", inferred_type="TEXT", category="aadhaar", impact_tier="3")
    db_session.add_all([ds_f1, ds_f2, col_a_f1, col_a_f2])
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["aadhaar_multiple_files"] == "RED"

    # Delete second file Aadhaar and confirm the first
    db_session.delete(col_a_f2)
    pl_af1 = PurposeLink(column_id=col_a_f1.id, segment="customer", purpose_id=pmap["tax_records"].id, status="confirmed")
    db_session.add(pl_af1)
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["aadhaar_multiple_files"] == "GREEN"

    # ---------------------------------------------------------
    # 12: employee_data_lawful_basis
    # ---------------------------------------------------------
    ds_staff = Dataset(dataset_id="ds_staff", original_filename="staff_payroll.csv", segment="staff", source_type="csv")
    col_staff_id = Column(dataset_id="ds_staff", column_name="emp_name", inferred_type="TEXT", category="name", impact_tier="2")
    db_session.add_all([ds_staff, col_staff_id])
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["employee_data_lawful_basis"] == "YELLOW"

    pl_staff = PurposeLink(column_id=col_staff_id.id, segment="staff", purpose_id=pmap["employment_payroll"].id, status="confirmed")
    db_session.add(pl_staff)
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["employee_data_lawful_basis"] == "GREEN"

    # ---------------------------------------------------------
    # 13: data_sprawl_files
    # ---------------------------------------------------------
    p1 = Person(resolution="strong", confidence=1.0)
    db_session.add(p1)
    db_session.flush()
    # Add occurrences linking person to 3 datasets
    occ1 = Occurrence(person_id=p1.id, column_id=col_h.id, row_ref="1", masked_sample="X", value_hmac="h1", origin="rule")
    occ2 = Occurrence(person_id=p1.id, column_id=col_a_f1.id, row_ref="1", masked_sample="X", value_hmac="h1", origin="rule")
    occ3 = Occurrence(person_id=p1.id, column_id=col_staff_id.id, row_ref="1", masked_sample="X", value_hmac="h1", origin="rule")
    db_session.add_all([occ1, occ2, occ3])
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["data_sprawl_files"] == "YELLOW"

    # Remove 3rd occurrence so person is in < 3 datasets and all columns confirmed
    db_session.delete(occ3)
    db_session.commit()
    assert {r.rule_id: r.state for r in evaluate_rules(db_session)}["data_sprawl_files"] == "GREEN"


def test_questionnaire_api_and_ledger_event(db_session: Session, app_client: TestClient):
    """
    POST /api/questionnaire:
    - answers yes/no/not_sure
    - appends ledger event 'questionnaire_answer' with ids and enum only
    - GET /api/questionnaire returns the 8 questions in plain business language
    """
    # 1. GET questions
    get_res = app_client.get("/api/questionnaire")
    assert get_res.status_code == 200
    questions = get_res.json()
    assert len(questions) == 8
    assert any(q["key"] == "cctv" for q in questions)
    assert any(q["key"] == "breach_contact" for q in questions)
    assert any(q["key"] == "shared_folder" for q in questions)
    assert any(q["key"] == "collection_notice" for q in questions)

    # 2. POST answer
    post_res = app_client.post("/api/questionnaire", json={"key": "breach_contact", "answer": "yes"})
    assert post_res.status_code == 200
    assert post_res.json()["saved"]["breach_contact"] == "yes"

    # 3. Verify ledger event
    ledger_res = app_client.get("/api/ledger")
    assert ledger_res.status_code == 200
    events = ledger_res.json()
    qa_events = [ev for ev in events if ev["type"] == "questionnaire_answer"]
    assert len(qa_events) >= 1
    latest_qa = qa_events[-1]
    payload = json.loads(latest_qa["payload_json"])
    assert payload["question_key"] == "breach_contact"
    assert payload["answer"] == "yes"

    # 4. Verify chain integrity
    v_res = app_client.get("/api/ledger/verify")
    assert v_res.status_code == 200
    assert v_res.json()["ok"] is True


def test_flags_run_and_state_change_ledger_logging(db_session: Session, app_client: TestClient):
    """
    POST /api/flags/run:
    - evaluates all rules
    - stores snapshot in flag_results
    - records 'flag_change' ledger event for changes
    - chain verifies
    - GET /api/flags returns latest snapshot with metadata
    """
    # Run initial flags (all NOT_ASSESSED in empty DB)
    run_1 = app_client.post("/api/flags/run")
    assert run_1.status_code == 200
    data_1 = run_1.json()
    assert "run_id" in data_1

    # Now change a questionnaire answer from empty to "no"
    app_client.post("/api/questionnaire", json={"key": "breach_contact", "answer": "no"})

    # Run flags again -> state change for breach_contact_process (NOT_ASSESSED -> RED)
    run_2 = app_client.post("/api/flags/run")
    assert run_2.status_code == 200

    # Verify ledger recorded flag_change
    ledger_res = app_client.get("/api/ledger")
    assert ledger_res.status_code == 200
    flag_change_events = [ev for ev in ledger_res.json() if ev["type"] == "flag_change"]
    assert len(flag_change_events) >= 1

    # Verify chain
    assert app_client.get("/api/ledger/verify").json()["ok"] is True

    # GET /api/flags
    flags_res = app_client.get("/api/flags")
    assert flags_res.status_code == 200
    flags_data = flags_res.json()
    assert len(flags_data) >= 12

    for f in flags_data:
        assert "rule_id" in f
        assert "state" in f
        assert "whats_right" in f
        assert "whats_not" in f
        assert "how_to_fix" in f
        assert "citation_hint" in f
        assert "fix_action" in f
        assert f["fix_action"] in ALLOWED_FIX_ACTIONS


def test_cctv_no_alone_never_makes_notice_at_collection_green(db_session: Session):
    """cctv answered 'no' alone never makes notice_at_collection GREEN (it remains NOT_ASSESSED)."""
    db_session.add(QuestionnaireAnswer(key="cctv", answer="no"))
    db_session.commit()

    results = {r.rule_id: r.state for r in evaluate_rules(db_session)}
    assert results["notice_at_collection"] == "NOT_ASSESSED"


def test_shared_folder_and_personal_phones_are_independent(db_session: Session):
    """shared_folder and personal_phones are independent: answering one does not change the other rule."""
    qa_sf = QuestionnaireAnswer(key="shared_folder", answer="yes")
    db_session.add(qa_sf)
    db_session.commit()

    res = {r.rule_id: r.state for r in evaluate_rules(db_session)}
    assert res["unrestricted_shared_source"] == "RED"
    assert res["data_on_personal_phones"] == "NOT_ASSESSED"

    qa_pp = QuestionnaireAnswer(key="personal_phones", answer="no")
    db_session.add(qa_pp)
    db_session.commit()

    res = {r.rule_id: r.state for r in evaluate_rules(db_session)}
    assert res["unrestricted_shared_source"] == "RED"
    assert res["data_on_personal_phones"] == "GREEN"

    qa_sf.answer = "no"
    db_session.commit()

    res = {r.rule_id: r.state for r in evaluate_rules(db_session)}
    assert res["unrestricted_shared_source"] == "GREEN"
    assert res["data_on_personal_phones"] == "GREEN"


def test_shared_folder_and_collection_notice_states(db_session: Session):
    """
    Each new answer value gives the exact state:
    - shared_folder yes -> RED; no -> GREEN with text 'Owner reports no shared folders (not verified by Kavach)'; not_sure / unanswered -> NOT_ASSESSED.
    - collection_notice no -> YELLOW; yes -> GREEN with text 'Owner reports a notice is shown (not verified by Kavach)'; not_sure / unanswered -> NOT_ASSESSED.
    """
    # 1. Unanswered
    res = {r.rule_id: r for r in evaluate_rules(db_session)}
    assert res["unrestricted_shared_source"].state == "NOT_ASSESSED"
    assert res["notice_at_collection"].state == "NOT_ASSESSED"

    # 2. not_sure
    qa_sf = QuestionnaireAnswer(key="shared_folder", answer="not_sure")
    qa_cn = QuestionnaireAnswer(key="collection_notice", answer="not_sure")
    db_session.add_all([qa_sf, qa_cn])
    db_session.commit()
    res = {r.rule_id: r for r in evaluate_rules(db_session)}
    assert res["unrestricted_shared_source"].state == "NOT_ASSESSED"
    assert res["notice_at_collection"].state == "NOT_ASSESSED"

    # 3. shared_folder yes -> RED; collection_notice no -> YELLOW
    qa_sf.answer = "yes"
    qa_cn.answer = "no"
    db_session.commit()
    res = {r.rule_id: r for r in evaluate_rules(db_session)}
    assert res["unrestricted_shared_source"].state == "RED"
    assert res["notice_at_collection"].state == "YELLOW"

    # 4. shared_folder no -> GREEN; collection_notice yes -> GREEN
    qa_sf.answer = "no"
    qa_cn.answer = "yes"
    db_session.commit()
    res = {r.rule_id: r for r in evaluate_rules(db_session)}
    assert res["unrestricted_shared_source"].state == "GREEN"
    assert any("Owner reports no shared folders (not verified by Kavach)" in ev for ev in res["unrestricted_shared_source"].evidence_refs)
    assert res["notice_at_collection"].state == "GREEN"
    assert any("Owner reports a notice is shown (not verified by Kavach)" in ev for ev in res["notice_at_collection"].evidence_refs)


def test_questionnaire_green_text_contains_owner_reports():
    """Every questionnaire-based GREEN text contains 'Owner reports'."""
    questionnaire_rule_ids = {
        "unrestricted_shared_source",
        "notice_at_collection",
        "breach_contact_process",
        "retention_policy",
        "data_on_personal_phones",
        "vendors_unwritten_agreement",
        "minors_parental_consent",
        "no_named_contact",
    }
    all_rules = {r["id"]: r for r in load_rules()}
    for rid in questionnaire_rule_ids:
        r = all_rules[rid]
        whats_right = r.get("whats_right", "")
        assert "Owner reports" in whats_right, f"Rule {rid} whats_right lacks 'Owner reports': {whats_right}"


def test_rules_yaml_metadata_and_wording_compliance():
    """Verify all rules maintain verify: true, verified: false, allowed fix_actions, and never use 'Compliant'."""
    all_rules = load_rules()
    assert len(all_rules) >= 12

    questionnaire_rule_ids = {
        "unrestricted_shared_source",
        "notice_at_collection",
        "breach_contact_process",
        "retention_policy",
        "data_on_personal_phones",
        "vendors_unwritten_agreement",
        "minors_parental_consent",
        "no_named_contact",
    }

    for r in all_rules:
        assert r.get("verify") is True, f"Rule {r['id']} missing verify: true"
        assert r.get("verified") is False, f"Rule {r['id']} has verified != false"
        assert r.get("fix_action") in ALLOWED_FIX_ACTIONS, f"Invalid fix_action for {r['id']}: {r.get('fix_action')}"

        whats_right = r.get("whats_right", "")
        assert len(whats_right) > 0, f"Rule {r['id']} missing whats_right"
        assert "Compliant" not in whats_right, f"Forbidden word 'Compliant' found in whats_right for {r['id']}"

        if r["id"] in questionnaire_rule_ids:
            assert "Owner reports" in whats_right, f"Questionnaire rule {r['id']} missing 'Owner reports' in whats_right"
        else:
            assert "No issue found by Kavach's checks" in whats_right, f"Data rule {r['id']} missing 'No issue found by Kavach's checks' in whats_right"
