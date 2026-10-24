# AI / SLM Module

This folder owns everything related to on-device AI inference.

## Responsibilities

- **Ollama integration** — client wrapper that talks to the local Ollama server (model selection, prompt construction, response parsing).
- **Data classification** — logic that labels personal data fields according to sensitivity tiers (e.g. sensitive personal data, general personal data, non-personal data) as defined by the DPDP Act.
- **Prompt engineering** — versioned prompt templates for classification, issue detection, breach-notification drafting, and inventory Q&A.
- **Model configuration** — settings for model name, context length, temperature, and other inference parameters.
- **AI utilities** — shared helpers for chunking, token counting, and response validation.

## What does NOT belong here

- HTTP API endpoints → `backend/`
- Database access → `backend/`
- UI components → `frontend/`
- Raw test datasets → `sample_data/`

## Planned structure (subject to change)

```
ai/
├── client.py          # Ollama HTTP client wrapper
├── classifier.py      # Personal-data field classifier
├── prompts/           # Versioned prompt templates (YAML or plain text)
├── models.py          # Pydantic models for AI I/O
└── config.py          # Model name, endpoint, and inference settings
```
