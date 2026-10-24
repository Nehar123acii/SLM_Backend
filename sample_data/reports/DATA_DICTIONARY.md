# Data Dictionary

All datasets below are **synthetic** — no real personal data.
Identifier-shaped fields (PAN, Aadhaar, phone) use clearly synthetic or deliberately
invalid tokens for detector testing. Do not treat any value here as a real identity.

---

## patients.xlsx / patients_messy.xlsx

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| Name | TEXT | Yes | PERSONAL_DATA | Full name — IDENTITY category |
| Phone | PHONE | Yes | PERSONAL_DATA | Indian mobile/landline format |
| Email | EMAIL | Yes | PERSONAL_DATA | CONTACT category |
| Aadhaar | TEXT | Yes | SENSITIVE_PERSONAL_DATA | 12-digit format; some rows have synthetic invalid tokens |
| DOB | DATE | Yes | PERSONAL_DATA | Date of birth; some rows have ambiguous formats |
| Test Name | TEXT | Indirect | PERSONAL_DATA | Health test — implies health category when combined with Name |
| Notes | TEXT | Yes | SENSITIVE_PERSONAL_DATA | Free text; may contain health diagnoses |

---

## staff.csv / staff_messy.csv

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| name | TEXT | Yes | PERSONAL_DATA | Employee name |
| pan | TEXT | Yes | SENSITIVE_PERSONAL_DATA | PAN number — GOVERNMENT_ID; some rows have synthetic tokens |
| phone | PHONE | Yes | PERSONAL_DATA | CONTACT |
| salary | FLOAT | Yes | PERSONAL_DATA | FINANCIAL — personal financial data |
| bank_account | TEXT | Yes | SENSITIVE_PERSONAL_DATA | FINANCIAL; must be stored as TEXT to preserve leading zeros |
| ifsc | TEXT | No | NON_PERSONAL_DATA | Bank branch code — not directly identifying |

---

## billing.csv / billing_messy.csv

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| invoice_no | TEXT | No | NON_PERSONAL_DATA | Invoice reference ID |
| patient_name | TEXT | Yes | PERSONAL_DATA | IDENTITY — linked to patient record |
| phone | PHONE | Yes | PERSONAL_DATA | CONTACT |
| amount | FLOAT | Indirect | PERSONAL_DATA | FINANCIAL when linked to named patient |
| gstin | TEXT | No | NON_PERSONAL_DATA | Business GSTIN — not an individual identifier |

**Cross-file relationship:** `patient_name` should match `patients.xlsx.Name`.
Invalid references are labelled edge cases.

---

## appointments_form.csv / appointments_messy.csv

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| Timestamp | DATETIME | Indirect | PERSONAL_DATA | When combined with Name, reveals attendance |
| Name | TEXT | Yes | PERSONAL_DATA | IDENTITY |
| Phone | PHONE | Yes | PERSONAL_DATA | CONTACT |
| Email | EMAIL | Yes | PERSONAL_DATA | CONTACT |
| Reason | TEXT | Yes | SENSITIVE_PERSONAL_DATA | Appointment reason reveals health context (HIV, pregnancy) |

---

## synthetic_customers.csv / v2 / customers_messy_v1 / v2

| Column | Inferred type | Personal data | Sensitivity | Notes |
|---|---|---|---|---|
| customer_id | TEXT | No | NON_PERSONAL_DATA | Synthetic key |
| customer_name | TEXT | Yes | PERSONAL_DATA | IDENTITY |
| email | EMAIL | Yes | PERSONAL_DATA | CONTACT |
| phone | PHONE | Yes | PERSONAL_DATA | CONTACT |
| pan_number | TEXT | Yes | SENSITIVE_PERSONAL_DATA | GOVERNMENT_ID; some rows have synthetic tokens |
| city | TEXT | Indirect | PERSONAL_DATA | LOCATION when combined with other fields |
| pincode | TEXT | Indirect | PERSONAL_DATA | LOCATION; preserve as TEXT (leading zeros) |
| purchase_amount_inr | FLOAT | Indirect | PERSONAL_DATA | FINANCIAL when linked to named customer |

---

## whatsapp_chat.txt

Unstructured chat log. Contains:
- Aadhaar numbers in plaintext messages (SENSITIVE_PERSONAL_DATA)
- Phone numbers and email addresses (PERSONAL_DATA)
- Health condition disclosures (SENSITIVE_PERSONAL_DATA)
- Apparent erasure/opt-out requests (DPDP Act rights signals)

**Processing rule:** This file must NOT be ingested via the standard ETL pipeline
without explicit owner consent and legal basis review. Treat as a privacy-incident
evidence source requiring SLM contextual review.
