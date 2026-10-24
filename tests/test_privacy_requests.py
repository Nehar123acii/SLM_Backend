import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_privacy_request_workflow(client: AsyncClient):
    payload = {
        "raw_text": "Please provide me with a summary of all personal data held and delete my secondary address.",
        "submission_channel": "web_form",
    }
    # 1. POST new request
    post_res = await client.post("/api/v1/privacy-requests", json=payload)
    assert post_res.status_code == 201, f"Create failed: {post_res.text}"
    data = post_res.json()

    assert "request_id" in data
    assert data["request_id"].startswith("req_")
    request_id = data["request_id"]
    assert "ACCESS" in data["request_types"]
    assert "ERASURE" in data["request_types"]
    assert data["is_composite"] is True
    assert data["sla_deadline"] is not None

    # 2. GET the request
    get_res = await client.get(f"/api/v1/privacy-requests/{request_id}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["request_id"] == request_id
    assert get_data["status"] in ["PENDING_REVIEW", "RECEIVED"]
    assert len(get_data["checklist"]) >= 1

    # 3. PATCH status to IN_PROGRESS
    patch_status_res = await client.patch(
        f"/api/v1/privacy-requests/{request_id}/status",
        json={"status": "IN_PROGRESS"},
    )
    assert patch_status_res.status_code == 200
    assert patch_status_res.json()["status"] == "IN_PROGRESS"

    # 4. PATCH checklist
    updated_checklist = get_data["checklist"]
    if updated_checklist:
        updated_checklist[0]["completed"] = True

    patch_checklist_res = await client.patch(
        f"/api/v1/privacy-requests/{request_id}/checklist",
        json={"checklist": updated_checklist},
    )
    assert patch_checklist_res.status_code == 200
    assert patch_checklist_res.json()["checklist"][0]["completed"] is True

    # 5. List with filters
    list_res = await client.get("/api/v1/privacy-requests?status=IN_PROGRESS")
    assert list_res.status_code == 200
    items = list_res.json()
    assert any(item["request_id"] == request_id for item in items)
