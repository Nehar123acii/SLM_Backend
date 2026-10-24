# Contracts

This folder defines the **shared interface layer** between the backend, AI module, and frontend.  
It is the single source of truth for data shapes that cross module boundaries.

## Responsibilities

- **API schemas** — request/response schemas for every backend endpoint (OpenAPI / JSON Schema or Pydantic models).
- **Shared data models** — canonical representations of domain objects (e.g. `DataAsset`, `PrivacyRequest`, `BreachIncident`) that all three modules import from, avoiding duplication.
- **Enumerations and constants** — standardised code values (data categories, sensitivity tiers, request statuses, incident severities) kept in one place so all modules stay in sync.
- **Changelog** — breaking contract changes must be documented here before implementation begins.

## What does NOT belong here

- Implementation code → `ai/`, `backend/`, or `frontend/`
- Raw datasets → `sample_data/`

## Planned structure (subject to change)

```
contracts/
├── schemas/           # JSON Schema or OpenAPI component schemas
│   ├── data_asset.json
│   ├── privacy_request.json
│   └── breach_incident.json
├── enums.py           # Shared enumerations (DataCategory, RequestStatus, …)
├── models.py          # Shared Pydantic base models
└── CHANGELOG.md       # Record of contract-breaking changes
```

## Workflow

1. Discuss and agree on a contract change with all three leads.
2. Update the relevant schema / model in this folder.
3. Implement the change in the consuming modules.
4. Document the change in `CHANGELOG.md`.
