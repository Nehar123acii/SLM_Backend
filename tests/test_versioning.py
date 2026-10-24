import os
import pytest
from httpx import AsyncClient

V1_PATH = os.path.join(os.path.dirname(__file__), "..", "sample_data", "synthetic_customers.csv")
V2_PATH = os.path.join(os.path.dirname(__file__), "..", "sample_data", "synthetic_customers_v2.csv")


@pytest.mark.asyncio
async def test_dataset_versioning_and_reconciliation(client: AsyncClient):
    with open(V1_PATH, "rb") as f:
        v1_bytes = f.read()
    with open(V2_PATH, "rb") as f:
        v2_bytes = f.read()

    # Upload v1
    files_v1 = {"file": ("synthetic_customers.csv", v1_bytes, "text/csv")}
    res_v1 = await client.post("/api/v1/inventory/upload", files=files_v1)
    assert res_v1.status_code == 200
    v1_data = res_v1.json()
    assert v1_data["version"] == 1
    ds1_id = v1_data["dataset_id"]

    # Upload v2 with same logical filename
    files_v2 = {"file": ("synthetic_customers.csv", v2_bytes, "text/csv")}
    res_v2 = await client.post("/api/v1/inventory/upload", files=files_v2)
    assert res_v2.status_code == 200
    v2_data = res_v2.json()
    assert v2_data["version"] == 2
    ds2_id = v2_data["dataset_id"]

    # Fetch diff for v2
    diff_res = await client.get(f"/api/v1/inventory/datasets/{ds2_id}/diff")
    assert diff_res.status_code == 200, f"Diff call failed: {diff_res.text}"
    diff_data = diff_res.json()

    assert diff_data["dataset_id"] == ds2_id
    assert diff_data["previous_dataset_id"] == ds1_id

    # Check non-negative integers
    assert isinstance(diff_data["added_count"], int) and diff_data["added_count"] >= 0
    assert isinstance(diff_data["changed_count"], int) and diff_data["changed_count"] >= 0
    assert isinstance(diff_data["removed_count"], int) and diff_data["removed_count"] >= 0
    assert isinstance(diff_data["unchanged_count"], int) and diff_data["unchanged_count"] >= 0

    # Ensure diff_json has valid structural details
    assert "diff_json" in diff_data
    diff_details = diff_data["diff_json"]
    assert isinstance(diff_details, dict)
    assert "key_columns" in diff_details
    assert "changed_rows" in diff_details
