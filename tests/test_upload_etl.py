import os
import pytest
from httpx import AsyncClient

SAMPLE_CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "sample_data", "synthetic_customers.csv"
)


@pytest.mark.asyncio
async def test_upload_and_etl_pipeline(client: AsyncClient):
    assert os.path.exists(SAMPLE_CSV_PATH), f"Sample file not found at {SAMPLE_CSV_PATH}"

    with open(SAMPLE_CSV_PATH, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("synthetic_customers.csv", file_bytes, "text/csv")}
    response = await client.post("/api/v1/inventory/upload", files=files)
    assert response.status_code == 200, f"Upload failed: {response.text}"

    data = response.json()
    assert "dataset_id" in data
    assert data["dataset_id"].startswith("ds_")
    assert data["version"] == 1
    assert data["filename"] == "synthetic_customers.csv"
    assert data["row_count"] == 10

    # Rule: accepted_count + rejected_count + duplicate_count == row_count
    assert (
        data["accepted_count"] + data["rejected_count"] + data["duplicate_count"]
        == data["row_count"]
    )

    # Columns and ETL issues assertions
    assert len(data["columns"]) >= 1
    assert isinstance(data["etl_issues"], list)
    assert isinstance(data["identifier_findings"], list)
    assert data["status"] == "AI_CLASSIFIED"

    dataset_id = data["dataset_id"]

    # Test GET dataset detail
    detail_res = await client.get(f"/api/v1/inventory/datasets/{dataset_id}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["dataset_id"] == dataset_id
    assert len(detail_data["columns"]) == len(data["columns"])

    # Test GET identifier findings
    findings_res = await client.get(f"/api/v1/inventory/datasets/{dataset_id}/identifier-findings")
    assert findings_res.status_code == 200
    findings = findings_res.json()
    assert isinstance(findings, list)
    # Check that any finding contains valid disclaimer caveat
    for f in findings:
        assert "caveat" in f
        assert "pattern match only" in f["caveat"].lower()

    # Test Approve
    approve_res = await client.post(f"/api/v1/inventory/datasets/{dataset_id}/approve")
    assert approve_res.status_code == 200
    assert approve_res.json()["status"] == "APPROVED"

    # Test Cleanup staging file
    cleanup_res = await client.delete(f"/api/v1/inventory/datasets/{dataset_id}/temp-file")
    assert cleanup_res.status_code == 200
