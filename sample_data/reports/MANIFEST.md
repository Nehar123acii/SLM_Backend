# Data Manifest

**Generated:** 2026-10-25T00:00:00  
**Seed:** 42  
**Regeneration:** `python sample_data/generate_datasets.py`

## Original file checksums (MD5)

| File | MD5 | Purpose |
|---|---|---|
| patients.xlsx | 23f0f79e0b5da069ceaeed1eaf8c9f2c | Clinic patient records; highly sensitive |
| staff.csv | 35c25f591269fdf17e346e1ba143fd73 | Payroll with PAN and bank accounts |
| billing.csv | cf7f91c111f4fe87be570cb868230302 | Clinical invoices |
| appointments_form.csv | 70e7b26fc7bbabd7400d35864f314938 | Appointment form submissions |
| whatsapp_chat.txt | 765cddf000bfc9be5b751b50122ee7b1 | WhatsApp chat log (highly sensitive) |
| synthetic_customers.csv | 9cae1b81b9ee79542fe898560a97dd2c | Retail ETL test v1 |
| synthetic_customers_v2.csv | 81ed2068977ba034d1c637dc519f6619 | Retail ETL test v2 |

## Generated messy variants

| File | Source | Rows | Columns | Key issues |
|---|---|---|---|---|
| patients_messy.xlsx | patients.xlsx | 44 | 7 | exact_duplicates, plausible_duplicates, missing_values |
| staff_messy.csv | staff.csv | 33 | 6 | exact_duplicates, plausible_duplicates, messy_phones |
| billing_messy.csv | billing.csv | 44 | 5 | exact_duplicates, messy_phones, messy_amounts |
| appointments_messy.csv | appointments_form.csv | 64 | 5 | exact_duplicates, plausible_duplicates, messy_phones |
| customers_messy_v1.csv | synthetic_customers.csv | 38 | 8 | see v1 issues |
| customers_messy_v2.csv | synthetic_customers_v2.csv | 15 | 8 | version diff fixture |

## Expected-clean reference fixtures

| File | Purpose |
|---|---|
| patients_fixture_input.csv | 10-row patients input with injected issues |
| patients_fixture_expected.json | Expected transforms + remaining issues per row |
| staff_fixture_input.csv | 5-row staff input with PAN/account edge cases |
| staff_fixture_expected.json | Expected transforms + remaining issues per row |
| version_diff_v1_fixture.csv | 5-row customer dataset v1 |
| version_diff_v2_fixture.csv | 5-row customer dataset v2 |
| version_diff_expected.json | Expected diff: 2 unchanged, 1 changed, 2 added, 2 removed |

## Folder structure

```
sample_data/
├── (originals — never modified)
├── raw_messy/           ← expanded messy variants for upload/ETL testing
├── expected_clean/      ← small input+expected fixtures for unit testing
├── reports/             ← manifest, data dictionary, EDA summary
└── generate_datasets.py ← this script (reproducible, seed=42)
```