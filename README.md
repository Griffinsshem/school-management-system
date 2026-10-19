# School Management System

A multi-school School Management System for administrators, teachers,
finance staff, parents and students, built with strict school-level data
isolation and security as first priorities.

> **Status:** Project initialization complete. The frontend is the Next.js
> starter page and the backend exposes only a health endpoint. No school
> management features are implemented yet.

## Stack

| Part     | Technology                                                        |
|----------|-------------------------------------------------------------------|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4      |
| Backend  | Python 3.12, Flask 3.1, SQLAlchemy 2.1, Flask-Migrate, Pytest, Ruff |
| Database | PostgreSQL (configured, not yet connected)                        |
| Hosting  | Vercel (frontend), Render (backend), subject to free-tier review  |

## Repository structure

```text
school-management-system/
├── frontend/   Next.js web application (independently deployable)
├── backend/    Flask REST API under /api/v1 (independently deployable)
└── docs/       Architecture and security notes
```

## Prerequisites

- Node.js 20.9 or newer (developed on 22.x) and npm
- Python 3.12 with `venv`
- Git
- PostgreSQL 16 (not required until the database feature is added)

## Getting started

The frontend and backend run independently. Follow each guide:

- [Frontend setup](frontend/README.md)
- [Backend setup](backend/README.md)

Security decisions and known findings are recorded in
[docs/security-notes.md](docs/security-notes.md).

## License

All rights reserved. See [LICENSE](LICENSE).
