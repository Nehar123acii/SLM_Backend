# EDA Findings Summary

Statistical findings only — no raw personal data values recorded.

## patients_messy.xlsx

- **Source:** patients.xlsx
- **Rows:** 44
- **Columns:** 7
- **Issues injected:**
  - exact_duplicates: 5
  - plausible_duplicates: 4
  - missing_values: {'Notes': 29, 'Email': 1}
  - messy_phones: 5
  - messy_emails: 4
  - messy_aadhaar: 3
  - ambiguous_dates: 4
  - category_inconsistencies: 6
  - sensitive_notes: 5
- **Personal data columns:** Name, Phone, Email, Aadhaar, DOB, Notes
- **Sensitive columns:** Aadhaar, Notes (health), Test Name (health)
- **Edge cases for SLM review:**
  - Notes column contains health condition mentions requiring DPDP sensitive-data classification
  - Aadhaar column contains synthetic invalid tokens and missing values
  - Test Name includes HIV, pregnancy — sensitive health context

## staff_messy.csv

- **Source:** staff.csv
- **Rows:** 33
- **Columns:** 6
- **Issues injected:**
  - exact_duplicates: 5
  - plausible_duplicates: 3
  - messy_phones: 4
  - synthetic_pan_tokens: 3
  - messy_salary: 3
  - missing_values: {'pan': 2, 'phone': 2}
  - leading_zero_accounts: 18
  - extra_whitespace_name: 3
- **Personal data columns:** name, pan, phone, bank_account
- **Sensitive columns:** pan (GOVERNMENT_ID), bank_account (FINANCIAL), salary (FINANCIAL), ifsc (FINANCIAL)
- **Edge cases for SLM review:**
  - PAN column contains clearly synthetic tokens mixed with pattern-valid values
  - Bank account numbers have leading zeros — must be preserved as TEXT
  - Salary field has non-numeric entries requiring validation

## billing_messy.csv

- **Source:** billing.csv
- **Rows:** 44
- **Columns:** 5
- **Issues injected:**
  - exact_duplicates: 4
  - messy_phones: 5
  - messy_amounts: 4
  - invalid_invoice_refs: 3
  - missing_gstin: 5
  - extra_whitespace_name: 3
- **Personal data columns:** patient_name, phone
- **Sensitive columns:** phone (CONTACT)
- **Edge cases for SLM review:**
  - Some rows reference patients not present in patients.xlsx (deliberate invalid FK)
  - GSTIN field: empty cells vs. a shared GSTIN — business-purpose ambiguity for review

## appointments_messy.csv

- **Source:** appointments_form.csv
- **Rows:** 64
- **Columns:** 5
- **Issues injected:**
  - exact_duplicates: 6
  - plausible_duplicates: 3
  - messy_phones: 7
  - messy_emails: 5
  - ambiguous_timestamps: 5
  - missing_emails: 4
  - reason_category_inconsistencies: 8
  - unknown_reason_needs_review: 3
  - extra_whitespace_name: 4
- **Personal data columns:** Name, Phone, Email
- **Sensitive columns:** Reason (health condition), Email (CONTACT), Phone (CONTACT)
- **Edge cases for SLM review:**
  - Reason field contains HIV screening, pregnancy — sensitive health context
  - 3 rows have 'Other / Not specified' reason — unknown business purpose requiring owner review
  - Ambiguous timestamps like '01/02/26' cannot be safely parsed without locale context

## customers_messy_v1.csv

- **Source:** synthetic_customers.csv
- **Rows:** 38
- **Columns:** 8
- **Personal data columns:** customer_name, email, phone, pan_number
- **Sensitive columns:** pan_number (GOVERNMENT_ID), phone (CONTACT), email (CONTACT)
- **Edge cases for SLM review:**
  - PAN column contains clearly synthetic tokens for identifier detector edge-case testing
  - City column has regional spelling variants (Mumbai/Bombay, Bengaluru/Bangalore)
  - V2 excludes 2 customers from V1 — tests REMOVED detection in version reconciler
- **Version diff (v1→v2):** unchanged=5, changed=3, added=7, removed=2

## whatsapp_chat.txt

- **file:** whatsapp_chat.txt
- **note:** Statistical analysis only — no raw message content recorded in this report.
- **total_lines:** 300
- **message_lines:** 300
- **unique_participants:** 16
- **aadhaar_pattern_matches:** 3
- **phone_pattern_matches:** 7
- **email_pattern_matches:** 2
- **health_keyword_mentions:** 32
- **erasure_request_signals:** 3

**Privacy risk summary:** Chat log contains Aadhaar-format numbers, phone numbers, and email addresses shared in plaintext messages. Health conditions and test results mentioned. Multiple messages appear to signal erasure or opt-out intent. This file requires SLM contextual review and likely constitutes a data source requiring breach-response assessment.

**SLM review triggers:**
  - Aadhaar numbers shared in plaintext — SENSITIVE_PERSONAL_DATA
  - Health condition disclosures — SENSITIVE_PERSONAL_DATA / HEALTH category
  - Erasure-intent signals — potential DPDP Act rights requests to be actioned
  - Phone numbers and emails shared across participants — CONTACT category

**Recommended action:** DO NOT include raw chat content in any ETL pipeline without explicit owner consent and legal basis review. Treat as a privacy-incident evidence source.