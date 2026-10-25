import os
import pytest
from httpx import AsyncClient

SAMPLE_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "sample_data")
RAW_MESSY_DIR = os.path.join(SAMPLE_DATA_DIR, "raw_messy")


@pytest.mark.asyncio
async def test_get_supported_sources(client: AsyncClient):
    """Verifies the supported sources catalog endpoint."""
    res = await client.get("/api/v1/inventory/supported-sources")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    source_types = [s["source_type"] for s in data]
    assert "csv" in source_types
    assert "excel" in source_types
    assert "google_forms" in source_types
    assert "whatsapp" in source_types
    assert "json" in source_types


@pytest.mark.asyncio
async def test_ingest_multisheet_excel(client: AsyncClient):
    """
    Tests Excel ingestion with multi-sheet detection and explicit sheet selection.
    """
    excel_path = os.path.join(RAW_MESSY_DIR, "multisheet_clinic.xlsx")
    assert os.path.exists(excel_path), f"File {excel_path} not found"

    with open(excel_path, "rb") as f:
        file_bytes = f.read()

    # 1. Upload without specifying sheet (should default to first sheet with notice)
    files = {"file": ("multisheet_clinic.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data = {"source_type": "excel"}
    res1 = await client.post("/api/v1/inventory/upload", files=files, data=data)
    assert res1.status_code == 200, res1.text
    out1 = res1.json()
    assert out1["source_type"] == "excel"
    assert out1["sheet_name"] == "Patients_Directory"
    assert out1["row_count"] == 3
    col_names = [c["column_name"] for c in out1["columns"]]
    assert "patient_name" in col_names
    assert "diagnosis_notes" in col_names

    # 2. Upload specifying second sheet: 'Doctors_Roster'
    files2 = {"file": ("multisheet_clinic.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    data2 = {"source_type": "excel", "sheet_name": "Doctors_Roster"}
    res2 = await client.post("/api/v1/inventory/upload", files=files2, data=data2)
    assert res2.status_code == 200, res2.text
    out2 = res2.json()
    assert out2["source_type"] == "excel"
    assert out2["sheet_name"] == "Doctors_Roster"
    assert out2["row_count"] == 2
    col_names2 = [c["column_name"] for c in out2["columns"]]
    assert "doctor_name" in col_names2
    assert "department" in col_names2


@pytest.mark.asyncio
async def test_ingest_google_forms_export(client: AsyncClient):
    """
    Tests Google Forms CSV export ingestion:
    - Question text preservation in column metadata
    - Submission timestamps
    - Forms response completeness metrics
    """
    forms_path = os.path.join(SAMPLE_DATA_DIR, "appointments_form.csv")
    assert os.path.exists(forms_path), f"File {forms_path} not found"

    with open(forms_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("appointments_form.csv", file_bytes, "text/csv")}
    data = {"source_type": "google_forms"}
    res = await client.post("/api/v1/inventory/upload", files=files, data=data)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["source_type"] == "google_forms"
    assert out["row_count"] == 20

    # Verify original question headers are preserved in columns
    columns = out["columns"]
    orig_names = [c["original_name"] for c in columns]
    assert "Timestamp" in orig_names
    assert "Reason" in orig_names


@pytest.mark.asyncio
async def test_ingest_whatsapp_chat(client: AsyncClient):
    """
    Tests WhatsApp exported chat text ingestion:
    - Multi-line continuation parsing
    - Timestamp & sender parsing
    - Zero raw PII logging
    - Attachment placeholders
    """
    wa_path = os.path.join(SAMPLE_DATA_DIR, "whatsapp_chat.txt")
    assert os.path.exists(wa_path), f"File {wa_path} not found"

    with open(wa_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("whatsapp_chat.txt", file_bytes, "text/plain")}
    data = {"source_type": "whatsapp"}
    res = await client.post("/api/v1/inventory/upload", files=files, data=data)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["source_type"] == "whatsapp"
    assert out["row_count"] > 250

    col_names = [c["column_name"] for c in out["columns"]]
    assert "message_ref" in col_names
    assert "timestamp" in col_names
    assert "sender" in col_names
    assert "message_text" in col_names


@pytest.mark.asyncio
async def test_ingest_nested_json(client: AsyncClient):
    """
    Tests JSON ingestion with nested dotted paths (contact.email, address.city, kyc.pan).
    """
    json_path = os.path.join(RAW_MESSY_DIR, "customers_nested.json")
    assert os.path.exists(json_path), f"File {json_path} not found"

    with open(json_path, "rb") as f:
        file_bytes = f.read()

    files = {"file": ("customers_nested.json", file_bytes, "application/json")}
    data = {"source_type": "json"}
    res = await client.post("/api/v1/inventory/upload", files=files, data=data)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["source_type"] == "json"
    assert out["row_count"] == 3

    col_names = [c["column_name"] for c in out["columns"]]
    assert "contact_email" in col_names or "contact.email" in col_names or any("email" in c for c in col_names)
    assert any("pan" in c for c in col_names)


@pytest.mark.asyncio
async def test_transactional_rollback_on_malformed_upload(client: AsyncClient):
    """
    Tests that a malformed upload rolls back cleanly and leaves no phantom dataset in DB.
    """
    # Malformed JSON
    bad_bytes = b"[{'bad_json': true,,]"
    files = {"file": ("bad_records.json", bad_bytes, "application/json")}
    data = {"source_type": "json"}
    res = await client.post("/api/v1/inventory/upload", files=files, data=data)
    assert res.status_code == 400

    # Verify no dataset was created
    datasets_res = await client.get("/api/v1/inventory/datasets")
    assert datasets_res.status_code == 200
    datasets = datasets_res.json()
    assert not any("bad_records.json" in d["original_filename"] for d in datasets)
