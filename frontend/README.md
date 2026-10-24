# Frontend

This folder owns the user interface for the privacy compliance assistant.

## Responsibilities

- **UI screens** — all pages and views: data inventory browser, privacy request dashboard, breach incident tracker, classification wizard, and settings.
- **Client-side routing** — navigation between views without full-page reloads.
- **State management** — local application state and API data-fetching / caching.
- **UX / design system** — reusable components, colour tokens, typography, and layout primitives.
- **API client** — typed wrappers around the backend REST endpoints (generated from `contracts/` schemas where possible).

## What does NOT belong here

- Business logic → `backend/`
- AI inference → `ai/`
- Shared data models → `contracts/`

## Planned structure (subject to change)

```
frontend/
├── public/            # Static assets (favicon, fonts, images)
├── src/
│   ├── components/    # Reusable UI components
│   ├── pages/         # Top-level route components / views
│   ├── api/           # Backend API client wrappers
│   ├── store/         # Client-side state management
│   └── styles/        # Global CSS / design tokens
├── index.html
└── package.json
```

> **Framework not yet decided.** See the root README for status.
