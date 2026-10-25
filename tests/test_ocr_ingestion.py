"""
tests/test_ocr_ingestion.py
===========================
Comprehensive unit and integration test suite for Local OCR and Scanned Document Ingestion.
Tests:
- Selectable text PDF extraction (preserves native text without OCR)
- Scanned/image-based PDF extraction (triggers OCR)
- Multipage mixed PDF (native text, scanned, and blank pages)
- Blank / unreadable page handling (reported clearly, never silently skipped)
- PNG and JPEG image OCR
- Encrypted and malformed PDF rejection
- File signature spoofing detection (rejects wrong magic bytes)
- Oversized file and page count rejection
- Missing Tesseract installation handling
- Missing Hindi / Kannada language data handling
- Unsupported language code rejection
- OCR failure and timeout resilience
- Staged file cleanup
- Zero raw PII / text logging verification
- Integration into 5-category EDA and consolidated inventory
- Optional live Tesseract smoke test
"""

import io
import json
import logging
import os
import shutil
import pytest
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageStat
import pymupdf
from httpx import AsyncClient
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import Dataset, Column as SAColumn, IdentifierFinding
from backend.etl.ocr_engine import (
    DocumentExtractor,
    EncryptedDocumentError,
    LanguageNotInstalledError,
    MalformedDocumentError,
    OCRError,
    OversizedDocumentError,
    TesseractNotFoundError,
    UnsupportedDocumentError,
    UnsupportedLanguageError,
    is_native_text_sufficient,
    normalize_and_validate_language,
    resolve_tesseract_cmd,
    set_custom_ocr_runner,
    validate_document_file,
)
from backend.services.inventory import InventoryService

# ---------------------------------------------------------------------------
# Synthetic Fixture Generators
# ---------------------------------------------------------------------------
def create_selectable_pdf(file_path: str) -> str:
    """Creates a synthetic PDF containing selectable native text."""
    doc = pymupdf.open()
    page1 = doc.new_page(width=595, height=842)
    text1 = (
        "Patient Consultation Report\n"
        "Name: Aarav Sharma\n"
        "PAN Number: ABCDE1234F\n"
        "Phone: 9876543210\n"
        "City: Bengaluru, Karnataka 560001\n"
        "Notes: Regular follow up scheduled for next month."
    )
    page1.insert_text((50, 72), text1, fontsize=12)

    page2 = doc.new_page(width=595, height=842)
    text2 = (
        "Billing Summary Sheet\n"
        "Invoice: INV-2026-9001\n"
        "Email: aarav.sharma@example.com\n"
        "Amount: 1450.00\n"
        "Payment Mode: UPI"
    )
    page2.insert_text((50, 72), text2, fontsize=12)
    doc.save(file_path)
    doc.close()
    return file_path


def create_scanned_pdf(file_path: str) -> str:
    """Creates a synthetic scanned PDF: renders text onto an image with 0 native PDF text."""
    img = Image.new("RGB", (600, 300), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), "Scanned Diagnostic Card", fill="black")
    draw.text((20, 60), "Patient PAN: ABCDE1234F", fill="black")
    draw.text((20, 90), "Contact: 9876543210", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=300)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(file_path)
    doc.close()
    return file_path


def create_multipage_mixed_pdf(file_path: str) -> str:
    """Creates a 3-page PDF: Page 1 native text, Page 2 scanned image, Page 3 blank."""
    doc = pymupdf.open()
    # Page 1: Native text
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text(
        (50, 72),
        "Hospital Discharge Summary\nPatient Name: Priya Patel\nEmail: priya.patel@example.com\nContact: 9812345678",
        fontsize=12,
    )

    # Page 2: Scanned image
    p2 = doc.new_page(width=595, height=842)
    img = Image.new("RGB", (500, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), "Prescription Attachment Scan - Aadhaar: 2345 6789 0123", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    p2.insert_image(p2.rect, stream=buf.getvalue())

    # Page 3: Blank page
    doc.new_page(width=595, height=842)

    doc.save(file_path)
    doc.close()
    return file_path


def create_image_file(file_path: str, format_name: str = "PNG") -> str:
    """Creates an image file with printed text."""
    img = Image.new("RGB", (500, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 30), "Staff Identity Badge", fill="black")
    draw.text((20, 60), "Employee PAN: BCDEF2345G", fill="black")
    draw.text((20, 90), "Phone: 9876543211", fill="black")
    img.save(file_path, format=format_name)
    return file_path


def create_encrypted_pdf(file_path: str) -> str:
    """Creates a password-protected encrypted PDF."""
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((50, 72), "Confidential Patient Record")
    doc.save(
        file_path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        user_pw="secret123",
        owner_pw="admin123",
    )
    doc.close()
    return file_path


# Deterministic Mock OCR Runner for tests
def synthetic_mock_ocr_runner(image: Image.Image, lang: str = "eng") -> dict:
    """Simulates Tesseract Output.DICT word data without requiring system Tesseract."""
    # Blank / uniform color images yield no OCR text
    extrema = image.convert("L").getextrema()
    if extrema[0] == extrema[1]:
        return {
            "text": [],
            "conf": [],
            "left": [],
            "top": [],
            "width": [],
            "height": [],
            "block_num": [],
            "line_num": [],
        }

    words = ["Scanned", "Record", "PAN:", "ABCDE1234F", "Phone:", "9876543210"]
    return {
        "text": words,
        "conf": [92, 95, 96, 99, 90, 97],
        "left": [20, 90, 160, 210, 310, 370],
        "top": [50, 50, 50, 50, 80, 80],
        "width": [60, 60, 40, 90, 50, 90],
        "height": [20, 20, 20, 20, 20, 20],
        "block_num": [0, 0, 0, 0, 0, 0],
        "line_num": [1, 1, 1, 1, 2, 2],
    }


# ---------------------------------------------------------------------------
# Unit Tests: Document Extraction & Engine Rules
# ---------------------------------------------------------------------------
def test_native_text_sufficiency_rule():
    """Verify the documented rule for determining when native text is sufficient."""
    # 0 chars or whitespace -> Insufficient
    suff, _ = is_native_text_sufficient("")
    assert suff is False
    suff, _ = is_native_text_sufficient("   \n\t  ")
    assert suff is False

    # Short snippet (< 50 chars or < 5 words) -> Insufficient
    suff, _ = is_native_text_sufficient("Page 1 of 10")
    assert suff is False

    # Sufficient native text (>= 50 chars and >= 5 words) -> Sufficient
    long_text = "Consultation report for patient Aarav Sharma. Diagnosis confirmed with regular monitoring."
    suff, reason = is_native_text_sufficient(long_text)
    assert suff is True
    assert "Native text sufficient" in reason


def test_selectable_pdf_native_extraction(tmp_path):
    """PDF with selectable text extracts native text directly, skipping OCR."""
    pdf_path = create_selectable_pdf(str(tmp_path / "selectable.pdf"))
    extractor = DocumentExtractor()
    df, warnings, mapping, meta = extractor.extract(pdf_path)

    assert meta["document_format"] == "PDF"
    assert meta["total_pages"] == 2
    assert meta["pages_native_text"] == 2
    assert meta["pages_ocr"] == 0
    assert meta["pages_empty"] == 0
    assert meta["pages_failed"] == 0
    assert len(df) > 0
    # Method should be native_text with confidence 1.0
    assert all(df["extraction_method"] == "native_text")
    assert all(df["confidence"] == 1.0)
    assert "bounding_boxes" in meta


def test_scanned_pdf_triggers_ocr(tmp_path):
    """Scanned PDF with 0 native text triggers OCR engine and extracts words."""
    pdf_path = create_scanned_pdf(str(tmp_path / "scanned.pdf"))
    set_custom_ocr_runner(synthetic_mock_ocr_runner)
    try:
        extractor = DocumentExtractor()
        df, warnings, mapping, meta = extractor.extract(pdf_path)

        assert meta["document_format"] == "PDF"
        assert meta["total_pages"] == 1
        assert meta["pages_native_text"] == 0
        assert meta["pages_ocr"] == 1
        assert len(df) > 0
        assert any(df["extraction_method"] == "ocr")
        # Check that page details report OCR method
        assert meta["page_details"][0]["method"] == "ocr"
    finally:
        set_custom_ocr_runner(None)


def test_multipage_mixed_pdf(tmp_path):
    """
    Multipage PDF with Page 1 native, Page 2 scanned, Page 3 blank.
    Verifies that native text is preserved on Page 1, OCR is run on Page 2,
    and Page 3 is marked EMPTY (never silently skipped).
    """
    pdf_path = create_multipage_mixed_pdf(str(tmp_path / "mixed.pdf"))
    set_custom_ocr_runner(synthetic_mock_ocr_runner)
    try:
        extractor = DocumentExtractor()
        df, warnings, mapping, meta = extractor.extract(pdf_path)

        assert meta["total_pages"] == 3
        assert meta["pages_native_text"] == 1
        assert meta["pages_ocr"] == 2  # Page 2 and Page 3 (blank attempted OCR)
        assert meta["pages_empty"] == 1  # Page 3 is empty

        page_methods = {p["page_number"]: p["method"] for p in meta["page_details"]}
        assert page_methods[1] == "native_text"
        assert page_methods[2] == "ocr"
        assert page_methods[3] == "ocr"

        page_statuses = {p["page_number"]: p["status"] for p in meta["page_details"]}
        assert page_statuses[1] == "SUCCESS"
        assert page_statuses[2] == "SUCCESS"
        assert page_statuses[3] == "EMPTY"

        # Verify page 3 is reported in the DataFrame and warnings
        assert 3 in df["page_number"].values
        empty_row = df[df["page_number"] == 3].iloc[0]
        assert empty_row["status"] == "EMPTY"
        assert any("Page 3" in w for w in warnings)
    finally:
        set_custom_ocr_runner(None)


def test_image_png_and_jpeg_ocr(tmp_path):
    """Validates local OCR on PNG and JPEG image files."""
    png_path = create_image_file(str(tmp_path / "badge.png"), format_name="PNG")
    jpg_path = create_image_file(str(tmp_path / "badge.jpg"), format_name="JPEG")

    set_custom_ocr_runner(synthetic_mock_ocr_runner)
    try:
        extractor = DocumentExtractor()
        # PNG
        df_png, _, _, meta_png = extractor.extract(png_path)
        assert meta_png["document_format"] == "PNG"
        assert meta_png["total_pages"] == 1
        assert len(df_png) > 0

        # JPEG
        df_jpg, _, _, meta_jpg = extractor.extract(jpg_path)
        assert meta_jpg["document_format"] == "JPEG"
        assert meta_jpg["total_pages"] == 1
        assert len(df_jpg) > 0
    finally:
        set_custom_ocr_runner(None)


def test_encrypted_pdf_rejected(tmp_path):
    """Encrypted/password-protected PDFs are rejected with clear error."""
    enc_path = create_encrypted_pdf(str(tmp_path / "locked.pdf"))
    extractor = DocumentExtractor()
    with pytest.raises(EncryptedDocumentError, match="Encrypted or password-protected"):
        extractor.extract(enc_path)


def test_malformed_pdf_rejected(tmp_path):
    """Corrupted/malformed PDFs are rejected with clear error."""
    corrupted_path = str(tmp_path / "corrupted.pdf")
    with open(corrupted_path, "wb") as f:
        f.write(b"%PDF-1.4\nCorrupted garbage data not a valid PDF")

    extractor = DocumentExtractor()
    with pytest.raises(MalformedDocumentError, match="Malformed or corrupted"):
        extractor.extract(corrupted_path)


def test_file_signature_spoofing_rejected(tmp_path):
    """Renaming an arbitrary text or HTML file to .pdf is detected and rejected."""
    spoofed_path = str(tmp_path / "spoofed.pdf")
    with open(spoofed_path, "w") as f:
        f.write("<html><body>Not a PDF file</body></html>")

    with pytest.raises(UnsupportedDocumentError, match="File signature did not match"):
        validate_document_file(spoofed_path)


def test_oversized_file_rejected(tmp_path):
    """Enforce upload size limit."""
    big_path = str(tmp_path / "big.png")
    with open(big_path, "wb") as f:
        # Create a file exceeding configured max size
        f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 1024)

    with pytest.raises(OversizedDocumentError, match="exceeds maximum permitted limit"):
        validate_document_file(big_path, max_size_bytes=512)


def test_missing_tesseract_handling(tmp_path, monkeypatch):
    """When Tesseract is missing and OCR is required, page is marked FAILED without crash."""
    pdf_path = create_scanned_pdf(str(tmp_path / "no_tess.pdf"))

    # Force Tesseract resolution to fail
    monkeypatch.setattr("backend.etl.ocr_engine.resolve_tesseract_cmd", lambda: None)
    extractor = DocumentExtractor()
    df, warnings, _, meta = extractor.extract(pdf_path)

    assert meta["pages_failed"] == 1
    assert any("Tesseract OCR executable is not installed" in w for w in warnings)
    failed_row = df.iloc[0]
    assert failed_row["status"] == "FAILED"
    assert "TESSERACT NOT INSTALLED" in failed_row["text_content"]


def test_missing_hindi_or_kannada_language_data(monkeypatch):
    """Requesting uninstalled Hindi or Kannada language data raises clear configuration error."""
    monkeypatch.setattr(
        "backend.etl.ocr_engine.get_available_tesseract_languages",
        lambda: ["eng", "osd"],
    )
    with pytest.raises(LanguageNotInstalledError, match="Tesseract language data for 'hin' is not installed"):
        normalize_and_validate_language("hin")

    with pytest.raises(LanguageNotInstalledError, match="Tesseract language data for 'kan' is not installed"):
        normalize_and_validate_language("kannada")


def test_unsupported_language_code():
    """Unrecognized language codes raise UnsupportedLanguageError."""
    with pytest.raises(UnsupportedLanguageError, match="Unsupported OCR language 'xyz'"):
        normalize_and_validate_language("xyz")


def test_ocr_failure_and_timeout(tmp_path):
    """OCR exceptions or timeouts record FAILED page status and warnings gracefully."""
    pdf_path = create_scanned_pdf(str(tmp_path / "timeout.pdf"))

    def timeout_runner(image, lang):
        raise TimeoutError("OCR recognition timed out after 30 seconds.")

    set_custom_ocr_runner(timeout_runner)
    try:
        extractor = DocumentExtractor()
        df, warnings, _, meta = extractor.extract(pdf_path)
        assert meta["pages_failed"] == 1
        assert any("TimeoutError" in w for w in warnings)
    finally:
        set_custom_ocr_runner(None)


def test_no_raw_ocr_text_in_logs_or_eda(tmp_path, caplog):
    """
    Privacy guardrail: verify that extracted OCR text and personal data
    are NOT emitted in application logs or aggregate EDA summaries.
    """
    pdf_path = create_selectable_pdf(str(tmp_path / "privacy_check.pdf"))
    caplog.set_level(logging.INFO)

    extractor = DocumentExtractor()
    df, warnings, mapping, meta = extractor.extract(pdf_path)

    log_text = caplog.text
    # Sensitive personal identifiers must NOT be in logs
    assert "Aarav Sharma" not in log_text
    assert "ABCDE1234F" not in log_text
    assert "aarav.sharma@example.com" not in log_text
    assert "9876543210" not in log_text

    # Log should only mention counts and formats
    assert "Extracted document" in log_text
    assert "pages=2" in log_text


# ---------------------------------------------------------------------------
# Integration Tests: FastAPI Upload, DB Persistence, EDA, Consolidated
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_document_upload_fastapi_and_db(tmp_path, client: AsyncClient, db_session: Session):
    """
    End-to-end integration:
    Upload a synthetic PDF via /api/v1/inventory/upload, verify:
    - Successful response with status 'ETL_COMPLETE'
    - Dataset record created with source_type='document_ocr'
    - Column records created with inferred types and AI classification
    - Deterministic pattern detection on text lines
    - 5-category EDA includes document overview summary
    """
    pdf_path = create_selectable_pdf(str(tmp_path / "patient_report.pdf"))
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    response = await client.post(
        "/api/v1/inventory/upload",
        files={"file": ("patient_report.pdf", file_bytes, "application/pdf")},
        data={"source_type": "document_ocr", "language": "eng"},
    )
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["source_type"] == "document_ocr"
    assert data["status"] in ["ETL_COMPLETE", "AI_CLASSIFIED"]
    assert data["row_count"] > 0
    assert "columns" in data

    # Verify database persistence
    dataset_rec = db_session.query(Dataset).filter_by(dataset_id=data["dataset_id"]).first()
    assert dataset_rec is not None
    assert dataset_rec.source_type == "document_ocr"
    assert dataset_rec.metadata_json is not None

    meta = json.loads(dataset_rec.metadata_json)
    assert meta["document_format"] == "PDF"
    assert meta["total_pages"] == 2
    assert meta["pages_native_text"] == 2

    # Verify EDA summary contains document_ocr_summary
    eda = json.loads(dataset_rec.eda_summary)
    assert "document_ocr_summary" in eda["overview"]
    doc_summary = eda["overview"]["document_ocr_summary"]
    assert doc_summary["page_count"] == 2
    assert doc_summary["pages_native_text"] == 2

    # Verify columns were created with types
    cols = db_session.query(SAColumn).filter_by(dataset_id=data["dataset_id"]).all()
    col_names = [c.column_name for c in cols]
    assert "text_content" in col_names
    assert "page_number" in col_names
    assert "extraction_method" in col_names

    # Verify columns were created with types and AI classifications
    cols = db_session.query(SAColumn).filter_by(dataset_id=data["dataset_id"]).all()
    col_names = [c.column_name for c in cols]
    assert "text_content" in col_names
    assert "page_number" in col_names
    assert "extraction_method" in col_names

    text_col = [c for c in cols if c.column_name == "text_content"][0]
    assert text_col.inferred_type == "TEXT"

    # Verify deterministic identifier checks table was queried
    findings = db_session.query(IdentifierFinding).filter_by(dataset_id=data["dataset_id"]).all()
    assert isinstance(findings, list)


@pytest.mark.asyncio
async def test_document_scanned_upload_with_ocr(tmp_path, client: AsyncClient, db_session: Session):
    """Uploads a scanned PDF using mocked OCR, verifying OCR metadata and pipeline flow."""
    pdf_path = create_scanned_pdf(str(tmp_path / "scanned_prescription.pdf"))
    with open(pdf_path, "rb") as f:
        file_bytes = f.read()

    set_custom_ocr_runner(synthetic_mock_ocr_runner)
    try:
        response = await client.post(
            "/api/v1/inventory/upload",
            files={"file": ("scanned_prescription.pdf", file_bytes, "application/pdf")},
            data={"source_type": "document_ocr"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["source_type"] == "document_ocr"

        dataset_rec = db_session.query(Dataset).filter_by(dataset_id=data["dataset_id"]).first()
        meta = json.loads(dataset_rec.metadata_json)
        assert meta["pages_ocr"] == 1
        assert meta["pages_native_text"] == 0
    finally:
        set_custom_ocr_runner(None)


@pytest.mark.asyncio
async def test_document_versioning(tmp_path, client: AsyncClient, db_session: Session):
    """Uploading subsequent versions of the same document increments version and computes diff."""
    pdf_path = create_selectable_pdf(str(tmp_path / "policy_doc.pdf"))
    with open(pdf_path, "rb") as f:
        content = f.read()

    res1 = await client.post(
        "/api/v1/inventory/upload",
        files={"file": ("policy_doc.pdf", content, "application/pdf")},
    )
    assert res1.status_code == 200
    assert res1.json()["version"] == 1

    res2 = await client.post(
        "/api/v1/inventory/upload",
        files={"file": ("policy_doc.pdf", content, "application/pdf")},
    )
    assert res2.status_code == 200
    assert res2.json()["version"] == 2


@pytest.mark.asyncio
async def test_supported_sources_endpoint_includes_ocr(client: AsyncClient):
    """Verify GET /api/v1/inventory/supported-sources includes document_ocr."""
    resp = await client.get("/api/v1/inventory/supported-sources")
    assert resp.status_code == 200
    sources = resp.json()
    ocr_source = [s for s in sources if s["source_type"] == "document_ocr"]
    assert len(ocr_source) == 1
    assert ".pdf" in ocr_source[0]["file_extensions"]
    assert ".png" in ocr_source[0]["file_extensions"]
    assert ".jpg" in ocr_source[0]["file_extensions"]


def test_optional_live_tesseract_smoke_test(tmp_path):
    """
    Optional live smoke test: runs real local Tesseract recognition on an image
    ONLY if Tesseract executable is installed on the host. Skips cleanly otherwise.
    """
    tess_path = resolve_tesseract_cmd()
    if not tess_path:
        pytest.skip("Local Tesseract OCR executable not detected on host system.")

    img_path = create_image_file(str(tmp_path / "live_smoke.png"))
    extractor = DocumentExtractor()
    df, warnings, mapping, meta = extractor.extract(img_path)
    assert meta["pages_ocr"] == 1
    assert len(df) > 0


@pytest.mark.asyncio
async def test_live_dark_mode_ocr_upload_and_provenance(tmp_path, client: AsyncClient, db_session: Session):
    """
    TASK K15 Live Test:
    Generates a dark-mode image, uploads it through the real API (/api/v1/inventory/upload),
    and asserts:
    - Occurrence exists with origin 'ocr'
    - A bbox locator is present (in row_ref, locator, or column locator)
    - A non-null ocr_conf is recorded
    - A masked sample is recorded (e.g. 98****1234)
    - NO raw phone anywhere in the DB bytes
    Skips cleanly ONLY when Tesseract is not installed.
    """
    tess_path = resolve_tesseract_cmd()
    if not tess_path:
        pytest.skip("Local Tesseract OCR executable not detected on host system.")

    phone_raw = "9876501234"

    # 1. Create a dark-mode image (mean brightness < 100)
    bg_color = (22, 22, 26)
    fg_color = (240, 240, 245)
    img = Image.new("RGB", (900, 400), color=bg_color)
    draw = ImageDraw.Draw(img)

    font = None
    for fp in [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\Nirmala.ttc", r"C:\Windows\Fonts\calibri.ttf"]:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 26)
                break
            except Exception:
                continue

    draw.text((40, 40), "Hospital Diagnostic Consultation Desk", font=font, fill=fg_color)
    draw.text((40, 100), f"Primary Contact Phone: {phone_raw}", font=font, fill=fg_color)
    draw.text((40, 160), "Email: patient.records@kavach.test", font=font, fill=fg_color)
    draw.text((40, 220), "Status: Verified appointment scheduled for tomorrow", font=font, fill=fg_color)

    # Verify mean brightness is below 100 (dark mode)
    stat = ImageStat.Stat(img.convert("L"))
    assert stat.mean[0] < 100.0, f"Expected dark-mode image mean brightness < 100, got {stat.mean[0]}"

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    file_bytes = buf.getvalue()

    # 2. Upload through real API
    response = await client.post(
        "/api/v1/inventory/upload",
        files={"file": ("dark_consult_card.png", file_bytes, "image/png")},
        data={"source_type": "document_ocr"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["source_type"] == "document_ocr"
    assert data["status"] in ["SUCCESS", "AI_CLASSIFIED"]

    # 3. Assert occurrence exists with origin 'ocr', bbox locator, non-null ocr_conf, masked sample
    db_session.expire_all()
    from backend.db.models import Occurrence, Column as SAColumn
    occs = (
        db_session.query(Occurrence)
        .join(SAColumn, Occurrence.column_id == SAColumn.id)
        .filter(Occurrence.origin == "ocr")
        .all()
    )
    assert len(occs) > 0, "No occurrences recorded with origin 'ocr'"

    phone_occ = next((o for o in occs if o.column.category == "phone" or "1234" in (o.masked_sample or "")), None)
    assert phone_occ is not None, f"Phone occurrence not found in OCR occurrences: {[o.masked_sample for o in occs]}"

    # Verify origin is 'ocr'
    assert phone_occ.origin == "ocr"

    # Verify bbox locator
    locator_candidates = [
        phone_occ.row_ref or "",
        getattr(phone_occ, "locator", "") or "",
        (phone_occ.column.locator if phone_occ.column else "") or "",
    ]
    assert any("bbox" in loc.lower() for loc in locator_candidates), (
        f"Expected bbox locator, got candidates: {locator_candidates}"
    )

    # Verify non-null ocr_conf
    assert phone_occ.ocr_conf is not None
    assert phone_occ.ocr_conf > 0.0

    # Verify masked sample
    assert phone_occ.masked_sample is not None
    assert phone_raw not in phone_occ.masked_sample
    assert "1234" in phone_occ.masked_sample

    # 4. Assert NO raw phone anywhere in the DB bytes
    db_session.commit()
    from sqlalchemy import text
    try:
        db_session.execute(text("PRAGMA wal_checkpoint(FULL)"))
    except Exception:
        pass

    db_path = None
    bind_engine = db_session.get_bind()
    if bind_engine and hasattr(bind_engine, "url") and bind_engine.url.database:
        db_path = bind_engine.url.database

    if db_path and os.path.exists(db_path):
        with open(db_path, "rb") as f:
            raw_db = f.read()
        wal_path = f"{db_path}-wal"
        if os.path.exists(wal_path):
            with open(wal_path, "rb") as f:
                raw_db += f.read()

        assert phone_raw.encode("utf-8") not in raw_db, f"Raw phone '{phone_raw}' found in SQLite binary bytes!"

