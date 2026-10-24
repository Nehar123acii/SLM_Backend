import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_incident_workflow(client: AsyncClient):
    payload = {
        "report_text": "Customer backup file was accidentally exposed on a public S3 bucket with 3000 customer records.",
        "reporter_role": "infrastructure_engineer",
        "discovery_datetime_hint": "2026-10-24T10:00:00Z",
    }
    # 1. POST a new incident
    create_res = await client.post("/api/v1/incidents", json=payload)
    assert create_res.status_code == 201, f"Incident creation failed: {create_res.text}"
    data = create_res.json()

    assert "incident_ref" in data
    assert data["incident_ref"].startswith("inc_")
    incident_ref = data["incident_ref"]
    assert data["incident_type"] == "ACCIDENTAL_DISCLOSURE"
    assert data["status"] == "DRAFT"
    assert len(data["checklist"]) == 10

    # 2. GET the incident
    get_res = await client.get(f"/api/v1/incidents/{incident_ref}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["incident_ref"] == incident_ref
    # Contract requirement: needs_human_review is always true
    assert get_data["needs_human_review"] is True
    assert get_data["reporter_role"] == "infrastructure_engineer"

    # 3. PATCH status
    patch_status_res = await client.patch(
        f"/api/v1/incidents/{incident_ref}/status",
        json={"status": "UNDER_REVIEW"},
    )
    assert patch_status_res.status_code == 200
    assert patch_status_res.json()["status"] == "UNDER_REVIEW"

    # 4. PATCH checklist
    checklist = get_data["checklist"]
    checklist[0]["completed"] = True
    patch_check_res = await client.patch(
        f"/api/v1/incidents/{incident_ref}/checklist",
        json={"checklist": checklist},
    )
    assert patch_check_res.status_code == 200
    assert patch_check_res.json()["checklist"][0]["completed"] is True

    # 5. POST evidence
    evidence_res = await client.post(
        f"/api/v1/incidents/{incident_ref}/evidence",
        json={"evidence_ref": "s3_access_log_20261024.csv"},
    )
    assert evidence_res.status_code == 200
    evidence_data = evidence_res.json()
    assert "s3_access_log_20261024.csv" in evidence_data["evidence_refs"]

    # 6. List with filter
    list_res = await client.get("/api/v1/incidents?status=UNDER_REVIEW")
    assert list_res.status_code == 200
    items = list_res.json()
    assert any(i["incident_ref"] == incident_ref for i in items)
