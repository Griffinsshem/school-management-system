# School Management System

[![CI](https://github.com/Griffinsshem/school-management-system/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Griffinsshem/school-management-system/actions/workflows/ci.yml)

A multi-school School Management System for administrators, teachers,
finance staff, parents and students, built with strict school-level data
isolation and security as first priorities.

> **Status:** In active development. The academic and fees workflows below
> work end to end, and a staging copy with fictional data runs on free hosting
> ([docs/deployment.md](docs/deployment.md)). Not yet ready for real schools.

## Features

| Area | What works |
|------|------------|
| **Schools and people** | Multiple schools with strict data isolation; roles for school admins, principals, teachers, finance officers, registrars, guardians and students; invitation links to join a school |
| **School year** | Academic years and terms; classes by grade and stream; subjects per class; class and subject teachers |
| **Students** | Student records, class enrolment and guardians |
| **Attendance** | Daily class registers (present, absent with a reason, late), editable for a week, with term summaries per class |
| **Marks and results** | Assessments per subject and term, mark sheets, weighted term results, and CBC and KCSE grading with configurable boundaries and optional class positions |
| **Report cards** | Per-student report cards with grades, points, attendance and class teachers' comments; print one or all, one per page |
| **Fees** | Fee structures per grade and term, student bills and corrections, payments, receipts, student statements and arrears lists, all print-ready |

## Engineering highlights

- **School isolation:** the active school comes only from the server-side session and is re-checked on every request; every inaccessible school returns the same `403`, so IDs cannot be probed.
- **Security:** revocable server-side sessions (the database stores only SHA-256 token hashes), Argon2id, three-layer CSRF protection and rate-limited logins. Details are in [docs/security-notes.md](docs/security-notes.md).
- **Least-privilege database:** the API connects as a user that can only read and write rows; only the migration user can change the schema, and a test proves the API user is refused.
- **Tests:** 770+ backend tests with Pytest, and Playwright browser tests covering each workflow, accessibility checks and phone layouts.

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
