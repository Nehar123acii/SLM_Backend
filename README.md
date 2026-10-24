# Privacy Compliance Assistant

> A **local-first** privacy compliance assistant for small businesses in India.
> All AI inference runs on-device via [Ollama](https://ollama.com/) — no data leaves the premises.

---

## What it does

| Capability | Description |
|---|---|
| **Data Classification** | Classifies personal data fields (e.g. Aadhaar, PAN, contact info) using an on-device SLM |
| **Privacy Issue Detection** | Scans data flows and raises alerts for potential DPDP Act / IT Act violations |
| **Privacy Request Management** | Tracks and helps respond to data principal rights requests (access, correction, erasure) |
| **Breach Response** | Guides teams through an incident workflow and generates breach-notification drafts |
| **Data Inventory Q&A** | Answers natural-language questions about the business's own data inventory |

---

## Project Structure

```
SLM_Backend/
├── ai/            # AI / SLM module (Ollama integration, prompts, classifiers)
├── backend/       # REST APIs, ETL pipelines, database layer
├── contracts/     # Shared API contracts, schemas, and data models
├── frontend/      # User interface
├── sample_data/   # Synthetic / anonymised sample datasets for dev & testing
└── tests/         # Cross-cutting integration and end-to-end tests
```

---

## Team Responsibilities

| Role | Owner | Area |
|---|---|---|
| **AI / SLM Lead** | — | `ai/` — Ollama integration, prompt engineering, classification logic |
| **Backend / Full-Stack Lead** | — | `backend/` — REST APIs, ETL pipelines, database schema & migrations |
| **Frontend Lead** | — | `frontend/` — UI, UX, client-side routing and state management |

> **Shared ownership:** `contracts/`, `sample_data/`, `tests/`, and this root README are maintained collaboratively by all team members.

---

## Regulatory Context

This tool is designed with India's **Digital Personal Data Protection (DPDP) Act, 2023** and the **IT Act, 2000** in mind. It is not a substitute for qualified legal advice.

---

## Getting Started

_Setup instructions will be added once the tech stack is finalised._

---

## Contributing

1. Branch off `main` with a descriptive branch name (e.g. `feat/ai-classifier`, `fix/backend-auth`).
2. Open a pull request and request review from at least one other team member.
3. Keep secrets, model weights, real personal data, and virtual environments out of version control (see `.gitignore`).
