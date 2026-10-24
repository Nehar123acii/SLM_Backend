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

## Planned structure (subject to change)

```
sample_data/
├── synthetic_persons.csv      # Fake personal-data records
├── mock_data_inventory.json   # Example data asset catalogue
├── mock_privacy_requests.json # Example rights-request records
├── mock_incidents.json        # Example breach incidents
└── generate.py                # Script to regenerate all files
```
