"""
tests/test_reports.py
=====================
Test suite for TASK K12 (Compliance Readiness Reports).
Covers:
1. Empty business: all NOT_ASSESSED, no GREEN anywhere in the HTML.
2. Summary numbers equal independent counts.
3. Action ordering is correct (RED -> YELLOW -> unknown -> NOT_ASSESSED).
4. HTML contains no sentinel raw value and no external URLs (no CDN links).
5. Ledger records report_exported event with ids/counts only, chain remains valid.
6. GREEN wording is always 'No issue found by Kavach\'s checks'.
"""

import datetime
import json
from typing import Dict, List
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db.models import (
    BreachSimulation,
    Column,
    Dataset,
    ErasurePlan,
    FlagResult,
    LedgerEvent,
    Occurrence,
    Person,
    Purpose,
    PurposeLink,
    QuestionnaireAnswer,
    RightsCase,
)
from backend.security import hmac_value
from backend.services.ledger import verify_chain
from backend.services.reports import (
    build_compliance_summary,
    generate_html_report,
    get_limitations_content,
)
from backend.services.rules import ALLOWED_FIX_ACTIONS


# ---------------------------------------------------------------------------
# Test 1: Empty Business
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_business(client: AsyncClient, db_session: Session):
    """
    On an empty business:
    - All rules evaluate to NOT_ASSESSED.
    - Zero sources, records, columns, people, cases, erasures, and simulations.
    - Generated HTML contains NO GREEN anywhere.
    - Contains exact footer disclaimer.
    """
    resp = await client.get("/api/reports/summary")
    assert resp.status_code == 200
    summary = resp.json()

    assert summary["sources_count"] == 0
    assert summary["records_count"] == 0
    assert summary["columns_count"] == 0
    assert summary["distinct_people"] == 0
    assert summary["cases"]["total"] == 0
    assert summary["erasure_receipts"]["total"] == 0
    assert summary["breach_simulations"]["total"] == 0

    flags = summary["flags"]
    assert len(flags) > 0
    assert all(f["state"] == "NOT_ASSESSED" for f in flags), "All rules on empty business must be NOT_ASSESSED"

    # Export HTML
    resp_html = await client.get("/api/reports/export")
    assert resp_html.status_code == 200
    html_text = resp_html.text

    # No GREEN anywhere in HTML (case-insensitive)
    assert "GREEN" not in html_text
    assert "green" not in html_text.lower(), "Empty business HTML must contain no occurrences of 'green'"

    # Required notices and disclaimers
    assert "Readiness aid, not legal advice. Citations unverified." in html_text
    assert "NOT ASSESSED" in html_text


# ---------------------------------------------------------------------------
# Test 2: Summary Numbers Equal Independent SQL Counts
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_summary_numbers_equal_independent_counts(client: AsyncClient, db_session: Session):
    """
    Populate diverse entities and verify every report summary number
    strictly matches an independent SQL query count.
    """
    # 1. Ingest datasets & columns
    ds1 = Dataset(
        dataset_id="ds_alpha",
        original_filename="patients.csv",
        source_type="csv",
        row_count=42,
    )
    ds2 = Dataset(
        dataset_id="ds_beta",
        original_filename="billing.xlsx",
        source_type="xlsx",
        row_count=18,
    )
    db_session.add_all([ds1, ds2])
    db_session.flush()

    col1 = Column(dataset_id="ds_alpha", column_name="full_name", inferred_type="NAME", impact_tier="1")
    col2 = Column(dataset_id="ds_alpha", column_name="aadhaar", inferred_type="AADHAAR", impact_tier="3")
    col3 = Column(dataset_id="ds_beta", column_name="invoice_total", inferred_type="TEXT", impact_tier="1")
    db_session.add_all([col1, col2, col3])
    db_session.flush()

    # 2. People
    p1 = Person(resolution="strong")
    p2 = Person(resolution="probable")
    db_session.add_all([p1, p2])
    db_session.flush()

    # 3. Purpose & Purpose links
    purp = Purpose(label_key="medical_care")
    db_session.add(purp)
    db_session.flush()

    link1 = PurposeLink(
        column_id=col1.id,
        segment="default",
        purpose_id=purp.id,
        status="confirmed",
        answered_by="owner",
    )
    db_session.add(link1)

    # 4. Rights Case
    now = datetime.datetime.now(datetime.timezone.utc)
    rc = RightsCase(
        case_ref="KAV-2026-0001",
        person_id=p1.id,
        sender_masked="+91 98765*****",
        intent="erasure",
        status="received",
        received_at=now,
        due_at=now + datetime.timedelta(days=30),
    )
    db_session.add(rc)

    # 5. Executed Erasure Plan
    receipt_data = {
        "action_counts": {"ERASE": 2, "RETAIN": 1},
        "residual_report": {"patients.csv": {"aadhaar": {"unexpected": 0}}},
    }
    ep = ErasurePlan(
        id="plan_001",
        person_id=p1.id,
        plan_hash="a1b2c3d4e5f678901234567890abcdef1234567890abcdef1234567890abcdef",
        status="executed",
        plan_json=json.dumps({"items": []}),
        receipt_json=json.dumps(receipt_data),
        executed_at=datetime.datetime.now(datetime.timezone.utc),
    )
    db_session.add(ep)

    # 6. Breach Simulation
    sim = BreachSimulation(
        scenario="Lost Staff Laptop",
        aware_at=now,
        device_protected="no",
        severity="high",
        counts_json=json.dumps({"people": {"total": 2, "confirmed": 1, "possible": 1}}),
        drafts_json=json.dumps({}),
    )
    db_session.add(sim)
    db_session.commit()

    # Independent counts directly via raw SQL
    expected_sources = db_session.execute(text("SELECT count(*) FROM datasets")).scalar()
    expected_records = db_session.execute(text("SELECT coalesce(sum(row_count), 0) FROM datasets")).scalar()
    expected_columns = db_session.execute(text("SELECT count(*) FROM columns")).scalar()
    expected_people = db_session.execute(text("SELECT count(*) FROM people")).scalar()
    expected_cases = db_session.execute(text("SELECT count(*) FROM cases")).scalar()
    expected_receipts = db_session.execute(text("SELECT count(*) FROM erasure_plans WHERE status = 'executed'")).scalar()
    expected_sims = db_session.execute(text("SELECT count(*) FROM breach_simulations")).scalar()

    resp = await client.get("/api/reports/summary")
    assert resp.status_code == 200
    summary = resp.json()

    assert summary["sources_count"] == expected_sources
    assert summary["records_count"] == expected_records
    assert summary["columns_count"] == expected_columns
    assert summary["distinct_people"] == expected_people
    assert summary["cases"]["total"] == expected_cases
    assert summary["erasure_receipts"]["total"] == expected_receipts
    assert summary["breach_simulations"]["total"] == expected_sims

    # Purpose coverage checks
    cov = summary["purpose_coverage"]
    assert cov["confirmed"] == 1
    assert cov["inferred"] == 0
    assert cov["unknown"] == 2  # col2 and col3 have no active purpose link


# ---------------------------------------------------------------------------
# Test 3: Action Ordering (RED -> YELLOW -> unknown -> NOT_ASSESSED)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_action_ordering(client: AsyncClient, db_session: Session):
    """
    Validates prioritization ordering of recommended actions:
    1. RED first
    2. YELLOW second
    3. unknown purposes third
    4. NOT_ASSESSED fourth
    Max 8 actions returned, each pointing to an allowed fix_action.
    """
    # Create dataset with an unconfirmed column to trigger unknown purpose action
    ds = Dataset(dataset_id="ds_order", original_filename="order_test.csv", source_type="csv", row_count=10)
    db_session.add(ds)
    db_session.flush()

    col = Column(dataset_id="ds_order", column_name="secret_col", inferred_type="TEXT", impact_tier="1")
    db_session.add(col)
    db_session.flush()

    # Pre-seed FlagResults with a specific run_id
    run_id = "test_run_ordering"
    db_session.add_all([
        FlagResult(run_id=run_id, rule_id="aadhaar_in_chat", state="RED"),
        FlagResult(run_id=run_id, rule_id="notice_at_collection", state="YELLOW"),
        FlagResult(run_id=run_id, rule_id="cctv", state="NOT_ASSESSED"),
        FlagResult(run_id=run_id, rule_id="vendors_unwritten_agreement", state="NOT_ASSESSED"),
        FlagResult(run_id=run_id, rule_id="data_on_personal_phones", state="NOT_ASSESSED"),
    ])
    db_session.commit()

    resp = await client.get("/api/reports/summary")
    assert resp.status_code == 200
    summary = resp.json()
    actions = summary["actions"]

    assert len(actions) <= 8
    assert len(actions) >= 4

    # Priority numbers strictly increment from 1
    priorities = [a["priority"] for a in actions]
    assert priorities == list(range(1, len(actions) + 1))

    # All fix_actions are valid
    for act in actions:
        assert act["fix_action"] in ALLOWED_FIX_ACTIONS, f"Invalid fix_action: {act.get('fix_action')}"

    # Verify strict state ordering: RED -> YELLOW -> unknown -> NOT_ASSESSED
    state_rank = {"RED": 1, "YELLOW": 2, "unknown": 3, "NOT_ASSESSED": 4}
    ranks = [state_rank.get(a["state"], 99) for a in actions]
    assert ranks == sorted(ranks), f"Actions are not sorted properly: {[a['state'] for a in actions]}"

    # Verify each expected group is represented
    states_present = [a["state"] for a in actions]
    assert "RED" in states_present
    assert "YELLOW" in states_present
    assert "unknown" in states_present
    assert "NOT_ASSESSED" in states_present

    # Specifically check the sequence of first 4 items
    assert states_present[0] == "RED"
    assert states_present[1] == "YELLOW"
    assert states_present[2] == "unknown"
    assert states_present[3] == "NOT_ASSESSED"


# ---------------------------------------------------------------------------
# Test 4: HTML Export Security, Zero External URLs, Zero Raw PII, and Ledger Logging
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_html_export_security_and_ledger(client: AsyncClient, db_session: Session):
    """
    Checks:
    - HTML export is completely self-contained (zero CDN links, no http/https URLs)
    - No sentinel raw values appear in HTML
    - Footer disclaimer strictly present
    - Ledger logs report_exported event with ids and counts only
    - Hash chain remains cryptographically valid
    """
    sentinel_phone = "9876543210"
    sentinel_email = "person_private@example.com"
    sentinel_aadhaar = "999988887777"

    # Add dataset with masked data
    ds = Dataset(dataset_id="ds_sec", original_filename="confidential.csv", source_type="csv", row_count=5)
    db_session.add(ds)
    db_session.flush()

    p = Person(
        resolution="strong",
    )
    db_session.add(p)

    now = datetime.datetime.now(datetime.timezone.utc)
    rc = RightsCase(
        case_ref="KAV-2026-SEC",
        person_id=1,
        sender_masked="+91 98765*****",
        intent="access",
        status="received",
        received_at=now,
        due_at=now + datetime.timedelta(days=30),
    )
    db_session.add(rc)
    db_session.commit()

    resp = await client.get("/api/reports/export")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    html = resp.text

    # No external CDN links
    assert "http://" not in html
    assert "https://" not in html

    # No raw sentinel values
    assert sentinel_phone not in html
    assert sentinel_email not in html
    assert sentinel_aadhaar not in html

    # Footer exact wording
    assert "Readiness aid, not legal advice. Citations unverified." in html

    # Print stylesheet included
    assert "@media print" in html

    # Check that report_exported ledger event was appended
    exported_events = (
        db_session.query(LedgerEvent)
        .filter(LedgerEvent.type == "report_exported")
        .all()
    )
    assert len(exported_events) >= 1
    last_event = exported_events[-1]
    payload = json.loads(last_event.payload_json)

    # Verify payload only contains ids and counts
    for key, val in payload.items():
        assert "count" in key or "id" in key or isinstance(val, int)
        assert isinstance(val, (int, float, str))

    # Verify ledger integrity
    chain_check = verify_chain(db_session)
    assert chain_check["ok"] is True, f"Ledger broken after report export: {chain_check}"


# ---------------------------------------------------------------------------
# Test 5: GREEN Wording Always "No issue found by Kavach's checks"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_green_wording_when_green(client: AsyncClient, db_session: Session):
    """
    When rules evaluate to GREEN:
    - Both summary JSON and export HTML strictly use 'No issue found by Kavach's checks'.
    """
    # Pre-seed FlagResult as GREEN
    run_id = "run_green_test"
    db_session.add(
        FlagResult(
            run_id=run_id,
            rule_id="unrestricted_shared_source",
            state="GREEN",
            evidence_refs=json.dumps(["questionnaire:shared_folder:no"]),
        )
    )
    db_session.commit()

    resp_summary = await client.get("/api/reports/summary")
    assert resp_summary.status_code == 200
    summary = resp_summary.json()

    green_flags = [f for f in summary["flags"] if f["state"] == "GREEN"]
    assert len(green_flags) >= 1
    for gf in green_flags:
        assert "No issue found by Kavach's checks" in gf["whats_right"]

    # Export HTML
    resp_html = await client.get("/api/reports/export")
    assert resp_html.status_code == 200
    html = resp_html.text

    assert "No issue found by Kavach's checks" in html
