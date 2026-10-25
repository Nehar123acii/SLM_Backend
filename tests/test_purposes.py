import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import create_app
from backend.db.models import Dataset, Column, Occurrence, PurposeLink, Purpose
from backend.services.purposes import (
    load_purposes_vocabulary,
    load_clinic_preset,
    generate_questions,
    record_answer,
    ensure_purposes_seeded,
)


@pytest.fixture
def app_client(db_session: Session):
    app = create_app()
    from backend.api.deps import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_purposes_vocabulary_and_clinic_preset_structure():
    """Verify vocabulary has all required purposes and preset contains suggested defaults."""
    vocab = load_purposes_vocabulary()
    vocab_ids = {p["id"] for p in vocab}
    required = {
        "appointment_booking",
        "billing_payment",
        "tax_records",
        "medical_care",
        "employment_payroll",
        "marketing_offers",
        "legal_obligation",
        "security_fraud",
        "other",
    }
    assert required.issubset(vocab_ids), f"Missing required purposes: {required - vocab_ids}"

    preset = load_clinic_preset()
    assert "patient" in preset
    assert "customer" in preset
    assert "staff" in preset
    assert "appointment_booking" in preset["patient"]["phone"]
    assert "billing_payment" in preset["customer"]["phone"]
    assert "employment_payroll" in preset["staff"]["aadhaar"]


def test_preset_alone_never_produces_confirmed_row(db_session: Session):
    """Verify that loading preset or generating questions never writes confirmed purpose links."""
    ds = Dataset(
        dataset_id="ds_preset_test",
        original_filename="patients_list.xlsx",
        source_type="excel",
        segment="patient",
    )
    col = Column(
        dataset_id="ds_preset_test",
        column_name="mobile",
        inferred_type="string",
        category="phone",
        impact_tier="2",
    )
    db_session.add_all([ds, col])
    db_session.commit()

    # Generate questions (preset is consulted for suggested_default)
    data = generate_questions(db_session)
    assert len(data["questions"]) == 1
    assert data["questions"][0]["suggested_default"] == ["appointment_booking"]

    # Verify database still has ZERO confirmed purpose links
    confirmed_count = db_session.query(PurposeLink).filter(PurposeLink.status == "confirmed").count()
    assert confirmed_count == 0


def test_answering_creates_confirmed_and_unknown_creates_unknown(db_session: Session, app_client: TestClient):
    """Verify answering creates confirmed rows, and 'I don't know' creates status unknown."""
    ds = Dataset(
        dataset_id="ds_ans_test",
        original_filename="billing.csv",
        source_type="csv",
        segment="customer",
    )
    col1 = Column(
        dataset_id="ds_ans_test",
        column_name="contact_number",
        inferred_type="string",
        category="phone",
        impact_tier="2",
    )
    col2 = Column(
        dataset_id="ds_ans_test",
        column_name="remarks",
        inferred_type="string",
        category="name",
        impact_tier="2",
    )
    db_session.add_all([ds, col1, col2])
    db_session.commit()

    # Answer col1 with confirmed purpose
    res1 = app_client.post(
        "/answers",
        json={
            "column_id": col1.id,
            "segment": "customer",
            "purpose_ids": ["billing_payment"],
            "answered_by": "clinic_admin",
        },
    )
    assert res1.status_code == 201

    link1 = db_session.query(PurposeLink).filter(PurposeLink.column_id == col1.id).first()
    assert link1 is not None
    assert link1.status == "confirmed"
    assert link1.answered_by == "clinic_admin"
    assert link1.purpose.label_key == "billing_payment"

    # Answer col2 with unknown=true ("I don't know")
    res2 = app_client.post(
        "/answers",
        json={
            "column_id": col2.id,
            "segment": "customer",
            "unknown": True,
            "answered_by": "clinic_admin",
        },
    )
    assert res2.status_code == 201

    link2 = db_session.query(PurposeLink).filter(PurposeLink.column_id == col2.id).first()
    assert link2 is not None
    assert link2.status == "unknown"
    assert link2.purpose_id is None


def test_superseding_keeps_old_row_and_links_it_to_new_one(db_session: Session, app_client: TestClient):
    """Verify answering again creates a new row and sets superseded_by on the prior active row."""
    ds = Dataset(
        dataset_id="ds_super_test",
        original_filename="patients.xlsx",
        source_type="excel",
        segment="patient",
    )
    col = Column(
        dataset_id="ds_super_test",
        column_name="email_address",
        inferred_type="string",
        category="email",
        impact_tier="2",
    )
    db_session.add_all([ds, col])
    db_session.commit()

    # 1st Answer: appointment_booking
    res1 = app_client.post(
        "/answers",
        json={
            "column_id": col.id,
            "segment": "patient",
            "purpose_ids": ["appointment_booking"],
            "answered_by": "staff_member_1",
        },
    )
    assert res1.status_code == 201

    first_link = db_session.query(PurposeLink).filter(PurposeLink.column_id == col.id).first()
    assert first_link.superseded_by is None

    # 2nd Answer: superseded by medical_care
    res2 = app_client.post(
        "/answers",
        json={
            "column_id": col.id,
            "segment": "patient",
            "purpose_ids": ["medical_care"],
            "answered_by": "compliance_lead",
        },
    )
    assert res2.status_code == 201

    all_links = (
        db_session.query(PurposeLink)
        .filter(PurposeLink.column_id == col.id)
        .order_by(PurposeLink.id.asc())
        .all()
    )
    assert len(all_links) == 2
    old_row, new_row = all_links[0], all_links[1]

    # Old row is preserved, and its superseded_by points to the new row
    assert old_row.superseded_by == new_row.id
    assert old_row.status == "confirmed"
    assert new_row.superseded_by is None
    assert new_row.purpose.label_key == "medical_care"

    # Verify GET /columns/{id}/purposes returns current answer and full history
    hist_res = app_client.get(f"/columns/{col.id}/purposes")
    assert hist_res.status_code == 200
    data = hist_res.json()
    assert len(data["current"]) == 1
    assert data["current"][0]["purpose_key"] == "medical_care"
    assert len(data["history"]) == 2
    assert data["history"][0]["superseded_by"] == new_row.id


def test_unknown_purpose_id_rejected_with_4xx(db_session: Session, app_client: TestClient):
    """Verify submitting an unknown purpose ID returns 400 Bad Request and creates no rows."""
    ds = Dataset(
        dataset_id="ds_reject_test",
        original_filename="staff.csv",
        source_type="csv",
        segment="staff",
    )
    col = Column(
        dataset_id="ds_reject_test",
        column_name="pan_number",
        inferred_type="string",
        category="pan",
        impact_tier="3",
    )
    db_session.add_all([ds, col])
    db_session.commit()

    res = app_client.post(
        "/answers",
        json={
            "column_id": col.id,
            "segment": "staff",
            "purpose_ids": ["not_a_valid_purpose_code_xyz"],
        },
    )
    assert 400 <= res.status_code < 500
    assert "Unknown purpose id" in res.text

    # No purpose link should exist
    assert db_session.query(PurposeLink).filter(PurposeLink.column_id == col.id).count() == 0


def test_questions_ordered_by_impact_tier_then_count(db_session: Session):
    """Verify questions are ordered by impact_tier descending, then number of occurrences descending."""
    ds = Dataset(
        dataset_id="ds_order_test",
        original_filename="multi_patient.csv",
        source_type="csv",
        segment="patient",
    )
    db_session.add(ds)
    db_session.flush()

    col_tier3_low = Column(dataset_id=ds.dataset_id, column_name="c_t3_low", inferred_type="string", category="aadhaar", impact_tier="3")
    col_tier3_high = Column(dataset_id=ds.dataset_id, column_name="c_t3_high", inferred_type="string", category="pan", impact_tier="3")
    col_tier2_high = Column(dataset_id=ds.dataset_id, column_name="c_t2_high", inferred_type="string", category="phone", impact_tier="2")
    col_tier2_low = Column(dataset_id=ds.dataset_id, column_name="c_t2_low", inferred_type="string", category="address", impact_tier="2")

    db_session.add_all([col_tier3_low, col_tier3_high, col_tier2_high, col_tier2_low])
    db_session.flush()

    # Seed occurrences
    # col_tier3_high: 10 occurrences
    for i in range(10):
        db_session.add(Occurrence(column_id=col_tier3_high.id, masked_sample="sample", value_hmac="hmac", origin="rule"))
    # col_tier3_low: 2 occurrences
    for i in range(2):
        db_session.add(Occurrence(column_id=col_tier3_low.id, masked_sample="sample", value_hmac="hmac", origin="rule"))
    # col_tier2_high: 25 occurrences
    for i in range(25):
        db_session.add(Occurrence(column_id=col_tier2_high.id, masked_sample="sample", value_hmac="hmac", origin="rule"))
    # col_tier2_low: 1 occurrence
    db_session.add(Occurrence(column_id=col_tier2_low.id, masked_sample="sample", value_hmac="hmac", origin="rule"))

    db_session.commit()

    q_data = generate_questions(db_session)
    questions = q_data["questions"]

    # Filter to only the test columns
    test_q_ids = [q["column_id"] for q in questions if q["column_id"] in {col_tier3_low.id, col_tier3_high.id, col_tier2_high.id, col_tier2_low.id}]
    
    expected_order = [
        col_tier3_high.id,  # Tier 3, 10 occurrences
        col_tier3_low.id,   # Tier 3, 2 occurrences
        col_tier2_high.id,  # Tier 2, 25 occurrences
        col_tier2_low.id,   # Tier 2, 1 occurrence
    ]
    assert test_q_ids == expected_order


def test_answered_column_no_longer_appears_unknown_still_open(db_session: Session, app_client: TestClient):
    """Verify an answered column disappears from GET /questions, while answering 'unknown' keeps it open."""
    ds = Dataset(
        dataset_id="ds_queue_test",
        original_filename="appointments_form.csv",
        source_type="csv",
        segment="patient",
    )
    col_a = Column(dataset_id="ds_queue_test", column_name="patient_name", inferred_type="string", category="name", impact_tier="2")
    col_b = Column(dataset_id="ds_queue_test", column_name="patient_phone", inferred_type="string", category="phone", impact_tier="2")
    db_session.add_all([ds, col_a, col_b])
    db_session.commit()

    # Initial open questions
    res0 = app_client.get("/questions")
    assert res0.status_code == 200
    q_col_ids = [q["column_id"] for q in res0.json()["questions"]]
    assert col_a.id in q_col_ids
    assert col_b.id in q_col_ids

    # 1. Answer col_a with confirmed purpose
    app_client.post(
        "/answers",
        json={
            "column_id": col_a.id,
            "segment": "patient",
            "purpose_ids": ["appointment_booking"],
        },
    )

    # col_a must disappear from open questions
    res1 = app_client.get("/questions")
    q_col_ids1 = [q["column_id"] for q in res1.json()["questions"]]
    assert col_a.id not in q_col_ids1
    assert col_b.id in q_col_ids1

    # 2. Answer col_b with unknown=true
    app_client.post(
        "/answers",
        json={
            "column_id": col_b.id,
            "segment": "patient",
            "unknown": True,
        },
    )

    # col_b must STILL appear in open questions
    res2 = app_client.get("/questions")
    q_col_ids2 = [q["column_id"] for q in res2.json()["questions"]]
    assert col_a.id not in q_col_ids2
    assert col_b.id in q_col_ids2


def test_patch_dataset_segment(db_session: Session, app_client: TestClient):
    """Verify owner can change dataset segment via PATCH /datasets/{id}/segment."""
    ds = Dataset(
        dataset_id="ds_patch_test",
        original_filename="generic_data.csv",
        source_type="csv",
        segment=None,
    )
    db_session.add(ds)
    db_session.commit()

    # Update to patient
    res = app_client.patch(f"/datasets/{ds.id}/segment", json={"segment": "patient"})
    assert res.status_code == 200
    assert res.json()["segment"] == "patient"

    db_session.refresh(ds)
    assert ds.segment == "patient"

    # Reject invalid segment
    res_bad = app_client.patch(f"/datasets/{ds.id}/segment", json={"segment": "unknown_segment"})
    assert res_bad.status_code == 400
