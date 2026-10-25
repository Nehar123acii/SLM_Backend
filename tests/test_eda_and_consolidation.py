import os
import pytest
from httpx import AsyncClient

SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_data")


@pytest.mark.asyncio
async def test_complete_five_category_eda(client: AsyncClient):
    """
    Tests complete 5-category EDA report calculation and retrieval:
    1. Dataset Overview
    2. Completeness and Duplication
    3. Numeric Distributions
    4. Categorical Distributions
    5. Time, Text and Data Quality
    """
    csv_path = os.path.join(SAMPLE_DATA_DIR, "synthetic_customers.csv")
    with open(csv_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("synthetic_customers.csv", file_bytes, "text/csv")}
    upload_res = await client.post("/api/v1/inventory/upload", files=files)
    assert upload_res.status_code == 200
    dataset_id = upload_res.json()["dataset_id"]

    # Retrieve EDA summary endpoint
    eda_res = await client.get(f"/api/v1/inventory/datasets/{dataset_id}/eda-summary")
    assert eda_res.status_code == 200, eda_res.text
    eda = eda_res.json()

    # 1. Dataset Overview
    assert "overview" in eda
    ov = eda["overview"]
    assert ov["row_count"] == 10
    assert ov["column_count"] == 8
    assert ov["source_type"] == "csv"
    assert "reconciliation_summary" in ov
    assert ov["reconciliation_summary"]["accepted_rows"] == 10

    # 2. Completeness and Duplication
    assert "completeness_and_duplication" in eda
    cd = eda["completeness_and_duplication"]
    assert "total_missing_cells" in cd
    assert "overall_missingness_percentage" in cd
    assert "missing_counts_per_column" in cd
    assert "customer_name" in cd["missing_counts_per_column"]

    # 3. Numeric Distributions (e.g. purchase_amount_inr)
    assert "numeric_distributions" in eda
    nd = eda["numeric_distributions"]
    assert "purchase_amount_inr" in nd
    amt_dist = nd["purchase_amount_inr"]
    assert "min" in amt_dist
    assert "max" in amt_dist
    assert "mean" in amt_dist
    assert "median" in amt_dist
    assert "std_dev" in amt_dist
    assert "histogram" in amt_dist
    assert len(amt_dist["histogram"]) <= 10

    # 4. Categorical Distributions
    assert "categorical_distributions" in eda
    cat_d = eda["categorical_distributions"]
    assert "city" in cat_d
    assert "distinct_value_count" in cat_d["city"]
    assert "top_categories" in cat_d["city"]
    # Verify sensitive data redaction flag for identity / government ID fields
    assert "pan_number" in cat_d
    assert cat_d["pan_number"]["is_redacted"] is True
    for top_cat in cat_d["pan_number"]["top_categories"]:
        assert top_cat["value"] == "[REDACTED_SENSITIVE_VALUE]"

    # 5. Time, Text and Data Quality
    assert "time_text_and_quality" in eda
    tq = eda["time_text_and_quality"]
    assert "text_length_summary" in tq
    assert "invalid_format_counts" in tq
    assert "etl_issues_breakdown" in tq


@pytest.mark.asyncio
async def test_consolidated_inventory_and_export(client: AsyncClient):
    """
    Tests consolidated inventory catalog, cross-source matrix, and JSON/CSV export.
    """
    # 1. Fetch consolidated inventory
    inv_res = await client.get("/api/v1/inventory/consolidated")
    assert inv_res.status_code == 200
    inv = inv_res.json()
    assert "total_sources" in inv
    assert "total_columns" in inv
    assert "sources" in inv
    assert "columns" in inv
    assert "category_coverage_matrix" in inv
    assert "cross_source_matches" in inv

    # 2. Export consolidated as JSON
    export_json_res = await client.get("/api/v1/inventory/consolidated/export?format=json")
    assert export_json_res.status_code == 200
    assert "application/json" in export_json_res.headers.get("content-type", "")
    assert "total_sources" in export_json_res.json()

    # 3. Export consolidated as CSV
    export_csv_res = await client.get("/api/v1/inventory/consolidated/export?format=csv")
    assert export_csv_res.status_code == 200
    assert "text/csv" in export_csv_res.headers.get("content-type", "")
    assert "dataset_id" in export_csv_res.text


@pytest.mark.asyncio
async def test_privacy_governance_analysis(client: AsyncClient):
    """
    Tests the case-specific privacy analysis aggregation endpoint.
    """
    res = await client.get("/api/v1/inventory/privacy-analysis")
    assert res.status_code == 200
    data = res.json()

    assert "smart_personal_data_mapper" in data
    mapper = data["smart_personal_data_mapper"]
    assert "categories_distribution" in mapper
    assert "total_classified_fields" in mapper

    assert "privacy_leak_detector" in data
    leak = data["privacy_leak_detector"]
    assert "total_deterministic_findings" in leak

    assert "privacy_requests_summary" in data
    assert "breach_assistant_summary" in data


@pytest.mark.asyncio
async def test_audit_logs_endpoint(client: AsyncClient):
    """
    Tests retrieval of system administrative audit events.
    """
    res = await client.get("/api/v1/inventory/audit-logs")
    assert res.status_code == 200
    logs = res.json()
    assert isinstance(logs, list)
    if logs:
        sample_log = logs[0]
        assert "action" in sample_log
        assert "entity_type" in sample_log
        assert "timestamp" in sample_log
        # Verify no raw PII in details
        assert "@" not in str(sample_log.get("details", ""))
