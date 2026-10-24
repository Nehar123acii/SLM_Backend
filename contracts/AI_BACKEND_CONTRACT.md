# AI ↔ Backend Contract

**Version:** 0.1.0  
**Status:** Draft — awaiting review by AI lead and Backend lead  
**Last updated:** 2026-10-24

This document is the single source of truth for every call the backend makes into the
AI module.  It is language-neutral: all shapes are described as JSON; both sides must
honour them exactly.

> [!IMPORTANT]
> **Hard constraints on the AI module (non-negotiable)**
> - The model MUST NOT execute SQL or issue database write commands.
> - The model MUST NOT delete, overwrite, or move any stored data.
> - The model MUST NOT send emails, webhooks, or external HTTP requests.
> - The model MUST NOT shut down or restart any system process.
> - Raw personal data (real names, real Aadhaar numbers, real phone numbers, etc.)
>   MUST NOT appear in logs, traces, or prompt caches.  Pass only anonymised
>   or synthetic values during development and testing.

> [!NOTE]
> **Division of responsibility**
>
> | Concern | Owner |
> |---|---|
> | File upload, virus scan, storage | Backend |
> | ETL, normalisation, column-type inference | Backend |
> | Deterministic identifier validation (Luhn, Aadhaar checksum, PAN regex) | Backend |
> | Database persistence and version history | Backend |
> | Privacy-request case management (status, deadlines) | Backend |
> | Breach incident records and audit log | Backend |
> | Authentication, authorisation, rate-limiting | Backend |
> | Contextual data classification, explanations | AI module |
> | Privacy-issue detection and risk reasoning | AI module |
> | Privacy-request intent classification | AI module |
> | Breach-detail extraction from free text | AI module |

---

## Common envelope

Every AI call uses the same request/response envelope.

### Request envelope

```json
{
  "task":    "<task_name>",
  "version": "1",
  "payload": { }
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `task` | string | ✅ | One of the task names in this document |
| `version` | string | ✅ | Contract version the caller is using (currently `"1"`) |
| `payload` | object | ✅ | Task-specific fields — see each task section |

### Response envelope

```json
{
  "task":                "<task_name>",
  "version":             "1",
  "status":              "ok",
  "needs_human_review":  false,
  "result":              { },
  "warnings":            [],
  "error":               null
}
```

| Field | Type | Notes |
|---|---|---|
| `task` | string | Echoed from the request |
| `version` | string | Contract version used by the AI module |
| `status` | `"ok"` \| `"error"` | Top-level outcome |
| `needs_human_review` | boolean | `true` forces the backend to route the result to a human queue before any automated action is taken |
| `result` | object \| `null` | Populated when `status` is `"ok"`; `null` on error |
| `warnings` | array of string | Non-fatal observations (e.g. low-confidence predictions) |
| `error` | object \| `null` | Populated when `status` is `"error"`; `null` on success |

### Error object

```json
{
  "code":    "UNSUPPORTED_LANGUAGE",
  "message": "Human-readable explanation safe to log"
}
```

**Standard error codes**

| Code | Meaning |
|---|---|
| `INVALID_INPUT` | A required field is missing or has a wrong type |
| `UNSUPPORTED_LANGUAGE` | Column headers or text are in a language the model cannot handle |
| `CONTEXT_TOO_LONG` | Payload exceeds the model's context window |
| `LOW_CONFIDENCE` | Model confidence is below the acceptable threshold; treat result as unreliable |
| `MODEL_UNAVAILABLE` | Ollama server did not respond |
| `INTERNAL_ERROR` | Unexpected error inside the AI module |

---

## Task 1 — `classify_columns`

**Purpose:** Given a list of dataset column descriptors (name, sample values, data type)
already cleaned by the backend's ETL pipeline, the AI module returns a privacy
classification for each column.

> [!NOTE]
> The backend performs deterministic Aadhaar/PAN/phone-number format checks
> **before** calling this task.  The AI module adds contextual reasoning on top.

### `needs_human_review` triggers

`needs_human_review` MUST be `true` when:
- Any column has `confidence` < `0.70`.
- Any column is classified `SENSITIVE_PERSONAL_DATA`.
- The model detects a column that looks like a unique biometric identifier.

### Request payload

| Field | Type | Required | Notes |
|---|---|---|---|
| `dataset_id` | string | ✅ | Opaque ID assigned by the backend (no PII) |
| `columns` | array | ✅ | 1–200 column descriptors |
| `columns[].name` | string | ✅ | Column header as it appears in the file |
| `columns[].inferred_type` | string | ✅ | Backend's ETL type hint — see permitted values |
| `columns[].sample_values` | array of string | ✅ | 3–5 synthetic/anonymised sample values |
| `columns[].description` | string | ❌ | Optional human note about the column |

**Permitted `inferred_type` values**

`TEXT` · `INTEGER` · `FLOAT` · `DATE` · `DATETIME` · `BOOLEAN` · `EMAIL` · `PHONE` · `URL` · `UNKNOWN`

### Response result

| Field | Type | Notes |
|---|---|---|
| `classifications` | array | One entry per input column, same order |
| `classifications[].column_name` | string | Echoed from input |
| `classifications[].category` | string | See permitted values |
| `classifications[].sensitivity` | string | See permitted values |
| `classifications[].confidence` | float | 0.0 – 1.0 |
| `classifications[].explanation` | string | ≤ 200 chars, safe to display |
| `classifications[].dpdp_basis` | string \| `null` | Relevant DPDP Act clause if applicable, e.g. `"Section 2(t)"` |

**Permitted `category` values**

| Value | Meaning |
|---|---|
| `IDENTITY` | Name, date of birth, gender, photograph |
| `GOVERNMENT_ID` | Aadhaar, PAN, Voter ID, Passport, Driving Licence |
| `CONTACT` | Address, email, phone number |
| `FINANCIAL` | Bank account, credit card, salary, transaction |
| `HEALTH` | Medical record, diagnosis, prescription |
| `BIOMETRIC` | Fingerprint, iris, face geometry |
| `LOCATION` | GPS coordinates, IP address, device ID |
| `BEHAVIOURAL` | Browsing history, purchase pattern, usage log |
| `EMPLOYMENT` | Job title, employer, performance review |
| `NON_PERSONAL` | Data that cannot identify a natural person |
| `UNCERTAIN` | Model is not confident enough to categorise |

**Permitted `sensitivity` values**

| Value | Meaning |
|---|---|
| `SENSITIVE_PERSONAL_DATA` | DPDP Act special category / IT Rules Schedule II |
| `PERSONAL_DATA` | Identifiable but not in the sensitive category |
| `NON_PERSONAL_DATA` | Cannot identify a natural person |

### Synthetic example

**Request**
```json
{
  "task": "classify_columns",
  "version": "1",
  "payload": {
    "dataset_id": "ds_20261024_001",
    "columns": [
      {
        "name": "customer_name",
        "inferred_type": "TEXT",
        "sample_values": ["Rahul Sharma", "Priya Nair", "Amit Desai"],
        "description": "Full name of the customer"
      },
      {
        "name": "aadhar_last4",
        "inferred_type": "INTEGER",
        "sample_values": ["1234", "5678", "9012"],
        "description": "Last 4 digits of Aadhaar, stored for verification"
      },
      {
        "name": "purchase_amount_inr",
        "inferred_type": "FLOAT",
        "sample_values": ["499.00", "1299.50", "89.99"],
        "description": null
      }
    ]
  }
}
```

**Response**
```json
{
  "task": "classify_columns",
  "version": "1",
  "status": "ok",
  "needs_human_review": true,
  "result": {
    "classifications": [
      {
        "column_name": "customer_name",
        "category": "IDENTITY",
        "sensitivity": "PERSONAL_DATA",
        "confidence": 0.97,
        "explanation": "Full name directly identifies a natural person.",
        "dpdp_basis": "Section 2(t)"
      },
      {
        "column_name": "aadhar_last4",
        "category": "GOVERNMENT_ID",
        "sensitivity": "SENSITIVE_PERSONAL_DATA",
        "confidence": 0.91,
        "explanation": "Partial Aadhaar number is still a government identifier fragment.",
        "dpdp_basis": "Section 2(t), IT Rules Schedule II"
      },
      {
        "column_name": "purchase_amount_inr",
        "category": "FINANCIAL",
        "sensitivity": "PERSONAL_DATA",
        "confidence": 0.82,
        "explanation": "Transaction amount linked to a customer record is personal financial data.",
        "dpdp_basis": null
      }
    ]
  },
  "warnings": [],
  "error": null
}
```

> `needs_human_review` is `true` because `aadhar_last4` is `SENSITIVE_PERSONAL_DATA`.

---

## Task 2 — `contextual_privacy_findings`

**Purpose:** Given a description of a data flow or processing activity (supplied as
structured metadata by the backend), the AI module identifies privacy issues and
explains them in plain language suitable for a non-lawyer business owner.

> [!NOTE]
> The backend is responsible for building this metadata from its data-asset catalogue.
> The AI module does not query the database directly.

### `needs_human_review` triggers

`needs_human_review` MUST be `true` when:
- Any finding has `severity` of `HIGH` or `CRITICAL`.
- The model detects cross-border data transfer of sensitive personal data.
- Total number of findings is ≥ 5.

### Request payload

| Field | Type | Required | Notes |
|---|---|---|---|
| `activity_id` | string | ✅ | Opaque ID for this processing activity |
| `activity_name` | string | ✅ | Human-readable label, e.g. `"Customer loyalty programme"` |
| `purpose` | string | ✅ | Declared purpose of processing, ≤ 500 chars |
| `data_categories` | array of string | ✅ | Categories from `classify_columns` permitted values |
| `recipients` | array of string | ❌ | Who the data is shared with (role labels, no personal names) |
| `retention_days` | integer \| `null` | ❌ | How long data is kept; `null` means unspecified |
| `cross_border` | boolean | ✅ | Whether data leaves India |
| `consent_collected` | boolean | ✅ | Whether explicit consent is obtained |
| `legal_basis` | string \| `null` | ❌ | Claimed legal basis, e.g. `"Legitimate use"`, `"Consent"` |

### Response result

| Field | Type | Notes |
|---|---|---|
| `findings` | array | May be empty if no issues are found |
| `findings[].finding_id` | string | Stable short ID, e.g. `"F-001"` |
| `findings[].title` | string | ≤ 80 chars |
| `findings[].description` | string | Plain-language explanation, ≤ 500 chars |
| `findings[].severity` | string | See permitted values |
| `findings[].category` | string | See permitted values |
| `findings[].recommendation` | string | Actionable suggestion, ≤ 300 chars |
| `findings[].dpdp_reference` | string \| `null` | Applicable DPDP / IT Act clause |
| `summary` | string | 1–3 sentence plain-language summary of overall risk |

**Permitted `severity` values** (ascending risk)

`INFORMATIONAL` · `LOW` · `MEDIUM` · `HIGH` · `CRITICAL`

**Permitted `category` values**

`CONSENT` · `DATA_MINIMISATION` · `RETENTION` · `CROSS_BORDER_TRANSFER` · `PURPOSE_LIMITATION` · `SECURITY` · `RIGHTS_FACILITATION` · `TRANSPARENCY` · `OTHER`

### Synthetic example

**Request**
```json
{
  "task": "contextual_privacy_findings",
  "version": "1",
  "payload": {
    "activity_id": "act_20261024_007",
    "activity_name": "Monthly newsletter send",
    "purpose": "Send promotional emails to customers who purchased in the last 90 days.",
    "data_categories": ["CONTACT", "BEHAVIOURAL", "IDENTITY"],
    "recipients": ["email_service_provider"],
    "retention_days": null,
    "cross_border": true,
    "consent_collected": false,
    "legal_basis": null
  }
}
```

**Response**
```json
{
  "task": "contextual_privacy_findings",
  "version": "1",
  "status": "ok",
  "needs_human_review": true,
  "result": {
    "findings": [
      {
        "finding_id": "F-001",
        "title": "No consent basis for marketing emails",
        "description": "Sending promotional emails requires a valid legal basis under the DPDP Act. No consent or other recognised basis has been specified.",
        "severity": "HIGH",
        "category": "CONSENT",
        "recommendation": "Collect explicit opt-in consent before adding customers to the newsletter list, and provide a clear unsubscribe mechanism.",
        "dpdp_reference": "Section 6, DPDP Act 2023"
      },
      {
        "finding_id": "F-002",
        "title": "No data retention limit defined",
        "description": "Retention period is unspecified. Data should not be kept longer than necessary for the stated purpose.",
        "severity": "MEDIUM",
        "category": "RETENTION",
        "recommendation": "Define and enforce a maximum retention period; delete or anonymise records after that period.",
        "dpdp_reference": "Section 8(7), DPDP Act 2023"
      },
      {
        "finding_id": "F-003",
        "title": "Cross-border transfer to email service provider",
        "description": "Contact and identity data is being shared with an external email provider potentially outside India without a documented transfer safeguard.",
        "severity": "HIGH",
        "category": "CROSS_BORDER_TRANSFER",
        "recommendation": "Verify whether the provider's servers are in India or in a government-approved jurisdiction; document the safeguard.",
        "dpdp_reference": "Section 16, DPDP Act 2023"
      }
    ],
    "summary": "This activity has two HIGH-severity issues: missing consent and undocumented cross-border transfer. Immediate action is recommended before the next send."
  },
  "warnings": [],
  "error": null
}
```

> `needs_human_review` is `true` because two findings have severity `HIGH`.

---

## Task 3 — `classify_privacy_request`

**Purpose:** Given the raw text of a data principal's rights request (e.g. submitted
via a web form), the AI module identifies the request type(s), the likely data subject,
and whether the text is clear enough for automated processing.

> [!NOTE]
> The backend owns case creation, SLA timers, identity verification, and fulfilment
> workflow.  The AI module only interprets the natural-language text.

### `needs_human_review` triggers

`needs_human_review` MUST be `true` when:
- `confidence` < `0.75`.
- More than one request type is detected (`is_composite` is `true`).
- `urgency` is `HIGH` (e.g. text mentions legal action or regulatory complaint).
- The text contains apparent threats or distressing content.

### Request payload

| Field | Type | Required | Notes |
|---|---|---|---|
| `request_id` | string | ✅ | Opaque ID assigned by the backend |
| `raw_text` | string | ✅ | Verbatim text submitted by the data principal; ≤ 5 000 chars |
| `submission_channel` | string | ❌ | `"web_form"` \| `"email"` \| `"walk_in"` \| `"other"` |
| `language_hint` | string | ❌ | BCP-47 language tag, e.g. `"en"`, `"hi"`, `"ta"` |

### Response result

| Field | Type | Notes |
|---|---|---|
| `request_types` | array of string | One or more values from the permitted list |
| `is_composite` | boolean | `true` when more than one distinct right is requested |
| `confidence` | float | 0.0 – 1.0; applies to the primary type |
| `urgency` | string | `"LOW"` \| `"MEDIUM"` \| `"HIGH"` |
| `subject_reference` | string \| `null` | How the data principal referred to themselves (e.g. `"account holder"`) — no raw PII |
| `data_scope_hint` | string \| `null` | What data the request appears to concern, in general terms |
| `suggested_response_outline` | string | Draft outline (not a final response); ≤ 400 chars |
| `ambiguities` | array of string | Questions a human agent should clarify with the requester |

**Permitted `request_types` values**

| Value | Right under DPDP Act |
|---|---|
| `ACCESS` | Right to obtain a summary of personal data held |
| `CORRECTION` | Right to correct inaccurate personal data |
| `ERASURE` | Right to erase personal data |
| `NOMINATION` | Right to nominate a person to exercise rights on death |
| `WITHDRAW_CONSENT` | Right to withdraw previously given consent |
| `GRIEVANCE` | General complaint or grievance |
| `UNKNOWN` | Cannot determine the request type |

### Synthetic example

**Request**
```json
{
  "task": "classify_privacy_request",
  "version": "1",
  "payload": {
    "request_id": "req_20261024_042",
    "raw_text": "Hello, I am a customer and I want to know what personal information you have stored about me. Also, my phone number has changed and I need you to update it in your records. Please confirm once done.",
    "submission_channel": "web_form",
    "language_hint": "en"
  }
}
```

**Response**
```json
{
  "task": "classify_privacy_request",
  "version": "1",
  "status": "ok",
  "needs_human_review": true,
  "result": {
    "request_types": ["ACCESS", "CORRECTION"],
    "is_composite": true,
    "confidence": 0.93,
    "urgency": "LOW",
    "subject_reference": "customer",
    "data_scope_hint": "All stored personal data; specifically the phone number field",
    "suggested_response_outline": "Acknowledge receipt. Send a data summary within the statutory period. Separately process the phone-number correction request after verifying the requester's identity.",
    "ambiguities": [
      "Requester has not provided an account identifier — backend should ask for one to locate the correct record.",
      "New phone number is not included in the text — backend must collect it during identity verification."
    ]
  },
  "warnings": [],
  "error": null
}
```

> `needs_human_review` is `true` because `is_composite` is `true`.

---

## Task 4 — `extract_breach_details`

**Purpose:** Given a free-text incident report written by staff (e.g. an email, a
Slack message pasted into the form, or an internal ticket), the AI module extracts
structured breach metadata to pre-populate the incident record.

> [!IMPORTANT]
> This is an extraction aid only.  All extracted values MUST be reviewed and confirmed
> by a human before the incident record is finalised or any notification is sent.

### `needs_human_review` triggers

`needs_human_review` is **always `true`** for this task — no exceptions.  Breach
response always requires human confirmation.

### Request payload

| Field | Type | Required | Notes |
|---|---|---|---|
| `incident_ref` | string | ✅ | Opaque reference ID from the backend |
| `report_text` | string | ✅ | Raw internal incident report; ≤ 10 000 chars |
| `reporter_role` | string | ❌ | Role of the person filing the report (e.g. `"store_manager"`) — no personal names |
| `report_timestamp` | string | ❌ | ISO 8601 timestamp when the report was filed |

### Response result

| Field | Type | Notes |
|---|---|---|
| `incident_type` | string | See permitted values |
| `discovery_datetime_hint` | string \| `null` | Best-guess ISO 8601 datetime extracted from the text; `null` if not found |
| `affected_data_categories` | array of string | Subset of `classify_columns` category values |
| `estimated_affected_count` | integer \| `null` | Best-guess number of affected data principals; `null` if not stated |
| `count_confidence` | string | `"EXACT"` \| `"ESTIMATE"` \| `"UNKNOWN"` |
| `potential_harm` | array of string | See permitted values |
| `containment_steps_mentioned` | array of string | Steps already taken as described in the text |
| `notification_likely_required` | boolean | Model's assessment of whether regulatory notification may be needed |
| `notification_reasoning` | string | Plain-language explanation, ≤ 300 chars |
| `draft_summary` | string | 3–5 sentence incident summary draft; ≤ 600 chars |
| `open_questions` | array of string | Gaps the human reviewer must fill in |

**Permitted `incident_type` values**

`UNAUTHORISED_ACCESS` · `DATA_LEAK` · `RANSOMWARE` · `INSIDER_THREAT` · `LOST_DEVICE` · `PHISHING` · `ACCIDENTAL_DISCLOSURE` · `SYSTEM_MISCONFIGURATION` · `UNKNOWN`

**Permitted `potential_harm` values**

`IDENTITY_THEFT` · `FINANCIAL_LOSS` · `REPUTATIONAL_DAMAGE` · `DISCRIMINATION` · `PHYSICAL_HARM` · `EMOTIONAL_DISTRESS` · `LOSS_OF_CONFIDENTIALITY` · `UNKNOWN`

### Synthetic example

**Request**
```json
{
  "task": "extract_breach_details",
  "version": "1",
  "payload": {
    "incident_ref": "inc_20261024_003",
    "report_text": "Hi team, just noticed that our customer database backup file was accidentally uploaded to a public S3 bucket this morning around 9 AM. The file contains customer names, email addresses, and phone numbers for roughly 3,000 customers from our Delhi store. I've already made the bucket private again and removed the file. Not sure how long it was public. Please advise on next steps.",
    "reporter_role": "store_manager",
    "report_timestamp": "2026-10-24T09:47:00+05:30"
  }
}
```

**Response**
```json
{
  "task": "extract_breach_details",
  "version": "1",
  "status": "ok",
  "needs_human_review": true,
  "result": {
    "incident_type": "ACCIDENTAL_DISCLOSURE",
    "discovery_datetime_hint": "2026-10-24T09:00:00+05:30",
    "affected_data_categories": ["IDENTITY", "CONTACT"],
    "estimated_affected_count": 3000,
    "count_confidence": "ESTIMATE",
    "potential_harm": [
      "IDENTITY_THEFT",
      "LOSS_OF_CONFIDENTIALITY",
      "REPUTATIONAL_DAMAGE"
    ],
    "containment_steps_mentioned": [
      "S3 bucket access set back to private",
      "Backup file removed from the bucket"
    ],
    "notification_likely_required": true,
    "notification_reasoning": "Approximately 3,000 data principals' contact and identity data was exposed publicly. The DPDP Act and IT Rules require notification to the Data Protection Board and affected individuals when a breach is likely to cause harm.",
    "draft_summary": "On 2026-10-24 at approximately 09:00 IST, a customer database backup containing names, email addresses, and phone numbers of an estimated 3,000 customers from the Delhi store was inadvertently made publicly accessible via a cloud storage bucket. The exposure was discovered and contained by the reporting manager, who restricted access and deleted the file. The duration of public exposure is currently unknown. Regulatory notification obligations are likely to apply.",
    "open_questions": [
      "Exact duration for which the bucket was publicly accessible is unknown — check cloud access logs.",
      "Confirm whether the backup was encrypted at rest.",
      "Determine whether any third party accessed or downloaded the file during the exposure window.",
      "Check if financial or government-ID data was also present in the backup."
    ]
  },
  "warnings": [
    "Duration of exposure could not be determined from the report text. This materially affects notification timelines."
  ],
  "error": null
}
```

> `needs_human_review` is always `true` for `extract_breach_details`.

---

## Changelog

| Version | Date | Author | Summary |
|---|---|---|---|
| 0.1.0 | 2026-10-24 | AI/SLM lead | Initial draft — four tasks, common envelope, hard constraints |

---

## Open questions

- [ ] Should `classify_columns` accept batches larger than 200 columns?  If so, define a chunking protocol.
- [ ] Do we need a `detect_language` pre-flight task so both sides can agree on the language before calling the main tasks?
- [ ] What is the agreed SLA (milliseconds) for each task so the backend can set appropriate timeouts?
- [ ] Confirm which Ollama model tag will be the default; document fallback behaviour if the model is not pulled.
- [ ] Agree on the authentication mechanism between the backend service and the AI module's local HTTP server (e.g. shared secret header, mutual TLS, or no auth since both run on localhost).
