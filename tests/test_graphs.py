"""
tests/test_graphs.py
====================
Test suite for DPDP Graph Data Endpoints (TASK K11).
Covers:
1. Empty database returns clean empty structures (not errors)
2. Every heatmap number matches an independent SQL count written in the test
3. Purpose-coverage counts (confirmed, inferred, unknown) match independent SQL counts
4. Source-purpose Cytoscape graph nodes and edges match independent SQL counts
5. Rows click-through returns masked values only with paging; zero raw sentinel values in body
6. Blast radius per source reuses K9 engine
"""

from typing import Dict, List, Set
import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db.models import Column, Dataset, Occurrence, Person, Purpose, PurposeLink
from backend.security import hmac_value
from backend.services.breach import blast_radius


# ---------------------------------------------------------------------------
# Test 1: Empty database returns empty structures (no errors)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_database_returns_empty_structures(client: AsyncClient, db_session: Session):
    # 1. Heatmap
    res_heatmap = await client.get("/api/graphs/heatmap")
    assert res_heatmap.status_code == 200
    hm = res_heatmap.json()
    assert hm["sources"] == []
    assert hm["categories"] == []
    assert hm["cells"] == []
    assert hm["matrix"] == []
    assert "Impact tier is Kavach's own 'impact if leaked' tier" in hm["notes"]

    # 2. Purpose coverage
    res_pc = await client.get("/api/graphs/purpose-coverage")
    assert res_pc.status_code == 200
    assert res_pc.json() == []

    # 3. Source-purpose graph
    res_sp = await client.get("/api/graphs/source-purpose")
    assert res_sp.status_code == 200
    sp = res_sp.json()
    assert sp["nodes"] == []
    assert sp["edges"] == []
    assert sp["elements"]["nodes"] == []
    assert sp["elements"]["edges"] == []

    # 4. Blast radius
    res_br = await client.get("/api/graphs/blast-radius")
    assert res_br.status_code == 200
    assert res_br.json() == []

    # 5. Rows on non-existent column
    res_rows = await client.get("/api/graphs/rows?column_id=9999")
    assert res_rows.status_code == 404


# ---------------------------------------------------------------------------
# Test 2: Every heatmap number equals an independent SQL count
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_heatmap_counts_match_independent_sql(client: AsyncClient, db_session: Session):
    ds1 = Dataset(dataset_id="ds_hm_01", original_filename="patients.csv", source_type="csv", row_count=10)
    ds2 = Dataset(dataset_id="ds_hm_02", original_filename="billing.xlsx", source_type="excel", row_count=8)
    db_session.add_all([ds1, ds2])
    db_session.flush()

    col1_phone = Column(dataset_id=ds1.dataset_id, column_name="phone", inferred_type="TEXT", category="phone", impact_tier="2")
    col1_aadhaar = Column(dataset_id=ds1.dataset_id, column_name="aadhaar", inferred_type="TEXT", category="aadhaar", impact_tier="3")
    col1_name = Column(dataset_id=ds1.dataset_id, column_name="name", inferred_type="TEXT", category="name", impact_tier="2")

    col2_phone = Column(dataset_id=ds2.dataset_id, column_name="phone", inferred_type="TEXT", category="phone", impact_tier="2")
    col2_email = Column(dataset_id=ds2.dataset_id, column_name="email", inferred_type="TEXT", category="email", impact_tier="2")
    db_session.add_all([col1_phone, col1_aadhaar, col1_name, col2_phone, col2_email])
    db_session.flush()

    p1 = Person(id=1, resolution="strong", confidence=1.0)
    p2 = Person(id=2, resolution="strong", confidence=1.0)
    p3 = Person(id=3, resolution="probable", confidence=0.6)
    db_session.add_all([p1, p2, p3])
    db_session.flush()

    # ds1 occurrences
    occ_1 = Occurrence(column_id=col1_phone.id, person_id=p1.id, value_hmac="hmac_1", masked_sample="+91 98****01")
    occ_2 = Occurrence(column_id=col1_phone.id, person_id=p2.id, value_hmac="hmac_2", masked_sample="+91 98****02")
    occ_3 = Occurrence(column_id=col1_aadhaar.id, person_id=p1.id, value_hmac="hmac_3", masked_sample="9988****11")
    occ_4 = Occurrence(column_id=col1_name.id, person_id=p1.id, value_hmac="hmac_4", masked_sample="P*** O**")
    occ_5 = Occurrence(column_id=col1_name.id, person_id=p2.id, value_hmac="hmac_5", masked_sample="P*** T**")
    occ_6 = Occurrence(column_id=col1_name.id, person_id=p3.id, value_hmac="hmac_6", masked_sample="P*** T**")

    # ds2 occurrences
    occ_7 = Occurrence(column_id=col2_phone.id, person_id=p2.id, value_hmac="hmac_7", masked_sample="+91 98****02")
    occ_8 = Occurrence(column_id=col2_phone.id, person_id=p3.id, value_hmac="hmac_8", masked_sample="+91 98****03")
    occ_9 = Occurrence(column_id=col2_email.id, person_id=p3.id, value_hmac="hmac_9", masked_sample="p***@test.com")

    db_session.add_all([occ_1, occ_2, occ_3, occ_4, occ_5, occ_6, occ_7, occ_8, occ_9])
    db_session.commit()

    res = await client.get("/api/graphs/heatmap")
    assert res.status_code == 200
    data = res.json()

    assert "Impact tier is Kavach's own 'impact if leaked' tier" in data["notes"]

    # Independent SQL verification for every single cell
    for cell in data["cells"]:
        ds_id = cell["source_id"]
        cat = cell["category"]

        # 1. Independent SQL query to count distinct people
        sql_people = text("""
            SELECT COUNT(DISTINCT o.person_id)
            FROM occurrences o
            JOIN columns c ON o.column_id = c.id
            WHERE c.dataset_id = :ds_id
              AND c.category = :cat
              AND o.person_id IS NOT NULL
        """)
        indep_people_count = db_session.execute(sql_people, {"ds_id": ds_id, "cat": cat}).scalar()

        # 2. Independent SQL query to count total occurrences
        sql_occs = text("""
            SELECT COUNT(o.id)
            FROM occurrences o
            JOIN columns c ON o.column_id = c.id
            WHERE c.dataset_id = :ds_id
              AND c.category = :cat
        """)
        indep_occ_count = db_session.execute(sql_occs, {"ds_id": ds_id, "cat": cat}).scalar()

        assert cell["people_count"] == indep_people_count, f"Mismatch for {ds_id} x {cat}"
        assert cell["occurrence_count"] == indep_occ_count, f"Occurrence mismatch for {ds_id} x {cat}"

        # Verify impact tier
        if cat == "aadhaar":
            assert cell["impact_tier"] == "3"
        elif cat in ("phone", "email", "name"):
            assert cell["impact_tier"] == "2"


# ---------------------------------------------------------------------------
# Test 3: Purpose-coverage counts equal independent SQL counts
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_purpose_coverage_counts_match_independent_sql(client: AsyncClient, db_session: Session):
    ds = Dataset(dataset_id="ds_cov_01", original_filename="clinic_data.csv", source_type="csv")
    db_session.add(ds)
    db_session.flush()

    c1 = Column(dataset_id=ds.dataset_id, column_name="c_conf", inferred_type="TEXT", category="phone")
    c2 = Column(dataset_id=ds.dataset_id, column_name="c_inf", inferred_type="TEXT", category="email")
    c3 = Column(dataset_id=ds.dataset_id, column_name="c_unk", inferred_type="TEXT", category="pan")
    c4 = Column(dataset_id=ds.dataset_id, column_name="c_none", inferred_type="TEXT", category="name")
    db_session.add_all([c1, c2, c3, c4])
    db_session.flush()

    p1 = Purpose(id=1, label_key="appointment_booking")
    p2 = Purpose(id=2, label_key="billing_payment")
    p3 = Purpose(id=3, label_key="tax_records")
    db_session.add_all([p1, p2, p3])
    db_session.flush()

    # Link 1: confirmed
    pl1 = PurposeLink(column_id=c1.id, segment="patient", purpose_id=p1.id, status="confirmed")
    # Link 2: inferred
    pl2 = PurposeLink(column_id=c2.id, segment="patient", purpose_id=p2.id, status="inferred")
    # Link 3: unknown status
    pl3 = PurposeLink(column_id=c3.id, segment="patient", purpose_id=p3.id, status="unknown")
    # c4 has no PurposeLink (no answer => unknown)
    db_session.add_all([pl1, pl2, pl3])
    db_session.commit()

    res = await client.get("/api/graphs/purpose-coverage")
    assert res.status_code == 200
    data = res.json()

    # Independent SQL counts
    sql_total = text("SELECT COUNT(*) FROM columns WHERE dataset_id = :ds_id")
    indep_total = db_session.execute(sql_total, {"ds_id": ds.dataset_id}).scalar()

    sql_confirmed = text("""
        SELECT COUNT(*)
        FROM columns c
        JOIN purpose_links pl ON c.id = pl.column_id
        WHERE c.dataset_id = :ds_id
          AND pl.superseded_by IS NULL
          AND pl.purpose_id IS NOT NULL
          AND LOWER(pl.status) = 'confirmed'
    """)
    indep_confirmed = db_session.execute(sql_confirmed, {"ds_id": ds.dataset_id}).scalar()

    sql_inferred = text("""
        SELECT COUNT(*)
        FROM columns c
        JOIN purpose_links pl ON c.id = pl.column_id
        WHERE c.dataset_id = :ds_id
          AND pl.superseded_by IS NULL
          AND pl.purpose_id IS NOT NULL
          AND LOWER(pl.status) = 'inferred'
    """)
    indep_inferred = db_session.execute(sql_inferred, {"ds_id": ds.dataset_id}).scalar()

    indep_unknown = indep_total - (indep_confirmed + indep_inferred)

    matching_ds = [d for d in data if d["source_id"] == ds.dataset_id][0]
    assert matching_ds["total_fields"] == indep_total
    assert matching_ds["confirmed"] == indep_confirmed
    assert matching_ds["inferred"] == indep_inferred
    assert matching_ds["unknown"] == indep_unknown

    assert matching_ds["confirmed"] == 1
    assert matching_ds["inferred"] == 1
    assert matching_ds["unknown"] == 2


# ---------------------------------------------------------------------------
# Test 4: Source-purpose Cytoscape edges match independent SQL
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_source_purpose_cytoscape_edges_match_independent_sql(client: AsyncClient, db_session: Session):
    ds = Dataset(dataset_id="ds_graph_01", original_filename="patients.xlsx", source_type="excel")
    db_session.add(ds)
    db_session.flush()

    c_phone = Column(dataset_id=ds.dataset_id, column_name="contact_no", inferred_type="TEXT", category="phone")
    c_email = Column(dataset_id=ds.dataset_id, column_name="email_addr", inferred_type="TEXT", category="email")
    db_session.add_all([c_phone, c_email])
    db_session.flush()

    purp = Purpose(id=10, label_key="appointment_booking")
    db_session.add(purp)
    db_session.flush()

    pl = PurposeLink(column_id=c_phone.id, segment="patient", purpose_id=purp.id, status="confirmed")
    db_session.add(pl)
    db_session.commit()

    res = await client.get("/api/graphs/source-purpose")
    assert res.status_code == 200
    data = res.json()

    nodes = data["nodes"]
    edges = data["edges"]

    # Independent SQL verification for edges
    # Edge 1: source -> phone
    # Edge 2: source -> email
    # Edge 3: phone -> appointment_booking
    sql_src_cat = text("SELECT DISTINCT dataset_id, category FROM columns WHERE category IS NOT NULL")
    indep_src_cat = db_session.execute(sql_src_cat).fetchall()

    sql_cat_purp = text("""
        SELECT DISTINCT c.category, pl.purpose_id
        FROM columns c
        JOIN purpose_links pl ON c.id = pl.column_id
        WHERE pl.superseded_by IS NULL AND pl.purpose_id IS NOT NULL
    """)
    indep_cat_purp = db_session.execute(sql_cat_purp).fetchall()

    expected_total_edges = len(indep_src_cat) + len(indep_cat_purp)
    assert len(edges) == expected_total_edges

    # Assert Cytoscape format contains valid source and target ids
    node_ids = {n["data"]["id"] for n in nodes}
    for e in edges:
        assert e["data"]["source"] in node_ids
        assert e["data"]["target"] in node_ids

    # Elements structure exists for Cytoscape.js
    assert "elements" in data
    assert len(data["elements"]["nodes"]) == len(nodes)
    assert len(data["elements"]["edges"]) == len(edges)


# ---------------------------------------------------------------------------
# Test 5: Click-through returns masked values only; no sentinels
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rows_clickthrough_masked_only_and_no_sentinels(client: AsyncClient, db_session: Session):
    sentinel_phone = "9876543219"
    sentinel_email = "sentinel_alpha_user99@sentinelcorp.in"
    sentinel_aadhaar = "998877665544"

    ds = Dataset(dataset_id="ds_rows_01", original_filename="secure_records.csv", source_type="csv")
    db_session.add(ds)
    db_session.flush()

    col = Column(dataset_id=ds.dataset_id, column_name="secret_phone", inferred_type="TEXT", category="phone", impact_tier="2")
    db_session.add(col)
    db_session.flush()

    # Create occurrences with format-preserving masked samples and HMACs
    occ1 = Occurrence(column_id=col.id, row_ref="row_1", masked_sample="+91 98****19", value_hmac=hmac_value("phone", sentinel_phone), origin="rule")
    occ2 = Occurrence(column_id=col.id, row_ref="row_2", masked_sample="+91 98****20", value_hmac=hmac_value("phone", "9876543220"), origin="rule")
    occ3 = Occurrence(column_id=col.id, row_ref="row_3", masked_sample="+91 98****21", value_hmac=hmac_value("phone", "9876543221"), origin="rule")
    db_session.add_all([occ1, occ2, occ3])
    db_session.commit()

    # Page 1, size 2
    res = await client.get(f"/api/graphs/rows?column_id={col.id}&page=1&page_size=2")
    assert res.status_code == 200
    data = res.json()

    assert data["column_id"] == col.id
    assert data["total_rows"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 2
    assert len(data["rows"]) == 2

    # Check that sentinel phone does NOT appear anywhere in the response text
    assert sentinel_phone not in res.text
    assert sentinel_email not in res.text
    assert sentinel_aadhaar not in res.text

    # Check fields present
    first_row = data["rows"][0]
    assert first_row["row_ref"] == "row_1"
    assert first_row["masked_sample"] == "+91 98****19"
    assert first_row["origin"] == "rule"

    # Page 2, size 2
    res_p2 = await client.get(f"/api/graphs/rows?column_id={col.id}&page=2&page_size=2")
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert len(data_p2["rows"]) == 1
    assert data_p2["rows"][0]["row_ref"] == "row_3"


# ---------------------------------------------------------------------------
# Test 6: Blast radius per source reuses K9 engine
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_blast_radius_by_source_reuses_k9(client: AsyncClient, db_session: Session):
    ds = Dataset(dataset_id="ds_br_01", original_filename="patients.xlsx", source_type="excel", row_count=5)
    db_session.add(ds)
    db_session.flush()

    col = Column(dataset_id=ds.dataset_id, column_name="aadhaar", inferred_type="TEXT", category="aadhaar", impact_tier="3")
    db_session.add(col)
    db_session.flush()

    p = Person(id=100, resolution="strong", confidence=1.0)
    db_session.add(p)
    db_session.flush()

    occ = Occurrence(column_id=col.id, person_id=p.id, value_hmac="hmac_br_1", masked_sample="9988****12")
    db_session.add(occ)
    db_session.commit()

    # Call endpoint
    res = await client.get("/api/graphs/blast-radius")
    assert res.status_code == 200
    data = res.json()

    # Compare against direct call to K9 blast_radius function
    k9_blast = blast_radius(db_session, [ds.dataset_id])

    matching = [d for d in data if d["source_id"] == ds.dataset_id][0]
    assert matching["confirmed_people"] == k9_blast["confirmed_people"]
    assert matching["possible_people"] == k9_blast["possible_people"]
    assert matching["high_impact_categories"] == k9_blast["high_impact_categories"]
    assert matching["minors_involved"] == k9_blast["minors_involved"]
    assert "If this leaks:" in matching["leak_summary"]
    assert "AADHAAR" in matching["leak_summary"]
