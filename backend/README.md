# Backend Module — Local-First Privacy Compliance Assistant

This module provides the server-side architecture, multi-source data ingestion adapters, ETL pipeline, runtime 5-category EDA, consolidated data inventory catalog, deterministic pattern validation, rights-request workflow, and breach incident tracking under India's Digital Personal Data Protection (DPDP) Act, 2023.

---

## 1. Supported Source Types & Formats

| Source Type (`source_type`) | Formats | Ingestion Behavior & Capabilities | Limitations / Export Notes |
|---|---|---|---|
| `csv` | `.csv` | UTF-8/BOM with Latin-1 fallback, delimiter parsing, row/column size enforcement, header whitespace & case normalization. | Max 50,000 rows, 200 cols by default. |
| `excel` | `.xlsx`, `.xls` | Multi-sheet inspection. Pass optional `sheet_name` form parameter or defaults to first worksheet with explicit multi-sheet notice. | Does not automatically merge unrelated worksheet schemas. |
| `google_forms` | `.csv`, `.xlsx` | Preserves full question titles, response timestamps, response completeness rates, and blank-answer tracking. | In Google Forms, export via *Responses* → *Link to Sheets* → *File* → *Download* → *CSV* / *Microsoft Excel (.xlsx)*. |
| `whatsapp` | `.txt` | Dedicated `.txt` parser supporting 12h/24h timestamps, multiline continuation messages, attachment markers (`<Media omitted>`), system notices. | In WhatsApp, export via *Chat* → *More options (⋮)* → *More* → *Export chat* → *Without media*. Never exposes raw message bodies in aggregate reports. |
| `json` | `.json` | Arrays of records or single nested objects. Flattens nested fields using dotted paths (e.g. `kyc.pan`, `address.city`) preserving lineage. | Malformed JSON is rejected transactionally with clear 400 error. |
| `document_ocr` | `.pdf`, `.png`, `.jpg`, `.jpeg`, `.tiff`, `.tif` | **Local OCR & Scanned Document Ingestion**. Two-stage pipeline: extracts selectable native text via PyMuPDF; triggers local Tesseract OCR on pages with insufficient text (< 50 chars). Preserves page numbers, line numbers, word coordinates/bounding boxes, and extraction confidences. Supports English, Hindi, and Kannada. | Max 25 MB, 100 pages by default. Encrypted/malformed files rejected. Requires local Tesseract binary for OCR on scanned pages; does not use cloud APIs. |

---

## 2. Ingestion & Runtime EDA Engine

### Five General EDA Categories (`GET /api/v1/inventory/datasets/{id}/eda-summary`)

1. **Dataset Overview**:
   - `row_count`, `column_count`, `source_type`, `format`, `dataset_id`, `version`, `processing_status`.
   - `type_distribution` (breakdown of 10 inferred ETL types: `TEXT`, `INTEGER`, `FLOAT`, `DATE`, `DATETIME`, `BOOLEAN`, `EMAIL`, `PHONE`, `URL`, `UNKNOWN`).
   - `reconciliation_summary` (source raw rows, accepted rows, rejected rows, duplicate rows).
2. **Completeness & Duplication**:
   - Per-column missing count and completeness percentage.
   - Total missing cells and overall missingness percentage.
   - Exact duplicate row counts.
   - Potential duplicate candidates (rows matching on contact identifiers like phone/email while varying elsewhere).
3. **Numeric Distributions**:
   - Genuine numeric measurements only (e.g. salary, invoice amounts; excludes identifier-like IDs, phones, PIN codes).
   - Metrics: count, min, max, mean, median, sample std deviation, Q1 (25th), Q3 (75th), IQR.
   - Bounded histograms (up to 10 bins: `bin_start`, `bin_end`, `count`).
4. **Categorical Distributions**:
   - Distinct value count, high cardinality warnings.
   - Top 10 frequencies with value, count, and percentage.
   - **Sensitive Data Redaction**: Columns classified as `SENSITIVE_PERSONAL_DATA` (Aadhaar, PAN, patient names) report distinct counts but redact raw value strings to `[REDACTED_SENSITIVE_VALUE]`.
5. **Time, Text & Data Quality**:
   - Datetime fields: parse success/failure counts, earliest/latest timestamps.
   - Text fields: min, max, and average string lengths.
   - Column normalization collisions detected.
   - Deterministic identifier pattern match counts (`EMAIL`, `PHONE_IN`, `PAN`, `AADHAAR`, `PINCODE`).
   - ETL issue counts by type (`MISSING`, `INVALID`, `DUPLICATE`, `REJECTED`).

---

## 3. Consolidated Inventory Catalog

- **Unified Schema & Source Overview** (`GET /api/v1/inventory/consolidated`):
  - Catalog of all registered sources with versions, timestamps, and row counts.
  - Column catalog with original source field names and normalized names.
  - **Category Coverage Matrix**: Maps which personal data categories appear across which dataset sources.
  - **Unresolved Cross-Source Matches**: Flags potential record links across sources (e.g. shared phone or email between clinical and billing datasets) as `UNRESOLVED` for human review. Never merges records based on weak identity heuristics.
- **Inventory Export** (`GET /api/v1/inventory/consolidated/export?format=json` or `?format=csv`):
  - Downloadable inventory data for compliance records and DPIA assessments.

---

## 4. Case-Specific Privacy Analysis (`GET /api/v1/inventory/privacy-analysis`)

- **Smart Personal Data Mapper**:
  - Breakdown of fields across DPDP sensitivity tiers (`SENSITIVE_PERSONAL_DATA`, `PERSONAL_DATA`, `NON_PERSONAL_DATA`).
  - Documented vs awaiting-review business purposes.
- **Privacy Leak Detector**:
  - Deterministic identifier matches combined with AI contextual classifications.
  - Legal disclaimer caveats.
- **Privacy Request Manager Summary**:
  - Case status breakdown (`RECEIVED`, `PENDING_REVIEW`, `IN_PROGRESS`, `FULFILLED`).
  - Statutory SLA deadline tracking (7 days for High, 15 for Medium, 30 for Low urgency).
- **Data Breach Response Assistant Summary**:
  - Incident tracking, 10-step regulatory checklist completion status, and evidence reference log.

---

## 5. API Endpoints Reference

### Data Ingestion & Inventory
- `GET /api/v1/inventory/supported-sources` — Lists supported formats and upload options.
- `POST /api/v1/inventory/upload` — Ingest file (`multipart/form-data`) with optional `source_type` and `sheet_name`.
- `GET /api/v1/inventory/datasets` — Lists all uploaded datasets with version and status.
- `GET /api/v1/inventory/datasets/{id}` — Full dataset details including column classifications and ETL issues.
- `GET /api/v1/inventory/datasets/{id}/eda-summary` — Complete 5-category EDA report.
- `GET /api/v1/inventory/datasets/{id}/identifier-findings` — Deterministic pattern validator results.
- `GET /api/v1/inventory/datasets/{id}/diff` — Version reconciliation diff (added, changed, removed, unchanged rows).
- `POST /api/v1/inventory/datasets/{id}/approve` — Owner approves dataset for production inventory.
- `POST /api/v1/inventory/datasets/{id}/reject` — Owner rejects dataset.
- `DELETE /api/v1/inventory/datasets/{id}/temp-file` — Explicit owner-approved staging file deletion.
- `GET /api/v1/inventory/consolidated` — Unified multi-source inventory catalog.
- `GET /api/v1/inventory/consolidated/export?format=json|csv` — Export consolidated catalog.
- `GET /api/v1/inventory/privacy-analysis` — Aggregated privacy governance analytics.
- `GET /api/v1/inventory/audit-logs` — Administrative audit event history.

### Privacy Requests & Breach Incidents
- `POST /api/v1/privacy-requests` — Ingest data principal rights request.
- `GET /api/v1/privacy-requests` — List requests (filter by status, urgency).
- `GET /api/v1/privacy-requests/{id}` — Full request case details.
- `PATCH /api/v1/privacy-requests/{id}/status` — Transition workflow status.
- `PATCH /api/v1/privacy-requests/{id}/checklist` — Update fulfillment checklist items.
- `POST /api/v1/incidents` — Create breach incident record.
- `GET /api/v1/incidents` — List breach incidents.
- `GET /api/v1/incidents/{ref}` — Full incident details.
- `PATCH /api/v1/incidents/{ref}/status` — Update incident status.
- `PATCH /api/v1/incidents/{ref}/checklist` — Update 10-step regulatory checklist.
- `POST /api/v1/incidents/{ref}/evidence` — Append evidence reference string.

---

## 6. Security, Privacy & Reliability Guardrails

1. **Transactional Rollback**: File uploads that fail parsing or validation roll back SQLite transactions and remove temporary staged files immediately, preventing orphaned records.
2. **Zero Raw PII Logging**: Loggers output only dataset IDs, counts, task names, and status strings. No raw spreadsheet values, emails, Aadhaar/PAN tokens, or chat lines are ever sent to log streams.
3. **Audit Logging**: Sensitive administrative actions (`UPLOAD_PROCESSED`, `DATASET_APPROVED`, `DATASET_REJECTED`, `TEMP_FILE_CLEANED`) are tracked in `audit_logs` table without PII in event details.
4. **Staging Isolation**: Uploads are staged in `uploads_temp/` and physically deleted only on explicit user request via `DELETE /api/v1/inventory/datasets/{id}/temp-file`.

---

## 7. Local OCR & Scanned Document Ingestion

### Technology & Licensing
- **PyMuPDF (`pymupdf`)**: PDF text extraction, document page rendering, and coordinate parsing. Licensed under GNU AGPL v3 (or commercial license).
- **Tesseract OCR (`tesseract`)**: Open-source local optical character recognition engine. Licensed under Apache 2.0.
- **`pytesseract`**: Python wrapper for Tesseract-OCR CLI. Licensed under Apache 2.0.
- **Pillow (`PIL`)**: Image validation and manipulation. Licensed under HPND (BSD/MIT compatible).
- **Strictly Local**: Zero cloud OCR APIs or external AI services are invoked.

### Windows Installation & Setup
1. **Download Tesseract Installer**:
   - Download the official Windows installer from [UB-Mannheim Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (e.g. `tesseract-ocr-w64-setup-5.x.exe`).
   - During installation, check the optional language packs for **Hindi (`hin`)** and **Kannada (`kan`)** if Indian regional script recognition is required.
   - Default install path: `C:\Program Files\Tesseract-OCR\tesseract.exe`.
2. **Configure Environment Variable**:
   - If installed in standard location `C:\Program Files\Tesseract-OCR\tesseract.exe`, the application auto-detects it.
   - Alternatively, set in `.env`:
     ```env
     TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
     TESSDATA_PREFIX=C:\Program Files\Tesseract-OCR\tessdata
     ```
3. **Verify Language Data**:
   - Run `tesseract --list-langs` in terminal.
   - Available language models should list `eng`, and optionally `hin` and `kan`.

### Two-Stage PDF Extraction Rule
1. **Native Text Extraction**: Attempt native text extraction via PyMuPDF.
2. **Sufficiency Check**: Count alphanumeric characters and words. If $\ge 50$ characters and $\ge 5$ words, native text is deemed sufficient and preserved with $1.0$ confidence.
3. **OCR Fallback**: If native text is insufficient ($< 50$ chars), the page is rendered at 200 DPI and processed through local Tesseract OCR.
4. **Blank/Failed Reporting**: Pages with 0 text are marked `EMPTY`. Pages where OCR fails are marked `FAILED`. No pages are silently skipped.

---

## 8. Running Tests & Verification

Run the complete test suite:
```bash
.venv\Scripts\python.exe -m pytest -v --tb=short
```

Run dataset generator validation suite:
```bash
.venv\Scripts\python.exe sample_data/validate_datasets.py
```
