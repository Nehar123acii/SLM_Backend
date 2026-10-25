# Kavach DPDP Backend — Complete Implementation Summary

This document provides a comprehensive, technical summary of all features, architecture components, security controls, database schemas, and test suites implemented in the Kavach DPDP backend repository.

---

## 1. Executive Technical Overview

- **Core Stack**: FastAPI, SQLAlchemy 2.0 ORM, SQLite (WAL mode + Foreign Keys enabled), Pydantic v2, PyMuPDF, Tesseract OCR, pytest.
- **Privacy Model**: Local-first compliance engine designed for small and medium businesses under India's Digital Personal Data Protection (DPDP) Act, 2023.
- **Current Test Suite**: **90 passed, 2 skipped** (100% passing rate on active tests).
- **Core Security Rule**: **Zero raw personal data persistence**. All personal data identifiers (phones, emails, Aadhaar, PAN, names) are strictly pseudonymized using keyed HMAC-SHA256 and masked before persistence.

---

## 2. Key Architecture Components & Implemented Tasks

```mermaid
flowchart TD
    subgraph Ingestion ["1. Multi-Source Ingestion & OCR"]
        CSV[CSV / TSV]
        XLSX[Multi-sheet Excel]
        Forms[Google Forms CSV]
        WA[WhatsApp Chat TXT]
        JSON_in[Nested JSON]
        OCR_in[Scanned PDFs & Images]
    end

    subgraph Processing ["2. ETL, Normalization & Security"]
        Cleaner[Column & String Normalizer]
        HMAC[Keyed HMAC-SHA256<br/>backend/security.py]
        Detect[PII & Identifier Checkers<br/>Verhoeff & Luhn Validation]
    end

    subgraph Resolution ["3. Provenance & Entity Resolution"]
        Prov[Occurrences & Locators<br/>file|sheet|col or file|bbox]
        UF[Union-Find Disjoint Set<br/>Strong & Probable Matching]
        People[People & Person Records]
    end

    subgraph Persistence ["4. SQLite Database (WAL Mode)"]
        DB[(kavach.db)]
    end

    subgraph RulesEngine ["5. Ported Foundations & DPDP Rules"]
        YAML[rules.yaml / intents.yaml<br/>retention.yaml / breach_scenarios.yaml]
        Config[Statutory Constants<br/>RESPONSE_DAYS=30 / BREACH_72H]
        NewModels[QuestionnaireAnswer<br/>BreachSimulation<br/>EvidencePack<br/>LedgerTamperBackup]
    end

    Ingestion --> Processing
    Processing --> Resolution
    Resolution --> Persistence
    RulesEngine --> Persistence
```

---

## 3. Detailed Breakdown of Completed Tasks

### Task 1: Multi-Source Privacy Data Ingestion & Consolidated EDA
- **Supported Formats**: CSV, multi-sheet Excel (.xlsx), Google Forms export CSVs, WhatsApp export chats (.txt), and nested JSON records.
- **Cleaning & Normalization**:
  - Whitespace trimming, header sanitization (snake_case conversion), deduplication.
  - Preservation of identifiers with leading zeros (e.g., phone numbers and Aadhaar strings).
  - Ambiguous date parsing with UTC timestamp normalization.
- **Consolidated EDA Engine**:
  - Calculates dimensions, inferred data types, null counts, distinct counts, exact duplicate rows, and categorical distributions.
  - Generates cross-source reconciliation metrics and dataset version diffs.

---

### Task 2: Local OCR & Scanned Document Ingestion
- **Engine**: PyMuPDF (`fitz`) for PDF parsing and local Tesseract OCR engine (`pytesseract`) for image recognition.
- **Strict Local Execution**: Enforces local processing only; zero data leaves the host.
- **Feature Set**:
  - Dual-mode PDF processing: extracts native digital text; switches to Tesseract OCR when raster scanned pages are detected.
  - Supported Image Formats: PNG, JPG, JPEG, TIFF, BMP.
  - Granular Spatial Locators: `file.pdf|page_1_bbox_120_340_200_30` preserving exact spatial coordinates on scanned documents.
  - Lineage & Confidence Tracking: Records OCR word confidence levels (`ocr_conf`) and origin metadata (`origin='ocr'`).

---

### Task 3: Real Ollama SLM Integration
- **Client Implementation**: Integrated Ollama client (`backend/ai_client/ollama_client.py`) with fallback to contract-compliant mock client (`backend/ai_client/mock_client.py`).
- **4 DPDP Compliance Tasks**:
  1. `classify_columns`: Identifies data principal segments (Customer, Employee, Vendor) and legal basis (e.g., s.4 Consent, s.7 Certain Legitimate Uses).
  2. `contextual_privacy_findings`: Assesses cross-table data sprawl, sensitive category co-occurrence, and high-impact risks.
  3. `classify_privacy_request`: Categorizes incoming requests into Erasure, Access, Correction, or Grievance Redressal.
  4. `extract_breach_details`: Extracts impacted data categories, estimated principal counts, and regulatory risk severity.
- **Security & Reliability**:
  - Enforces local-only endpoint binding (`localhost`, `127.0.0.1`).
  - Exponential backoff with jitter and graceful schema-conforming fallback envelopes.

---

### Task K1: SQLite Everywhere & Cryptographic Keyed Hashing
- **Database Engine Consolidation**:
  - Pure SQLite database (`sqlite:///data/kavach.db`), configurable via `KAVACH_DATA_DIR`.
  - Configured with `connect_args={"check_same_thread": False}`.
  - WAL journal mode (`PRAGMA journal_mode = WAL`) and foreign key enforcement (`PRAGMA foreign_keys = ON`).
  - Added clean resource disposal via `dispose_engine()` for clean teardown on Windows.
- **Cryptographic Hashing (`backend/security.py`)**:
  - Replaced plain salted SHA-256 with HMAC-SHA256 using secret key persisted to `data/.key` or `KAVACH_KEY`.
  - Normalization before hashing:
    - Phone: canonical E.164 without prefix (last 10 digits).
    - Email: lowercase, trimmed.
    - Aadhaar: 12 stripped digits validated via Verhoeff checksum.
    - PAN: uppercase 10-character alphanumeric validated via regex.
    - Name: case-folded, trimmed string.
- **Zero Raw PII Persistence Verification**:
  - Dedicated automated test (`tests/test_no_raw_values.py`) ingests known sentinel values and inspects the raw binary bytes of the SQLite database and WAL files, verifying zero unmasked strings exist on disk.

---

### Task K2: Provenance Tracking & Entity Resolution
- **Granular Locators**:
  - Tabular / Chat format: `filename|sheet_name|column_name` or `filename|line_N`.
  - Scanned OCR format: `filename|page_N_bbox_X_Y_W_H`.
- **Impact Tiers & Categorization**:
  - Categorizes identifiers: `phone`, `email`, `aadhaar`, `pan`, `name`, `dob`, `address`, `health`, `other`.
  - Assigns Kavach leakage impact tiers: Tier 1 (Aadhaar, Health, Bank), Tier 2 (Phone, Email, PAN), Tier 3 (Name, General).
- **`occurrences` Table**:
  - Tracks individual observations: `person_id`, `column_id`, `row_ref`, `masked_sample`, `value_hmac`, `origin` (`rule` or `ocr`), `ocr_conf`.
- **Entity Resolution Engine (`backend/services/provenance.py`)**:
  - Uses Disjoint-Set Union (Union-Find).
  - **Strong Match**: Shared HMAC for phone, email, or Aadhaar $\rightarrow$ merged with `resolution='strong'` and `confidence=1.0`.
  - **Probable Match**: Name-only match $\rightarrow$ tagged as `resolution='probable'` with `confidence=0.7`.
  - Updates consolidated `people` records and populates `cross_source_matches`.

---

### Task K0: Prototype Port Mapping Specification
- **Deliverable**: Generated [`docs/PORT_MAP.md`](file:///c:/Users/nehar/OneDrive/Documents/GitHub/SLM_Backend/docs/PORT_MAP.md).
- **Scope**: Inspected all 21 files in the legacy Flask prototype (`reference_mannat/app/`).
- **Classification**:
  - **PORT AS IS**: Static YAML definitions (`rules.yaml`, `intents.yaml`, `retention.yaml`, `breach_scenarios.yaml`).
  - **PORT AND ADAPT**: Business engines (`rules.py`, `ledger.py`, `erasure.py`, `breach.py`, `reports.py`, REST routes, evaluation benchmarks).
  - **MERGE**: Adapters, schema models, and detection regexes.
  - **SKIP**: Flask lifecycle wrappers and empty stubs (`__init__.py`, `db.py`, `llm.py`).
- **Roadmap**: Established strict 11-step dependency graph.

---

### Task K4: Porting Foundations
- **Part A (Rule Assets)**:
  - Deployed `rules.yaml`, `intents.yaml`, `breach_scenarios.yaml`, and `retention.yaml` into `backend/rules/`.
  - Enforced `verify: true` and `verified: false` across all 12 compliance rules and every retention source/field policy.
- **Part B (Statutory Constants)**:
  - Added statutory constants to [`backend/config.py`](file:///c:/Users/nehar/OneDrive/Documents/GitHub/SLM_Backend/backend/config.py):
    - `RESPONSE_DAYS = 30` (UNVERIFIED, shown as "verify" in the UI).
    - `BREACH_STAGE_1_DESCRIPTION = "without delay"`.
    - `BREACH_STAGE_2_HOURS = 72`.
- **Part C (SQLAlchemy Data Models)**:
  - Added new models to [`backend/db/models.py`](file:///c:/Users/nehar/OneDrive/Documents/GitHub/SLM_Backend/backend/db/models.py) and exported in [`backend/db/__init__.py`](file:///c:/Users/nehar/OneDrive/Documents/GitHub/SLM_Backend/backend/db/__init__.py):
    1. `QuestionnaireAnswer` (`questionnaire`): Operational assessment answers (`key`, `answer`).
    2. `BreachSimulation` (`breach_simulations`): Simulated incident blast-radius runs and draft intimation notices.
    3. `EvidencePack` (`evidence_packs`): Exported compliance audit zip packages and ledger head hashes.
    4. `LedgerTamperBackup` (`ledger_tamper_backup`): Ledger event snapshots for demonstrating cryptographic tamper detection.
  - Formulated the exact structural difference report between `LedgerEvent` and `ledger.py`.
- **Verification**: Created [`tests/test_foundations.py`](file:///c:/Users/nehar/OneDrive/Documents/GitHub/SLM_Backend/tests/test_foundations.py) (4 tests passing).

---

## 4. Complete Database Schema Summary

| Table Name | SQLAlchemy Model | Purpose / Contents | Stored Identifiers |
| :--- | :--- | :--- | :--- |
| `datasets` | `Dataset` | Uploaded file metadata, versioning, ingestion lifecycle status, and EDA summary | File names, row/col counts, status |
| `columns` | `Column` | Schema column definitions, inferred data types, AI classification, DPDP legal bases | Column headers, locators, impact tiers |
| `etl_issues` | `ETLIssue` | Parsing anomalies, type mismatches, rejected row indices | Row numbers, issue descriptions |
| `identifier_findings` | `IdentifierFinding` | Deterministic identifier detections per column | Column ID, category, flag codes |
| `people` | `Person` | Consolidated Data Principals resolved via Union-Find | `masked_name`, `name_hmac`, resolution status |
| `occurrences` | `Occurrence` | Provenance link between a person, dataset column, and source row/bounding box | `masked_sample`, `value_hmac`, `origin`, `ocr_conf` |
| `cross_source_matches` | `CrossSourceMatch` | Records linking common entities across diverse sources | Source names, match types, confidence |
| `privacy_requests` | `PrivacyRequest` | Data Principal rights requests (Erasure, Access, Rectification) | Request status, intent, dates |
| `incidents` | `Incident` | Recorded privacy breach incidents | Title, severity, status, timestamps |
| `questionnaire` | `QuestionnaireAnswer` | DPDP operational readiness questionnaire answers | Keys (`cctv`, `vendors`, etc.) & answers |
| `breach_simulations` | `BreachSimulation` | Blast-radius simulation records and draft notification letters | Scenario IDs, aggregate counts, draft texts |
| `evidence_packs` | `EvidencePack` | Audit evidence package exports with cryptographic head hashes | Pack IDs, score, chain status, zip path |
| `ledger_tamper_backup`| `LedgerTamperBackup` | Snapshot of ledger events to simulate and demonstrate tampering & repair | Event payloads, hashes, timestamps |
| `ledger_events` | `LedgerEvent` | Tamper-evident append-only cryptographic event chain | Sequence, event type, canonical JSON, SHA-256 hash |
| `flag_results` | `FlagResult` | DPDP rule evaluation results and compliance findings | Rule ID, run ID, state (`GREEN`/`YELLOW`/`RED`) |
| `purposes` | `Purpose` | Permitted DPDP business processing purpose catalog | Purpose keys, descriptions |
| `purpose_links` | `PurposeLink` | Map between data columns, principal segments, and purposes | Column ID, segment, status |
| `business_state` | `BusinessState` | Tracks application heartbeat and data activity timestamps | Timestamps |

---

## 5. Verification & Test Suite Status

Running the complete test suite:
```powershell
.\.venv\Scripts\python.exe -m pytest
```

### Results Summary
- **Total Test Cases**: 92
- **Passed**: 90
- **Skipped**: 2 (optional live Ollama network tests, requiring a running Ollama daemon)
- **Failed**: 0
- **Execution Time**: ~5.2 seconds

### Test Coverage by Domain
1. `tests/test_foundations.py`: YAML parsing, verify/verified integrity, DPDP constants, new table row insertion.
2. `tests/test_no_raw_values.py`: Binary SQLite/WAL inspection for zero plain-text personal identifiers.
3. `tests/test_security.py`: Normalization and HMAC-SHA256 generation for phone, email, Aadhaar, PAN, name.
4. `tests/test_provenance.py`: Multi-source occurrences, locators, and Union-Find entity resolution.
5. `tests/test_ocr_ingestion.py`: PyMuPDF and Tesseract extraction, image bounding boxes, confidence scores.
6. `tests/test_multi_source_ingestion.py`: CSV, Excel, Google Forms, WhatsApp text, and JSON ingestion.
7. `tests/test_ai_client.py`: Ollama integration, retry/fallback behavior, local URL restrictions.
8. `tests/test_eda_and_consolidation.py`: Summary statistics, type inference, duplicate row detection.
9. `tests/test_schema_v2.py`, `test_upload_etl.py`, `test_versioning.py`, `test_incidents.py`, `test_privacy_requests.py`: API endpoints and core workflows.
