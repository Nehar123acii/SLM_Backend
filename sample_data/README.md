# Sample Data

This folder contains **synthetic and anonymised** datasets used for development, manual testing, and demonstrations.

## Rules — please read before adding files

> **NEVER commit real personal data.**
> All files here must be artificially generated or fully anonymised.
> If in doubt, leave the file out and generate it locally with a script.

## Responsibilities

- **Synthetic personal-data records** — fake names, emails, phone numbers, and Indian identifier-like strings (not real Aadhaar/PAN) for testing the classifier.
- **Mock data inventories** — representative data-asset catalogues for a hypothetical small Indian business (e.g. a retail shop, a clinic).
- **Scenario fixtures** — pre-built privacy requests and breach incident records for UI and API testing.
- **Generation scripts** — scripts that produce the above files so team members can regenerate them locally.

## What does NOT belong here

- Real customer records or any actual personal data.
- Model weights or large binary files.
- Database dumps from production or staging.

## Folder Structure

```
sample_data/
├── (Original files — preserved intact and verified via MD5 checksums)
│   ├── patients.xlsx             # Clinical patient records with health and Aadhaar contexts
│   ├── staff.csv                 # Payroll records with PAN and bank accounts
│   ├── billing.csv               # Invoice billing data
│   ├── appointments_form.csv     # Webform appointment requests
│   ├── whatsapp_chat.txt         # Unstructured communication log (incident evidence source)
│   ├── synthetic_customers.csv   # Retail dataset (v1 baseline)
│   └── synthetic_customers_v2.csv# Retail dataset (v2 revision)
│
├── raw_messy/                    # Expanded datasets with controlled quality issues for EDA/ETL
│   ├── patients_messy.xlsx       # Inconsistent headers, ambiguous dates, formatting, PII
│   ├── staff_messy.csv           # Leading-zero accounts, invalid/synthetic PANs, whitespace
│   ├── billing_messy.csv         # Duplicate invoices, unverified GSTINs, malformed numbers
│   ├── appointments_messy.csv    # Ambiguous timestamps, categorical variations, health text
│   ├── customers_messy_v1.csv    # 38 rows with missing values, format defects, typos
│   └── customers_messy_v2.csv    # 15 rows with removals, modifications, additions for version diff
│
├── expected_clean/               # Reference fixtures with machine-checkable transformations
│   ├── patients_fixture_input.csv & patients_fixture_expected.json
│   ├── staff_fixture_input.csv & staff_fixture_expected.json
│   └── version_diff_v1_fixture.csv, version_diff_v2_fixture.csv & version_diff_expected.json
│
├── reports/                      # Dataset documentation and measurable findings
│   ├── MANIFEST.md               # Summary manifest with row counts and file hashes
│   ├── DATA_DICTIONARY.md        # Column semantics, types, and DPDP sensitivity tiers
│   ├── EDA_FINDINGS.md           # Dataset-level quality and privacy detection findings
│   └── manifest.json             # Machine-readable manifest with original file checksums
│
├── generate_datasets.py          # Deterministic generation script (fixed random seed = 42)
└── validate_datasets.py          # Automated verification suite checking integrity and reproduction
```

## Reproduction & Verification

To regenerate the datasets deterministically:
```bash
python sample_data/generate_datasets.py
```

To run the validation suite:
```bash
python sample_data/validate_datasets.py
```
