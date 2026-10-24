# Tests

This folder owns **cross-cutting integration and end-to-end (E2E) tests** that span more than one module.

## Responsibilities

- **Integration tests** — verify that the AI module, backend API, and database work together correctly (e.g. ingest a file → trigger classification → assert stored results).
- **E2E tests** — simulate real user journeys through the full stack (UI → API → AI → database → UI).
- **Contract tests** — assert that the backend and AI module honour the schemas defined in `contracts/`.
- **Fixtures and factories** — shared test helpers, mock Ollama responses, and database seed utilities used across test files.

## What does NOT belong here

- Unit tests for a single module — keep those co-located inside `ai/`, `backend/`, or `frontend/` alongside the code they test.
- Real personal data — use `sample_data/` synthetic fixtures.

## Planned structure (subject to change)

```
tests/
├── integration/
│   ├── test_classify_flow.py      # Ingest → classify → assert stored label
│   └── test_privacy_request.py    # Submit request → assert workflow
├── e2e/
│   └── test_dashboard_journey.py  # Full UI journey (Playwright / Selenium)
├── contract/
│   └── test_api_contracts.py      # Schema validation against contracts/
└── conftest.py                    # Shared fixtures and test configuration
```

## Running tests

_Commands will be documented here once the test framework is chosen._
