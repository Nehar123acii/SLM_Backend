"""
tests/test_erasure.py
=====================
Comprehensive tests for DPDP Erasure Engine (TASK K8):
- Plan for a strong-match person lists every source holding them; counts equal independent count.
- Probable identity: all REVIEW and execute is refused until confirmed.
- Approve with a wrong hash is rejected; execute without approval is refused.
- After execute: the originals are byte-identical (compare SHA-256 before and after).
- Residual check reports 0 unexpected on the cleaned copies; the positive control passes.
- A cleaned CSV cell starting with = is prefixed to prevent formula injection.
- Receipt contains no raw phone, email, Aadhaar or name (search its bytes for sentinel values).
- Ledger shows the four events and the chain verifies.
- tests/test_no_raw_values.py still passes.
"""

import csv
import hashlib
import json
import os
import shutil
import tempfile
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from backend.config import settings
from backend.main import create_app
from backend.db.engine import get_db
from backend.db.models import Column, Dataset, ErasurePlan, LedgerEvent, Occurrence, Person
from backend.security import normalise, mask, hmac_value
from backend.services.erasure import (
    compile_plan,
    approve,
    execute,
    confirm_identity_for_plan,
    _sha256_file,
    _run_positive_control,
)
from backend.services.ledger import verify_chain


@pytest.fixture
def app_client(db_session: Session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_uploads_env(tmp_path):
    """Sets up a clean temporary workspace for original source files."""
    old_upload_dir = settings.upload_temp_dir
    temp_dir = str(tmp_path / "uploads_temp")
    os.makedirs(temp_dir, exist_ok=True)
    settings.upload_temp_dir = temp_dir
    yield temp_dir
    settings.upload_temp_dir = old_upload_dir


def test_plan_strong_match_lists_all_sources_and_counts(db_session: Session, test_uploads_env: str):
    """
    Plan for a strong-match person lists every source holding them;
    counts equal an independent count from the sample files.
    """
    # 1. Create strong person
    p = Person(resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    # 2. Create datasets
    ds_appt = Dataset(
        dataset_id="ds_appt",
        original_filename="appointments_form.csv",
        source_type="csv",
        temp_file_path=os.path.join(test_uploads_env, "appointments_form.csv"),
    )
    ds_pat = Dataset(
        dataset_id="ds_pat",
        original_filename="patients.xlsx",
        source_type="excel",
        temp_file_path=os.path.join(test_uploads_env, "patients.xlsx"),
    )
    ds_bill = Dataset(
        dataset_id="ds_bill",
        original_filename="billing.csv",
        source_type="csv",
        temp_file_path=os.path.join(test_uploads_env, "billing.csv"),
    )
    db_session.add_all([ds_appt, ds_pat, ds_bill])
    db_session.flush()

    # 3. Create columns
    col_appt_phone = Column(dataset_id="ds_appt", column_name="Phone", inferred_type="TEXT", category="phone")
    col_pat_email = Column(dataset_id="ds_pat", column_name="Email", inferred_type="TEXT", category="email")
    col_pat_notes = Column(dataset_id="ds_pat", column_name="notes", inferred_type="TEXT", category="health")
    col_bill_phone = Column(dataset_id="ds_bill", column_name="phone", inferred_type="TEXT", category="phone")
    col_bill_inv = Column(dataset_id="ds_bill", column_name="invoice_no", inferred_type="TEXT", category="other")
    db_session.add_all([col_appt_phone, col_pat_email, col_pat_notes, col_bill_phone, col_bill_inv])
    db_session.flush()

    # 4. Create occurrences
    occ1 = Occurrence(person_id=p.id, column_id=col_appt_phone.id, row_ref="R2", masked_sample="98765*****", value_hmac=hmac_value("phone", "9876543210"), origin="rule")
    occ2 = Occurrence(person_id=p.id, column_id=col_pat_email.id, row_ref="R2", masked_sample="r***@example.com", value_hmac=hmac_value("email", "ramesh@example.com"), origin="rule")
    occ3 = Occurrence(person_id=p.id, column_id=col_pat_notes.id, row_ref="R2", masked_sample="diabetes check", value_hmac=hmac_value("health", "diabetes"), origin="rule")
    occ4 = Occurrence(person_id=p.id, column_id=col_bill_phone.id, row_ref="R5", masked_sample="98765*****", value_hmac=hmac_value("phone", "9876543210"), origin="rule")
    occ5 = Occurrence(person_id=p.id, column_id=col_bill_inv.id, row_ref="R5", masked_sample="INV-***", value_hmac=hmac_value("other", "INV-1001"), origin="rule")
    db_session.add_all([occ1, occ2, occ3, occ4, occ5])
    db_session.commit()

    # Compile plan
    plan = compile_plan(db_session, person_id=p.id)

    assert plan["person_id"] == p.id
    assert plan["identity_resolution"] == "strong"
    assert plan["identity_confirmed"] is True
    assert set(plan["sources_holding"]) == {"appointments_form.csv", "patients.xlsx", "billing.csv"}

    counts = plan["action_counts"]
    # appt Phone: ERASE, pat Email: ERASE, pat notes: RETAIN, bill phone: MASK, bill invoice: RETAIN
    assert counts["ERASE"] == 2
    assert counts["MASK"] == 1
    assert counts["RETAIN"] == 2
    assert counts["REVIEW"] == 0

    assert "plan_hash" in plan
    assert len(plan["plan_hash"]) == 64


def test_probable_identity_blocks_execution(db_session: Session, test_uploads_env: str):
    """
    Probable identity: all items default to REVIEW and approval/execution is refused
    until owner confirms identity.
    """
    p = Person(resolution="probable", confidence=0.6)
    db_session.add(p)
    db_session.flush()

    ds = Dataset(dataset_id="ds_prob", original_filename="patients.xlsx", source_type="excel", temp_file_path=os.path.join(test_uploads_env, "patients.xlsx"))
    db_session.add(ds)
    db_session.flush()

    col = Column(dataset_id="ds_prob", column_name="Name", inferred_type="TEXT", category="name")
    db_session.add(col)
    db_session.flush()

    occ = Occurrence(person_id=p.id, column_id=col.id, row_ref="R3", masked_sample="R***** K****", value_hmac=hmac_value("name", "ramesh kumar"), origin="rule")
    db_session.add(occ)
    db_session.commit()

    plan = compile_plan(db_session, person_id=p.id)
    assert plan["identity_resolution"] == "probable"
    assert plan["status"] == "blocked_identity"
    assert plan["action_counts"]["REVIEW"] == 1
    assert plan["action_counts"]["ERASE"] == 0

    # Attempt to approve -> refused
    with pytest.raises(ValueError, match="Execution refused|identity must be confirmed"):
        approve(db_session, plan["plan_id"], plan["plan_hash"])

    # Attempt to execute -> refused
    with pytest.raises(ValueError, match="Execution refused|not approved"):
        execute(db_session, plan["plan_id"])

    # Confirm identity -> unblocks
    unblocked = confirm_identity_for_plan(db_session, plan["plan_id"])
    assert unblocked["status"] == "plan_ready"
    assert unblocked["identity_confirmed"] is True
    assert unblocked["action_counts"]["ERASE"] == 1


def test_approve_with_wrong_hash_and_unapproved_execute_refused(db_session: Session, test_uploads_env: str):
    """Approve with a wrong hash is rejected; execute without approval is refused."""
    p = Person(resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ds = Dataset(dataset_id="ds_t3", original_filename="billing.csv", source_type="csv", temp_file_path=os.path.join(test_uploads_env, "billing.csv"))
    db_session.add(ds)
    db_session.flush()

    col = Column(dataset_id="ds_t3", column_name="phone", inferred_type="TEXT", category="phone")
    db_session.add(col)
    db_session.flush()

    occ = Occurrence(person_id=p.id, column_id=col.id, row_ref="R2", masked_sample="98765*****", value_hmac=hmac_value("phone", "9876543210"), origin="rule")
    db_session.add(occ)
    db_session.commit()

    plan = compile_plan(db_session, person_id=p.id)
    plan_id = plan["plan_id"]
    correct_hash = plan["plan_hash"]
    wrong_hash = "0" * 64

    # 1. Approve with wrong hash is rejected
    with pytest.raises(ValueError, match="confirm_hash does not match stored plan_hash"):
        approve(db_session, plan_id, confirm_hash=wrong_hash)

    # 2. Execute without approval is refused
    with pytest.raises(ValueError, match="is not approved"):
        execute(db_session, plan_id)

    # 3. Approve with correct hash succeeds
    app_res = approve(db_session, plan_id, confirm_hash=correct_hash)
    assert app_res["status"] == "approved"


def test_statutory_retention_override_prevention(db_session: Session):
    """Overriding an item to RETAIN that has a statutory mandate to ERASE is rejected."""
    p = Person(resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ds = Dataset(dataset_id="ds_stat", original_filename="appointments_form.csv", source_type="csv")
    db_session.add(ds)
    db_session.flush()

    col = Column(dataset_id="ds_stat", column_name="Phone", inferred_type="TEXT", category="phone")
    db_session.add(col)
    db_session.flush()

    occ = Occurrence(person_id=p.id, column_id=col.id, row_ref="R2", masked_sample="98765*****", value_hmac=hmac_value("phone", "9876543210"), origin="rule")
    db_session.add(occ)
    db_session.commit()

    # Attempt to override APPT phone to RETAIN (which has statutory s.6(4) ERASE mandate)
    with pytest.raises(ValueError, match=r"statutory requirement mandates erasure under DPDP Act s\.6\(4\)"):
        compile_plan(db_session, person_id=p.id, overrides={str(occ.id): "RETAIN"})


def test_execute_preserves_byte_identical_originals(db_session: Session, test_uploads_env: str):
    """
    After execute: the originals are byte-identical (compare SHA-256 before and after).
    Cleaned copy is written with a generated filename.
    """
    # Create sample CSV file in uploads_temp
    csv_file = os.path.join(test_uploads_env, "appointments_form.csv")
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Timestamp", "Name", "Phone", "Reason"])
        writer.writerow(["2026-10-20 10:00", "Ramesh Kumar", "9876543210", "Routine Checkup"])
        writer.writerow(["2026-10-20 10:30", "Other Patient", "8888888888", "Consultation"])

    orig_sha256 = _sha256_file(csv_file)

    p = Person(resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ds = Dataset(dataset_id="ds_exec_test", original_filename="appointments_form.csv", source_type="csv", temp_file_path=csv_file)
    db_session.add(ds)
    db_session.flush()

    col_phone = Column(dataset_id="ds_exec_test", column_name="Phone", inferred_type="TEXT", category="phone")
    db_session.add(col_phone)
    db_session.flush()

    occ = Occurrence(person_id=p.id, column_id=col_phone.id, row_ref="R2", masked_sample="98765*****", value_hmac=hmac_value("phone", "9876543210"), origin="rule")
    db_session.add(occ)
    db_session.commit()

    plan = compile_plan(db_session, person_id=p.id)
    approve(db_session, plan["plan_id"], plan["plan_hash"])

    receipt = execute(db_session, plan["plan_id"])

    # 1. Assert original file on disk is byte-identical
    after_sha256 = _sha256_file(csv_file)
    assert orig_sha256 == after_sha256

    # 2. Assert cleaned copy exists in data/out/<plan_id> and filename is generated (never the uploaded filename)
    assert len(receipt["sources"]) == 1
    clean_fn = receipt["sources"][0]["cleaned_filename"]
    assert clean_fn != "appointments_form.csv"
    assert clean_fn.startswith("cleaned_")


def test_residual_check_and_positive_control(db_session: Session, test_uploads_env: str):
    """
    Residual check reports 0 unexpected on the cleaned copies;
    the positive control passes.
    """
    assert _run_positive_control() is True

    # Create CSV
    csv_file = os.path.join(test_uploads_env, "billing.csv")
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["invoice_no", "phone"])
        writer.writerow(["INV-001", "9876543210"])

    p = Person(resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ds = Dataset(dataset_id="ds_res", original_filename="billing.csv", source_type="csv", temp_file_path=csv_file)
    col_phone = Column(dataset_id="ds_res", column_name="phone", inferred_type="TEXT", category="phone")
    db_session.add_all([ds, col_phone])
    db_session.flush()

    occ = Occurrence(person_id=p.id, column_id=col_phone.id, row_ref="R2", masked_sample="98765*****", value_hmac=hmac_value("phone", "9876543210"), origin="rule")
    db_session.add(occ)
    db_session.commit()

    plan = compile_plan(db_session, person_id=p.id)
    approve(db_session, plan["plan_id"], plan["plan_hash"])
    receipt = execute(db_session, plan["plan_id"])

    res_scan = receipt["residual_scan"]
    assert res_scan["unexpected_remaining"] == 0
    assert res_scan["scanner_control_passed"] is True
    assert receipt["compliance_statement"] == "No issue found by Kavach's checks"
    assert "deleted from everywhere" not in json.dumps(receipt)


def test_cleaned_csv_cell_formula_injection_prevention(db_session: Session, test_uploads_env: str):
    """A cleaned CSV cell starting with =, +, -, @ must be prefixed with an apostrophe."""
    csv_file = os.path.join(test_uploads_env, "formula_test.csv")
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "formula_col", "phone"])
        writer.writerow(["1", "=SUM(A1:A10)", "9876543210"])
        writer.writerow(["2", "+cmd|' /C calc'!A0", "8888888888"])
        writer.writerow(["3", "-100", "7777777777"])
        writer.writerow(["4", "@SUM(1,2)", "6666666666"])

    p = Person(resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ds = Dataset(dataset_id="ds_formula", original_filename="formula_test.csv", source_type="csv", temp_file_path=csv_file)
    col_phone = Column(dataset_id="ds_formula", column_name="phone", inferred_type="TEXT", category="phone")
    db_session.add_all([ds, col_phone])
    db_session.flush()

    occ = Occurrence(person_id=p.id, column_id=col_phone.id, row_ref="R2", masked_sample="98765*****", value_hmac=hmac_value("phone", "9876543210"), origin="rule")
    db_session.add(occ)
    db_session.commit()

    plan = compile_plan(db_session, person_id=p.id)
    approve(db_session, plan["plan_id"], plan["plan_hash"])
    receipt = execute(db_session, plan["plan_id"])

    # Read output cleaned file
    clean_path = receipt["sources"][0]["cleaned_filename"]
    out_dir = os.path.join("data", "out", plan["plan_id"])
    full_clean_path = os.path.join(out_dir, clean_path)

    with open(full_clean_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    # Assert cells starting with =, +, -, @ are prefixed with '
    assert rows[1][1] == "'=SUM(A1:A10)"
    assert rows[2][1] == "'+cmd|' /C calc'!A0"
    assert rows[3][1] == "'-100"
    assert rows[4][1] == "'@SUM(1,2)"


def test_receipt_contains_no_raw_sentinel_values(db_session: Session, test_uploads_env: str):
    """Receipt contains no raw phone, email, Aadhaar or name (search bytes for sentinel values)."""
    sentinel_phone = "9876543210"
    sentinel_email = "sentinel.patient@example.org"
    sentinel_aadhaar = "999912345678"
    sentinel_name = "Ramesh Kumar Sharma"

    csv_file = os.path.join(test_uploads_env, "appointments_form.csv")
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "Phone", "Email", "Aadhaar"])
        writer.writerow([sentinel_name, sentinel_phone, sentinel_email, sentinel_aadhaar])

    p = Person(resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ds = Dataset(dataset_id="ds_sentinel", original_filename="appointments_form.csv", source_type="csv", temp_file_path=csv_file)
    db_session.add(ds)
    db_session.flush()

    col_p = Column(dataset_id="ds_sentinel", column_name="Phone", inferred_type="TEXT", category="phone")
    col_e = Column(dataset_id="ds_sentinel", column_name="Email", inferred_type="TEXT", category="email")
    col_a = Column(dataset_id="ds_sentinel", column_name="Aadhaar", inferred_type="TEXT", category="aadhaar")
    col_n = Column(dataset_id="ds_sentinel", column_name="Name", inferred_type="TEXT", category="name")
    db_session.add_all([col_p, col_e, col_a, col_n])
    db_session.flush()

    # Store masked samples and HMACs
    occ_p = Occurrence(person_id=p.id, column_id=col_p.id, row_ref="R2", masked_sample="98765*****", value_hmac=hmac_value("phone", sentinel_phone), origin="rule")
    occ_e = Occurrence(person_id=p.id, column_id=col_e.id, row_ref="R2", masked_sample="s***@example.org", value_hmac=hmac_value("email", sentinel_email), origin="rule")
    occ_a = Occurrence(person_id=p.id, column_id=col_a.id, row_ref="R2", masked_sample="9999****5678", value_hmac=hmac_value("aadhaar", sentinel_aadhaar), origin="rule")
    occ_n = Occurrence(person_id=p.id, column_id=col_n.id, row_ref="R2", masked_sample="R***** S*****", value_hmac=hmac_value("name", sentinel_name), origin="rule")
    db_session.add_all([occ_p, occ_e, occ_a, occ_n])
    db_session.commit()

    plan = compile_plan(db_session, person_id=p.id)
    approve(db_session, plan["plan_id"], plan["plan_hash"])
    execute(db_session, plan["plan_id"])

    # Read receipt JSON and HTML
    plan_row = db_session.query(ErasurePlan).filter(ErasurePlan.id == plan["plan_id"]).first()
    receipt_json_bytes = plan_row.receipt_json.encode("utf-8")
    with open(plan_row.receipt_html_path, "rb") as f:
        receipt_html_bytes = f.read()

    combined_bytes = receipt_json_bytes + receipt_html_bytes

    assert sentinel_phone.encode("utf-8") not in combined_bytes
    assert sentinel_email.encode("utf-8") not in combined_bytes
    assert sentinel_aadhaar.encode("utf-8") not in combined_bytes
    assert sentinel_name.encode("utf-8") not in combined_bytes


def test_ledger_records_all_four_events_and_verifies(db_session: Session, test_uploads_env: str):
    """Ledger shows the four events and the chain verifies."""
    csv_file = os.path.join(test_uploads_env, "staff.csv")
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "Role"])
        writer.writerow(["Staff Member", "Nurse"])

    p = Person(resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ds = Dataset(dataset_id="ds_ledger_test", original_filename="staff.csv", source_type="csv", temp_file_path=csv_file)
    col = Column(dataset_id="ds_ledger_test", column_name="Name", inferred_type="TEXT", category="name")
    db_session.add_all([ds, col])
    db_session.flush()

    occ = Occurrence(person_id=p.id, column_id=col.id, row_ref="R2", masked_sample="S**** M*****", value_hmac=hmac_value("name", "staff member"), origin="rule")
    db_session.add(occ)
    db_session.commit()

    plan = compile_plan(db_session, person_id=p.id)
    approve(db_session, plan["plan_id"], plan["plan_hash"])
    execute(db_session, plan["plan_id"])

    # Check ledger events
    events = db_session.query(LedgerEvent).all()
    event_types = [e.type for e in events]

    assert "erasure_plan" in event_types
    assert "erasure_approved" in event_types
    assert "erasure_executed" in event_types
    assert "residual_check" in event_types

    # Verify chain integrity
    v_res = verify_chain(db_session)
    assert v_res["ok"] is True
    assert v_res["reason"] is None


def test_erasure_api_workflow(db_session: Session, app_client: TestClient, test_uploads_env: str):
    """Tests complete REST API workflow for erasure."""
    csv_file = os.path.join(test_uploads_env, "appointments_form.csv")
    with open(csv_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Phone"])
        writer.writerow(["9876543210"])

    p = Person(resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    ds = Dataset(dataset_id="ds_api_test", original_filename="appointments_form.csv", source_type="csv", temp_file_path=csv_file)
    col = Column(dataset_id="ds_api_test", column_name="Phone", inferred_type="TEXT", category="phone")
    db_session.add_all([ds, col])
    db_session.flush()

    occ = Occurrence(person_id=p.id, column_id=col.id, row_ref="R2", masked_sample="98765*****", value_hmac=hmac_value("phone", "9876543210"), origin="rule")
    db_session.add(occ)
    db_session.commit()

    # 1. POST /api/erasure/plan
    plan_resp = app_client.post("/api/erasure/plan", json={"person_id": p.id})
    assert plan_resp.status_code == 201
    plan_data = plan_resp.json()
    plan_id = plan_data["plan_id"]
    plan_hash = plan_data["plan_hash"]

    # 2. POST /api/erasure/{id}/approve
    appr_resp = app_client.post(f"/api/erasure/{plan_id}/approve", json={"confirm_hash": plan_hash})
    assert appr_resp.status_code == 200
    assert appr_resp.json()["status"] == "approved"

    # 3. POST /api/erasure/{id}/execute
    exec_resp = app_client.post(f"/api/erasure/{plan_id}/execute")
    assert exec_resp.status_code == 200
    exec_data = exec_resp.json()
    assert "receipt_id" in exec_data

    # 4. GET /api/erasure/{id}/receipt
    rcpt_resp = app_client.get(f"/api/erasure/{plan_id}/receipt")
    assert rcpt_resp.status_code == 200
    rcpt_data = rcpt_resp.json()
    assert rcpt_data["plan_id"] == plan_id
    assert rcpt_data["compliance_statement"] == "No issue found by Kavach's checks"

    # 5. GET /api/erasure/{id}/receipt.html
    html_resp = app_client.get(f"/api/erasure/{plan_id}/receipt.html")
    assert html_resp.status_code == 200
    assert "text/html" in html_resp.headers["content-type"]
    assert "DPDP Erasure Compliance Receipt" in html_resp.text
    assert "What We Did NOT Touch" in html_resp.text
