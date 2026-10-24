# AI / SLM Module (`ai/`)

This module implements local-first on-device privacy compliance intelligence for small businesses in India under the **DPDP Act, 2023** and **IT Act, 2000**.

All inference runs strictly against a **local [Ollama](https://ollama.com/) server** (`http://127.0.0.1:11434`) or in deterministic **Mock Mode**. Cloud AI endpoints are blocked at configuration validation time.

---

## Module Structure

```text
ai/
├── __init__.py              # Public API exports (functions, config, Pydantic models)
├── config.py                # AIConfig (local URL enforcement, retries, mock mode, language)
├── models.py                # Pydantic v2 schemas matching contracts/AI_BACKEND_CONTRACT.md
├── client.py                # Local-only Ollama HTTP client with bounded retries & validation
├── safety.py                # Untrusted input wrapping, prompt-injection defense, zero-PII logger
├── i18n.py                  # English ('en'), Hindi ('hi'), and Kannada ('kn') explanation templates
├── classifier.py            # Task 1: classify_columns
├── findings.py              # Task 2: contextual_privacy_findings
├── requests_classifier.py   # Task 3: classify_privacy_request
└── breach_extractor.py      # Task 4: extract_breach_details
```

---

## Setup Instructions

### 1. Local Ollama Setup (Live Mode)
1. Install [Ollama](https://ollama.com/) on the local machine.
2. Pull a compact instruction-tuned SLM suitable for local CPU/GPU hardware:
   ```bash
   ollama pull qwen2.5:3b
   # or: ollama pull llama3.2:3b
   ```
3. Verify the local server is running on loopback (`127.0.0.1:11434`):
   ```bash
   ollama serve
   ```

### 2. Mock Mode (CI / Development Without Ollama)
Set `AI_MOCK_MODE=true` (or pass `AIConfig(mock_mode=True)` in Python) to get deterministic synthetic responses matching `contracts/AI_BACKEND_CONTRACT.md` without a running Ollama server.

---

## Model Configuration (`AIConfig`)

Configuration is loaded via `ai.config.AIConfig` from environment variables or constructor arguments:

| Environment Variable | Field | Default | Description |
|---|---|---|---|
| `OLLAMA_BASE_URL` | `ollama_base_url` | `http://127.0.0.1:11434` | Local Ollama URL (`localhost` / `127.0.0.1` / `::1` only; cloud URLs raise `ValidationError`) |
| `OLLAMA_MODEL` | `model_name` | `qwen2.5:3b` | Local Ollama model tag |
| `AI_MOCK_MODE` | `mock_mode` | `false` | Set `true` for deterministic synthetic responses |
| `AI_TIMEOUT_SECONDS` | `timeout_seconds` | `15.0` | Per-attempt HTTP timeout in seconds (`1.0`–`120.0`) |
| `AI_MAX_RETRIES` | `max_retries` | `2` | Bounded retries on invalid JSON/schema or transient timeout (`0`–`5`) |
| `AI_TEMPERATURE` | `temperature` | `0.0` | Sampling temperature (`0.0` for deterministic structured JSON) |
| `AI_DEFAULT_LANGUAGE` | `default_language` | `en` | Default explanation language (`en`, `hi`, `kn`) |
| `AI_FALLBACK_ON_ERROR` | `fallback_on_model_error` | `true` | If `true`, falls back to safe deterministic assessment with `needs_human_review=True` when Ollama fails after retries; if `false`, returns `"status": "error"` envelope |

---

## How the Backend Calls the AI Module

The backend (`backend/`) imports the four stateless functions directly from `ai`. Each function accepts either a Python `dict` (matching `contracts/AI_BACKEND_CONTRACT.md`) or its corresponding Pydantic request model, and returns a validated Pydantic response model (serializable via `.model_dump(exclude_none=True)`).

```python
from ai import (
    AIConfig,
    classify_columns,
    contextual_privacy_findings,
    classify_privacy_request,
    extract_breach_details,
)

# Use mock_mode=True for local dev/tests, or mock_mode=False for live local Ollama
config = AIConfig(mock_mode=True)

# 1. Classify Columns (Backend passes deterministic_signals & masked_samples)
col_response = classify_columns(
    {
        "schema_version": "1.0",
        "request_id": "req_col_9001",
        "task": "classify_columns",
        "dataset_context": {
            "dataset_id": "ds_402",
            "dataset_name": "patient_onboarding_v2.csv",
            "business_domain": "diagnostic_clinic",
        },
        "columns": [
            {
                "column_name": "kyc_pan_card",
                "inferred_data_type": "string",
                "null_ratio": 0.05,
                "deterministic_signals": ["PAN_PATTERN"],
                "masked_samples": ["ABCDE1234F"],
            }
        ],
        "language": "en",  # Supports "en", "hi" (Hindi), "kn" (Kannada)
    },
    config=config,
)
print(col_response.model_dump(exclude_none=True))

# 2. Contextual Privacy Findings
findings_response = contextual_privacy_findings(
    {
        "schema_version": "1.0",
        "request_id": "req_find_9002",
        "task": "contextual_privacy_findings",
        "dataset_metadata": {
            "dataset_id": "ds_510",
            "dataset_name": "festive_coupon_signups.csv",
            "business_purpose": "promotional_discount_newsletter",
            "stated_retention_days": None,
            "has_consent_notice_linked": False,
            "access_scope": "ALL_STAFF",
            "third_party_sharing": True,
        },
        "classified_columns": [
            {
                "column_name": "aadhaar_number",
                "data_category": "GOVERNMENT_ID",
                "specific_identifier_type": "AADHAAR",
                "sensitivity_tier": "CRITICAL_PERSONAL",
            }
        ],
        "version_diff_summary": {
            "added_columns": ["aadhaar_number"],
            "removed_columns": [],
            "tier_escalations": [],
        },
    },
    config=config,
)

# 3. Classify Privacy Request
request_response = classify_privacy_request(
    {
        "schema_version": "1.0",
        "request_id": "req_dsr_9003",
        "task": "classify_privacy_request",
        "case_id": "case_2026_0041",
        "channel": "EMAIL",
        "received_at": "2026-10-24T14:20:00+05:30",
        "requester_role_hint": "CUSTOMER",
        "identity_verified_by_backend": False,
        "request_text": "Please delete all my personal records and tell me which third parties have my phone number.",
    },
    config=config,
)

# 4. Extract Breach Details
breach_response = extract_breach_details(
    {
        "schema_version": "1.0",
        "request_id": "req_inc_9004",
        "task": "extract_breach_details",
        "incident_id": "inc_2026_0009",
        "reported_at": "2026-10-24T18:00:00+05:30",
        "reporter_role": "STORE_MANAGER",
        "incident_narrative": "Billing operator accidentally emailed oct_kyc_billing.xlsx with 450 customer PAN and phone numbers to an external vendor list.",
    },
    config=config,
)
```

---

## Safety & Guardrails Summary

- **No Cloud Calls:** `AIConfig` rejects any non-local hostname.
- **Untrusted Input Isolation:** All uploaded dataset strings, sample tokens, request texts, and incident narratives are wrapped in `<untrusted_data>` blocks and scanned for prompt injection and SQL/command injection (`SAFETY_POLICY_BLOCKED`).
- **No Side Effects:** The module never executes SQL, modifies/deletes files, sends emails, or shuts down systems. Any model output containing SQL/shell syntax is blocked.
- **Zero-PII Logging:** `RedactingLogFilter` strips PAN, Aadhaar, phone numbers, emails, prompts, and sample values from all log records.
- **Mandatory Human Review:** `needs_human_review=True` is strictly enforced on low confidence, conflicts, sensitive categories, actionable privacy requests, all breach extractions, and any fallback/error path.

---

## Running Tests

```bash
python -m pytest tests/ -v
```
