# Backend

This folder owns the server-side application: REST APIs, data pipelines, and the database layer.

## Responsibilities

- **REST API** — HTTP endpoints consumed by the frontend and exposed to third-party integrations (data inventory CRUD, privacy request tracking, breach incidents, audit log).
- **ETL pipelines** — ingestion scripts that load and normalise data from CSV uploads, spreadsheets, or connected data sources into the internal data store.
- **Database layer** — schema definitions, migrations, and repository/query abstractions.
- **Business logic** — orchestration between the AI module and the data layer (e.g. trigger a classification job when new data is ingested, persist results).
- **Authentication & authorisation** — session management and role-based access control for business staff.

## What does NOT belong here

- AI/SLM inference logic → `ai/`
- UI components → `frontend/`
- Raw test datasets → `sample_data/`
- Cross-service data models → `contracts/`

## Planned structure (subject to change)

```
backend/
├── main.py            # Application entry point (FastAPI / Flask app factory)
├── api/               # Route handlers grouped by domain
│   ├── inventory.py
│   ├── requests.py
│   └── incidents.py
├── db/                # Database models and migrations
├── etl/               # Ingestion and transformation scripts
├── services/          # Business logic / use-case layer
└── config.py          # Environment-specific settings
```
