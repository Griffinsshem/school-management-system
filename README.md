# School Management System

[![CI](https://github.com/Griffinsshem/school-management-system/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Griffinsshem/school-management-system/actions/workflows/ci.yml)

A multi-school School Management System for administrators, teachers,
finance staff, parents and students, built with strict school-level data
isolation and security as first priorities.

> **Status:** In development. Login, schools, roles, invitations, people and
> students work, and a staging copy with fake data runs on free hosting
> ([docs/deployment.md](docs/deployment.md)). Not yet ready for real schools.

## Stack

| Part     | Technology                                                        |
|----------|-------------------------------------------------------------------|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4      |
| Backend  | Python 3.12, Flask 3.1, SQLAlchemy 2.1, Flask-Migrate, Pytest, Ruff |
| Database | PostgreSQL 16, least-privilege users, Alembic migrations         |
| Hosting  | Staging: Vercel (frontend), Render (API), Neon (database)         |

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
- PostgreSQL 16

## Getting started

The frontend and backend run independently. Follow each guide:

- [Frontend setup](frontend/README.md)
- [Backend setup](backend/README.md)

Database setup and migrations are described in
[docs/database.md](docs/database.md). Security decisions and known findings
are recorded in [docs/security-notes.md](docs/security-notes.md). The staging
deployment is described in [docs/deployment.md](docs/deployment.md).

## Continuous integration

Every push and pull request runs [GitHub Actions](.github/workflows/ci.yml):
backend lint and tests against a throwaway PostgreSQL 16 database, and
frontend lint, production build, type check and production dependency audit.

## License

All rights reserved. See [LICENSE](LICENSE).
