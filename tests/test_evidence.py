import hashlib
import json
import os
import zipfile
import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import Session

from backend.main import create_app
from backend.services.ledger import append_event
from backend.services.evidence import export_evidence_pack, verify_evidence_pack


@pytest.fixture
def app_client(db_session: Session):
    app = create_app()
    from backend.api.deps import get_db
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_evidence_pack_manifest_hashes_equal_real_file_hashes(db_session: Session):
    """Verify export_evidence_pack creates a zip whose manifest hashes match real file contents."""
    append_event(db_session, "scan", {"source": "demo.csv", "rows": 10})
    append_event(db_session, "answer", {"column_id": 1, "segment": "customer", "status": "confirmed"})

    pack_info = export_evidence_pack(db_session)
    zip_path = pack_info["path"]
    assert os.path.exists(zip_path)

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "ledger.json" in namelist
        assert "flags.json" in namelist
        assert "purposes.json" in namelist
        assert "limitations.md" in namelist

        manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
        files_dict = manifest_data["files"]

        for filename, expected_hash in files_dict.items():
            content = zf.read(filename)
            actual_hash = hashlib.sha256(content).hexdigest()
            assert actual_hash == expected_hash, f"Hash mismatch for {filename}!"


def test_editing_file_inside_zip_makes_verify_report_mismatch(db_session: Session, app_client: TestClient):
    """Verify that editing a file inside the evidence zip causes /verify to report mismatch."""
    append_event(db_session, "upload", {"dataset_id": "ds_verify_test", "rows": 25})

    export_res = app_client.post("/api/evidence/export")
    assert export_res.status_code == 200
    pack_data = export_res.json()
    pack_id = pack_data["pack_id"]
    zip_path = pack_data["path"]

    # 1. Clean verification before any edit
    v_clean = app_client.get(f"/verify/{pack_id}").json()
    assert v_clean["ok"] is True
    assert v_clean["status"] == "chain intact"

    # 2. Tamper the ZIP archive: read all files, alter limitations.md, write back
    tampered_files = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in zf.namelist():
            tampered_files[name] = zf.read(name)

    # Modify limitations.md
    tampered_files["limitations.md"] = b"# TAMPERED LIMITATIONS FILE CONTENT"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in tampered_files.items():
            zf.writestr(name, content)

    # 3. Verification must now report mismatch
    v_tampered = app_client.get(f"/verify/{pack_id}").json()
    assert v_tampered["ok"] is False
    assert v_tampered["status"] == "mismatched"
    assert "limitations.md" in v_tampered["reason"]
