from datetime import datetime, timezone
import pytest
from sqlalchemy.orm import Session
from backend.db.models import (
    Base,
    Dataset,
    Column,
    Person,
    Occurrence,
    Purpose,
    PurposeLink,
    FlagResult,
    LedgerEvent,
    BusinessState,
)


def test_new_tables_registered_in_metadata():
    expected_tables = {
        "datasets",
        "columns",
        "etl_issues",
        "identifier_findings",
        "version_diffs",
        "audit_logs",
        "cross_source_matches",
        "privacy_requests",
        "incidents",
        # New Part C tables:
        "people",
        "occurrences",
        "purposes",
        "purpose_links",
        "flag_results",
        "ledger_events",
        "business_state",
    }
    table_names = set(Base.metadata.tables.keys())
    for t in expected_tables:
        assert t in table_names, f"Table {t} missing from Base metadata"


def test_columns_table_nullable_fields(db_session: Session):
    ds = Dataset(
        dataset_id="ds_test_v2_cols",
        original_filename="test.csv",
        source_type="csv",
        status="PENDING",
    )
    db_session.add(ds)
    db_session.flush()

    col = Column(
        dataset_id="ds_test_v2_cols",
        column_name="patient_age",
        inferred_type="INTEGER",
        locator="sheet1.colC",
        category="DEMOGRAPHIC",
        impact_tier="TIER_2",
    )
    db_session.add(col)
    db_session.commit()

    saved = db_session.query(Column).filter_by(dataset_id="ds_test_v2_cols").first()
    assert saved.locator == "sheet1.colC"
    assert saved.category == "DEMOGRAPHIC"
    assert saved.impact_tier == "TIER_2"


def test_people_and_occurrences_records(db_session: Session):
    person = Person(resolution="RESOLVED", confidence=0.95)
    db_session.add(person)
    db_session.flush()

    occ = Occurrence(
        person_id=person.id,
        column_id=None,
        row_ref="row_12",
        masked_sample="XXXXXX4321",
        value_hmac="a" * 64,
        origin="rule",
        ocr_conf=0.99,
    )
    db_session.add(occ)
    db_session.commit()

    saved_occ = db_session.query(Occurrence).filter_by(person_id=person.id).first()
    assert saved_occ is not None
    assert saved_occ.masked_sample == "XXXXXX4321"
    assert saved_occ.origin == "rule"
    assert saved_occ.person.resolution == "RESOLVED"


def test_purposes_and_purpose_links(db_session: Session):
    ds = Dataset(dataset_id="ds_purpose_test", original_filename="data.csv", source_type="csv")
    db_session.add(ds)
    db_session.flush()

    col = Column(dataset_id="ds_purpose_test", column_name="email", inferred_type="EMAIL")
    db_session.add(col)
    db_session.flush()

    purpose = Purpose(label_key="COMMUNICATION_NOTIFICATIONS")
    db_session.add(purpose)
    db_session.flush()

    link = PurposeLink(
        column_id=col.id,
        segment="patient",
        purpose_id=purpose.id,
        status="confirmed",
        answered_by="compliance_officer",
        answered_at=datetime.now(timezone.utc),
    )
    db_session.add(link)
    db_session.commit()

    saved_link = db_session.query(PurposeLink).filter_by(column_id=col.id).first()
    assert saved_link is not None
    assert saved_link.segment == "patient"
    assert saved_link.status == "confirmed"
    assert saved_link.purpose.label_key == "COMMUNICATION_NOTIFICATIONS"


def test_flag_results_record(db_session: Session):
    flag = FlagResult(
        run_id="run_20261025_001",
        rule_id="RULE_PURPOSE_SPECIFICATION",
        state="GREEN",
        evidence_refs='["col_1", "col_2"]',
    )
    db_session.add(flag)
    db_session.commit()

    saved_flag = db_session.query(FlagResult).filter_by(run_id="run_20261025_001").first()
    assert saved_flag.state == "GREEN"
    assert saved_flag.rule_id == "RULE_PURPOSE_SPECIFICATION"


def test_ledger_events_record(db_session: Session):
    event = LedgerEvent(
        seq=1,
        event_type="DATASET_INGESTED",
        payload_json='{"dataset_id": "ds_001"}',
        prev_hash="0" * 64,
        hash="f" * 64,
    )
    db_session.add(event)
    db_session.commit()

    saved_event = db_session.query(LedgerEvent).filter_by(seq=1).first()
    assert saved_event.event_type == "DATASET_INGESTED"
    assert saved_event.prev_hash == "0" * 64


def test_business_state_record(db_session: Session):
    now = datetime.now(timezone.utc)
    state = BusinessState(last_activity=now)
    db_session.add(state)
    db_session.commit()

    saved_state = db_session.query(BusinessState).first()
    assert saved_state is not None
    assert saved_state.last_activity is not None
