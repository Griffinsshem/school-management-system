# Backend

Flask REST API for the School Management System. All endpoints live under
`/api/v1`.

## Setup

Requires Python 3.12 and a local PostgreSQL 16 server. Run from the
`backend/` folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
chmod 600 .env
```

Generate a secret key directly into `.env` (it is never printed):

```bash
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')|" .env
```

Create the database users and databases, set their passwords and apply
migrations by following [docs/database.md](../docs/database.md).

Activate the virtual environment (`source .venv/bin/activate`) in every new
terminal before working on the backend.

## Run

```bash
flask --app app run
```

The API listens on `http://127.0.0.1:5000`.

```bash
curl http://127.0.0.1:5000/api/v1/health/ready
# {"status":"ok"}
```

`flask run` is for development only. Production uses gunicorn with the
settings in `gunicorn.conf.py` and the entry point `wsgi.py`:

```bash
gunicorn -c gunicorn.conf.py wsgi:app
```

gunicorn's own access log and control socket are switched off: the app
writes one line per request without query strings or IP addresses. Settings
come from environment variables only (gunicorn does not read `.env`), and
`APP_ENV` defaults to `production`. Deployment is described in
`../docs/deployment.md`.

## Test and lint

```bash
pytest
ruff check .
ruff format --check .
```

Tests use the `sms_test` database and migrate it themselves. They read only
`TEST_DATABASE_URL` and `TEST_MIGRATION_DATABASE_URL` (from the environment,
or else from `.env`) and refuse to run against a database whose name does not
end in `_test`. They empty its tables before starting.

The frontend's browser tests start `scripts/e2e_server.py`: an API on
`127.0.0.1:5001` that uses the same `sms_test` database, empties it and adds
clearly fake data. Do not run `pytest` and the browser tests at the same time.

## Configuration

| Variable                      | Purpose                                                         |
|-------------------------------|-----------------------------------------------------------------|
| `APP_ENV`                     | `development` or `production`. If unset, production checks apply. |
| `SECRET_KEY`                  | At least 32 random characters. The app refuses to start otherwise. |
| `LOG_LEVEL`                   | `DEBUG`, `INFO` (default), `WARNING` or `ERROR`. Invalid values stop startup. |
| `DATABASE_URL`                | API connection as `sms_app` (rows only).                        |
| `MIGRATION_DATABASE_URL`      | Migration connection as `sms_migrator` (schema owner).          |
| `TEST_DATABASE_URL`           | Test connection as `sms_app` to `sms_test`.                     |
| `TEST_MIGRATION_DATABASE_URL` | Test migration connection as `sms_migrator` to `sms_test`.      |
| `FRONTEND_ORIGIN`             | The frontend's origin, e.g. `https://app.example.com`. Required in production (https); defaults to `http://127.0.0.1:3000` in development. |
| `TRUSTED_PROXY_COUNT`         | Reverse proxies whose `X-Forwarded-For` is trusted (0 to 5, default 0). |
| `PROXY_SHARED_SECRET`         | Shared with the frontend's host (at least 32 characters). When set, API requests without it are refused with `403` (health checks excepted), and only then is the frontend's `X-SMS-Client-IP` trusted. Required in production. |
| `PORT`, `WEB_CONCURRENCY`     | gunicorn only: the port to listen on (default 10000) and the number of worker processes (default 2). |

The app refuses to start if `SECRET_KEY` or `DATABASE_URL` is missing, so a
misconfigured server fails loudly instead of running with unsafe settings.

## Endpoints

| Method | Path                   | Response                                          |
|--------|------------------------|---------------------------------------------------|
| GET    | `/api/v1/health`       | `200 {"status":"ok"}`                             |
| GET    | `/api/v1/health/ready` | `200 {"status":"ok"}` or `503 {"status":"unavailable"}` |
| POST   | `/api/v1/auth/login`   | `200 {"user": {...}}` and a session cookie; `401`, `422` or `429` |
| POST   | `/api/v1/auth/logout`  | `204`; ends the session and clears the cookie     |
| GET    | `/api/v1/auth/me`      | `200` with the user, their memberships and active school; or `401` |
| POST   | `/api/v1/auth/active-school` | `200` (same body as `/me`), `403`, `401` or `422` |
| POST   | `/api/v1/platform/schools` | Platform admin only: `201 {"school": {...}}`, `409` (code taken), `422`, `401` or `403` |
| GET    | `/api/v1/platform/schools` | Platform admin only: `200 {"schools": [...]}`, `401` or `403` |
| GET    | `/api/v1/school/members` | Needs `members.read`: `200 {"members": [...]}` for the active school; `401` or `403` |
| POST   | `/api/v1/school/members/{id}/deactivate` | Needs `members.manage`: `200 {"member": {...}}`, `404`, `409` (last school admin), `401` or `403` |
| GET    | `/api/v1/school/students` | Needs `students.read`: `200 {"students": [...], "page", "per_page", "total"}`; `422` for bad query parameters |
| POST   | `/api/v1/school/students` | Needs `students.manage`: `201 {"student": {...}}`, `409` (admission number taken), `422` |
| GET    | `/api/v1/school/students/{id}` | Needs `students.read`: `200 {"student": {...}}` or `404` |
| PATCH  | `/api/v1/school/students/{id}` | Needs `students.manage`: `200`, `404`, `409` or `422` |
| POST   | `/api/v1/school/students/{id}/deactivate` | Needs `students.manage`: `200` or `404` |
| GET    | `/api/v1/school/academic-years` | Needs `academics.read`: `200 {"academic_years": [...], "current": {...}}`, newest first |
| POST   | `/api/v1/school/academic-years` | Needs `academics.manage`: `201 {"academic_year": {...}}`, `409` (`year_name_taken` or `overlapping_year`), `422` |
| PATCH  | `/api/v1/school/academic-years/{id}` | Needs `academics.manage`: `200`, `404`, `409` or `422` |
| PUT    | `/api/v1/school/academic-years/{id}/terms/{1-3}` | Needs `academics.manage`: `200` (term created or changed), `404` or `422` |
| GET    | `/api/v1/school/classes?academic_year_id=...` | Needs `classes.read` (every class) or `classes.read_own` (own classes): `200 {"academic_year", "grades", "classes"}`, `404` or `422` |
| POST   | `/api/v1/school/classes` | Needs `classes.manage`: `201 {"class": {...}}`, `409` (`class_exists`) or `422` |
| PATCH  | `/api/v1/school/classes/{id}` | Needs `classes.manage`: `200`, `404`, `409` or `422` |
| POST   | `/api/v1/school/classes/{id}/teachers` | Needs `classes.manage`: `201`, `404`, `409` (`already_assigned`) or `422` |
| DELETE | `/api/v1/school/classes/{id}/teachers/{membership_id}` | Needs `classes.manage`: `200` or `404` |
| GET    | `/api/v1/school/classes/{id}/students` | Needs `classes.read`, or `classes.read_own` for a class the user is a class teacher of or teaches a subject to: `200 {"class", "students"}` or `404` |
| POST   | `/api/v1/school/classes/{id}/students` | Needs `enrolments.manage`: enrol 1 to 100 students (`{"student_ids": [...]}`), all or none: `201`, `404`, `409` (`already_enrolled`) or `422` |
| PATCH  | `/api/v1/school/classes/{id}/students/{student_id}` | Needs `enrolments.manage`: move to another class of the year (`{"class_id"}`): `200`, `404` or `422` |
| DELETE | `/api/v1/school/classes/{id}/students/{student_id}` | Needs `enrolments.manage`: `200` or `404` |
| GET    | `/api/v1/school/classes/{id}/attendance/{YYYY-MM-DD}` | Needs `attendance.read`, or `attendance.record_own` for a class the user teaches: `200` (the register, or a blank one with everyone present), `404` or `422` (not a term day up to today) |
| PUT    | `/api/v1/school/classes/{id}/attendance/{YYYY-MM-DD}` | Needs `attendance.record`, or `attendance.record_own` for a class the user teaches (last 7 days only): save the whole register (`{"marks": [{"student_id", "status", "reason"}]}`), all or none: `201` (taken), `200` (corrected), `403` (`too_late_to_change`), `404`, `409` (`class_list_changed`, `register_students_differ`, `register_already_taken`) or `422` |
| GET    | `/api/v1/school/classes/{id}/attendance?term={1-3}` | Same as reading a register: `200 {"class", "term", "registers", "students"}` with counts per day and per student, `404` or `422` |
| GET    | `/api/v1/school/students/{id}/guardians` | Needs `guardians.read`: `200 {"student", "guardians"}` (primary first) or `404` |
| POST   | `/api/v1/school/students/{id}/guardians` | Needs `guardians.manage`: add a new guardian and link them (`{"full_name", "phone", "email"?, "relationship", "is_primary"?}`): `201`, `404`, `409` (`guardian_exists`, `too_many_guardians`, `phone_taken`) or `422` |
| POST   | `/api/v1/school/students/{id}/guardians/link` | Needs `guardians.manage`: link an existing guardian (`{"guardian_id", "relationship", "is_primary"?}`): `201`, `404`, `409` (`already_linked`, `too_many_guardians`) or `422` |
| PATCH  | `/api/v1/school/students/{id}/guardians/{guardian_id}` | Needs `guardians.manage`: change `relationship`, or set `"is_primary": true`: `200`, `404` or `422` |
| DELETE | `/api/v1/school/students/{id}/guardians/{guardian_id}` | Needs `guardians.manage`: remove the guardian from this student (the record stays): `200` or `404` |
| PATCH  | `/api/v1/school/guardians/{id}` | Needs `guardians.manage`: correct `full_name`, `phone`, `email` (for every linked student): `200`, `404`, `409` (`phone_taken`) or `422` |
| POST   | `/api/v1/school/guardians/lookup` | Needs `guardians.read`: find by phone (`{"phone"}`, in the body, never the URL): `200 {"guardian": {..., "students"}}` or `404` |
| GET    | `/api/v1/school/subjects` | Needs `subjects.read`: `200 {"subjects"}`, every subject by name, inactive ones included |
| POST   | `/api/v1/school/subjects` | Needs `subjects.manage`: `{"name", "code"?}`: `201`, `409` (`subject_exists`, `code_taken`) or `422` |
| PATCH  | `/api/v1/school/subjects/{id}` | Needs `subjects.manage`: change `name`, `code` (`null` removes it), `is_active` or `kcse_category` (`mathematics`, `language` or `other`, since D6): `200`, `404`, `409` or `422` |
| GET    | `/api/v1/school/classes/{id}/subjects` | Needs `subjects.read`: `200 {"class", "subjects"}`, each with its `teachers`, or `404` |
| POST   | `/api/v1/school/classes/{id}/subjects` | Needs `subjects.manage`: `{"subject_id"}` (an active subject): `201`, `404`, `409` (`already_taken`) or `422` |
| DELETE | `/api/v1/school/classes/{id}/subjects/{subject_id}` | Needs `subjects.manage`: the class stops taking it, and its teachers there are removed: `200`, `404` or `409` (`has_assessments`) |
| POST   | `/api/v1/school/classes/{id}/subjects/{subject_id}/teachers` | Needs `subjects.manage`: `{"membership_id"}` (an active teacher): `201`, `404`, `409` (`already_assigned`) or `422` |
| DELETE | `/api/v1/school/classes/{id}/subjects/{subject_id}/teachers/{membership_id}` | Needs `subjects.manage`: `200` or `404` |
| GET    | `/api/v1/school/classes/{id}/subjects/{subject_id}/assessments?term=1` | Needs `marks.read`, `marks.record`, or `marks.record_own` as its subject teacher or the class teacher: `200 {"class", "subject", "terms", "students", "can_record", "assessments"}` (the term is optional), or `404` |
| POST   | `/api/v1/school/classes/{id}/subjects/{subject_id}/assessments` | Needs `marks.record`, or `marks.record_own` as its subject teacher: `{"term", "name", "max_score", "held_on", "weight"?}` (`weight` a whole percentage from 1 to 100, or `null`, since D6): `201`, `404`, `409` (`assessment_exists`) or `422` |
| PATCH  | `/api/v1/school/assessments/{id}` | Same as adding: change `name`, `max_score` (not below a mark already entered), `held_on` or `weight`: `200`, `403` (`assessment_locked`), `404`, `409` or `422` |
| DELETE | `/api/v1/school/assessments/{id}` | Same as adding, only while it has no marks: `200`, `403` (`assessment_locked`), `404` or `409` (`has_marks`) |
| POST   | `/api/v1/school/assessments/{id}/lock` | Needs `marks.record`: only administrators can change it afterwards: `200` (the mark sheet) or `404` |
| POST   | `/api/v1/school/assessments/{id}/unlock` | Needs `marks.record`: `200` (the mark sheet) or `404` |
| GET    | `/api/v1/school/assessments/{id}/marks` | Same readers as the list: `200 {"class", "subject", "assessment", "can_record", "can_lock", "scale", "students"}`, each student with `score`, `did_not_sit`, `in_class` and `result` (`{"percent", "grade", "points"}` or `null`, since D5), or `404` |
| PUT    | `/api/v1/school/assessments/{id}/marks` | Same as adding: `{"marks": [{"student_id", "score"?, "did_not_sit"?}]}`, 1 to 200 students; neither clears that mark; students not sent keep theirs: `200` (the mark sheet), `403` (`assessment_locked`), `404` or `422` |
| GET    | `/api/v1/school/classes/{id}/marks?term=1` | Needs `marks.read`, `marks.record`, or `marks.record_own` as the class teacher: `200 {"class", "term", "students", "scale", "subjects"}`, every assessment of the term with its marks and their `result`, and per subject `term_results` (per student who sat something), `weighted` and `weight_total` (since D6), or `404` |
| GET    | `/api/v1/school/classes/{id}/results?term=1` | Same readers as the overview: `200 {"class", "term", "scale", "show_positions", "subjects", "students"}`, each student with each subject's term result, their `overall` result (`total_points`, `subjects_counted`, `mean_points`, `grade`, `complete`, or `null`) and, when the school shows them, `position`; or `404` (D6) |
| GET    | `/api/v1/school/grading` | Needs `marks.read`, `marks.record` or `marks.record_own`: `200 {"cbc", "kcse", "default_kcse", "show_class_positions"}`, each scale's bands (`grade`, `min_percent`, `points`); `kcse.is_default` |
| PUT    | `/api/v1/school/grading/kcse` | Needs `grading.manage`: `{"boundaries": {"A": 80, ..., "E": 0}}`, all 12 grades, whole numbers going down to `E` at 0: `200` (as GET) or `422` |
| PUT    | `/api/v1/school/grading/positions` | Needs `grading.manage`: `{"show_class_positions": true}` (a real `true` or `false`): `200` (as GET) or `422` (D6) |
| GET    | `/api/v1/school/attendance?date=YYYY-MM-DD` | Needs `attendance.read`: `200 {"date", "academic_year_id", "term_number", "classes"}`, each class taken or not with its counts; the date defaults to today; `422` for a future day |
| POST   | `/api/v1/school/invitations` | Needs `members.manage`: `201 {"invitation": {...}, "accept_url": "..."}`, `409` (already has the role), `422` |
| GET    | `/api/v1/school/invitations` | Needs `members.read`: `200 {"invitations": [...]}` (latest 200, never tokens) |
| POST   | `/api/v1/school/invitations/{id}/revoke` | Needs `members.manage`: `200`, `404` or `409` (already accepted) |
| POST   | `/api/v1/platform/schools/{id}/invitations` | Platform admin only: invite a school admin; `201` or `404` |
| POST   | `/api/v1/invitations/preview` | Anyone with the link: `200 {"invitation": {...}}` or `404` |
| POST   | `/api/v1/invitations/accept` | Anyone with the link: `201` (account created and signed in), `200` (role added), `401`, `403`, `404` or `422` |

Errors are always JSON in the form
`{"error": {"code": "...", "message": "...", "request_id": "..."}}` and never
include stack traces. Validation errors (`422`) add a `details` list naming
each invalid field, without repeating the submitted value.

Request bodies must be JSON (`Content-Type: application/json`); others get
`415`.

## Logging and request IDs

Every response carries an `X-Request-ID` header. A client may send its own
`X-Request-ID` (8 to 64 letters, digits, `-` or `_`); anything else is
replaced with a new random ID. The same ID appears in error bodies and on
every log line for that request, so a reported error can be traced.

Logs go to standard output: readable text in development, one JSON object
per line in production. Each request produces one summary line with the
method, path, status and duration. Query strings, request bodies, headers,
cookies and IP addresses are never logged by the app.

The Flask development server prints its own access lines as well, which do
include the query string and client IP. It is for local use only.

## Users and administrators

There is no public sign-up. The first platform administrator is created from
the terminal (run from `backend/` with the virtual environment active):

    flask --app app create-platform-admin

It asks for an email address, a name and a password (typed twice, hidden).
The password is never accepted as a command-line option, so it cannot end up
in shell history. Passwords must be 12 to 128 characters and are stored only
as Argon2id hashes.

Everyone else joins by invitation (below).

## Schools and memberships

A platform administrator creates schools with `POST /api/v1/platform/schools`
and a body such as
`{"name": "Greenfield Academy", "code": "greenfield-academy", "county_code": 32}`.

- `code` is a short unique identifier: 3 to 50 lowercase letters or digits,
  optionally joined by single hyphens. It is lowercased automatically.
- `county_code` is the county's number in the First Schedule of the
  Constitution, from 1 (Mombasa) to 47 (Nairobi City). Responses include the
  county's name. The full list is in `app/models/school.py`.
- Schools are deactivated, never deleted.

Being a platform administrator does not give access to any school's data.
Access comes only from a membership: a user's role in a school
(`school_admin`, `principal`, `teacher`, `finance_officer`, `registrar`,
`guardian` or `student`). One person can hold several roles in a school.
Until invitations exist, memberships are added from the terminal:

    flask --app app add-membership --email ada@example.com --school-code greenfield-academy --role school_admin

### The active school

Each session works in one school at a time. A user with exactly one school
starts in it at login; otherwise they choose with
`POST /api/v1/auth/active-school` and `{"school_id": "..."}`. The server
checks for an active membership in an active school first, and gives the
same `403` for a school that does not exist, is inactive or is someone
else's. The check is repeated on every request, so deactivating a membership
or a school removes access immediately.

### Roles and permissions

Each role grants an explicit list of permissions, defined in
`app/auth/permissions.py`; nothing is granted by default. A user's
permissions are those of all their active roles in the active school, and
`GET /api/v1/auth/me` lists them as `permissions` (for the interface only:
every endpoint checks on the server).

| Permission       | Roles                       | Allows |
|------------------|-----------------------------|--------|
| `members.read`    | `school_admin`, `principal`              | Listing the school's members |
| `members.manage`  | `school_admin`                           | Deactivating a member |
| `students.read`   | `school_admin`, `principal`, `registrar` | Listing and viewing students |
| `students.manage` | `school_admin`, `registrar`              | Adding, changing and deactivating students |
| `academics.read`  | `school_admin`, `principal`, `registrar`, `teacher`, `finance_officer` | Seeing school years and terms |
| `academics.manage`| `school_admin`                           | Adding and changing school years and terms |
| `classes.read`    | `school_admin`, `principal`, `registrar` | Seeing every class and its class teachers |
| `classes.manage`  | `school_admin`                           | Adding and changing classes, choosing class teachers |
| `classes.read_own`| `teacher`                                | Seeing only the classes they are an active class teacher of or teach a subject to, and their class lists |
| `enrolments.manage`| `school_admin`, `registrar`             | Enrolling students in classes, moving and removing them |
| `attendance.read`  | `school_admin`, `principal`             | Reading every class's registers, term summaries and the school's daily overview |
| `attendance.record`| `school_admin`                          | Taking and correcting any class's register, for any term day up to today |
| `attendance.record_own`| `teacher`                           | Reading, taking and correcting the registers of the classes they teach, for today and the previous 7 days |
| `guardians.read`   | `school_admin`, `principal`, `registrar` | Seeing students' guardians and looking one up by phone |
| `guardians.manage` | `school_admin`, `registrar`             | Adding, linking, correcting and removing students' guardians |
| `subjects.read`    | `school_admin`, `principal`             | Seeing the school's subjects, the subjects each class takes and their teachers |
| `subjects.manage`  | `school_admin`                          | Adding and changing subjects, choosing each class's subjects and subject teachers |
| `marks.read`       | `school_admin`, `principal`             | Reading every class's assessments and marks |
| `marks.record`     | `school_admin`                          | Adding, changing, deleting, locking and unlocking any assessment, and entering any marks, locked or not |
| `marks.record_own` | `teacher`                               | Adding assessments and entering marks for the subjects they teach, until locked, and reading every subject's marks in the classes they are class teacher of |
| `grading.manage`   | `school_admin`                          | Changing the school's KCSE grade boundaries and whether results show class positions (anyone with a marks permission reads both) |

Teachers have no access to student records: they see only the class lists
of their own classes, with each student's name and admission number. They
get no guardian (parent) data at all: contact goes through the office
(decision of 2026-10-28).

A school always keeps at least one active `school_admin`: deactivating the
last one is refused with `409`.

### Audit trail

Security-relevant actions are recorded in the `audit_events` table: who did
what, in which school, to what, whether it succeeded or was refused, and the
request ID. Events hold IDs only. The API's database user can add and read
events but cannot change or delete them. Recorded actions:

| Action                   | When |
|--------------------------|------|
| `school.created`         | A platform admin creates a school |
| `membership.added`       | `flask add-membership` adds or reactivates a role (no actor: terminal) |
| `membership.deactivated` | A member is deactivated, or a deactivation is refused (`404`) |
| `school.selected`        | A user switches school, or is refused (`403`) |
| `platform.access`        | A non-admin is refused a platform endpoint |
| `student.created`        | A student is added |
| `student.updated`        | A student is changed, or a change is refused (`404`) |
| `student.deactivated`    | A student is deactivated, or a deactivation is refused (`404`) |
| `academic_year.created`  | A school year is added |
| `academic_year.updated`  | A school year is changed, or a change is refused (`404`) |
| `term.saved`             | A term is set or changed (one event per term), or a change is refused (`404`) |
| `class.created`          | A class is added |
| `class.updated`          | A class is changed, or a change is refused (`404`) |
| `class_teacher.added`    | A class teacher is assigned, or an assignment is refused (`404`) |
| `class_teacher.removed`  | A class teacher is removed, or a removal is refused (`404`) |
| `enrolment.added`        | A student is enrolled in a class (one event per student), or enrolling into a missing class is refused (`404`) |
| `enrolment.moved`        | A student is moved to another class, or a move is refused (`404`) |
| `enrolment.removed`      | A student is removed from a class, or a removal is refused (`404`) |
| `class.students_read`    | A class list is refused (`404`): another school's class, or a class the teacher does not teach |
| `attendance.taken`       | A register is saved for the first time (target: the register) |
| `attendance.corrected`   | A saved register is changed (target: the register); nothing is recorded if no mark changed |
| `attendance.mark_changed`| One student's mark is changed by a correction (one event per student) |
| `attendance.saved`       | Saving a register is refused: another school's class or a class the teacher does not teach (`404`), or a day more than 7 days ago for a teacher (`403`) |
| `attendance.read`        | Reading a register or summary is refused (`404`) |
| `guardian.created`       | A new guardian is recorded (target: the guardian) |
| `guardian.updated`       | A guardian's name, phone or email is corrected (target: the guardian), or refused (`404`) |
| `guardian.linked`        | A guardian is linked to a student (target: the student), or refused (`404`) |
| `guardian.link_updated`  | A student's link changes relationship or primary (target: the student), or refused (`404`) |
| `guardian.unlinked`      | A guardian is removed from a student (target: the student), or refused (`404`) |
| `guardians.read`         | Reading a student's guardians is refused (`404`) |
| `subject.created`        | A subject is added (target: the subject) |
| `subject.updated`        | A subject is renamed, its code changed or it is made active or inactive (target: the subject), or refused (`404`) |
| `class_subject.added`    | A class starts taking a subject (target: the class), or refused (`404`) |
| `class_subject.removed`  | A class stops taking a subject, with its teachers there (target: the class), or refused (`404`) |
| `class_subjects.read`    | Reading a class's subjects is refused (`404`) |
| `subject_teacher.added`  | A teacher is assigned to a class's subject (target: the class), or refused (`404`) |
| `subject_teacher.removed`| A teacher is removed from a class's subject (target: the class), or refused (`404`) |
| `assessment.created`     | An assessment is added (target: the assessment), or refused (`404`, target: the class) |
| `assessment.updated`     | An assessment's name, maximum or date is changed (target: the assessment), or refused (`403`, `404`) |
| `assessment.deleted`     | An assessment without marks is deleted (target: the assessment), or refused (`403`, `404`) |
| `assessment.locked`      | An assessment is locked (target: the assessment), or refused (`404`) |
| `assessment.unlocked`    | An assessment is unlocked (target: the assessment), or refused (`404`) |
| `marks.saved`            | A save changes at least one mark (target: the assessment), or is refused (`403`, `404`) |
| `mark.changed`           | One student's mark is added, changed or cleared (target: the student; the score is never recorded) |
| `assessments.read`       | Reading a subject's assessments or a mark sheet is refused (`404`) |
| `marks.read`             | Reading a class's marks overview is refused (`404`) |
| `results.read`           | Reading a class's term results is refused (`404`) |
| `grading.updated`        | A save changes the school's KCSE grade boundaries or whether class positions are shown (target: the school) |
| `invitation.created`     | An invitation is created |
| `invitation.revoked`     | An invitation is revoked, or a revocation is refused (`404`) |
| `invitation.accepted`    | An invitation is accepted (the actor is the person joining), or reuse of an expired, revoked or used invitation is refused |
| `invitation.previewed`   | Preview of an expired, revoked or used invitation is refused |
| A permission name        | A user is refused for lacking that permission, for example `members.manage` |

To read the trail during development:

    sudo -u postgres psql -d sms_dev -c "SELECT occurred_at, action, outcome, target_type FROM audit_events ORDER BY occurred_at"

### Invitations

People join a school only by invitation. A school admin invites an email
address to a role with `POST /api/v1/school/invitations`; a platform admin
can invite a school's administrator with
`POST /api/v1/platform/schools/{id}/invitations`. The response contains an
`accept_url`, shown once, for the inviter to share (for example by WhatsApp
or SMS). There is no email delivery yet.

- The link looks like `FRONTEND_ORIGIN/invitations/accept#token=...`. The
  token is after `#`, which browsers never send to servers; the page sends
  it to the API in a JSON body.
- Only a SHA-256 hash of the token is stored. A link works once, expires
  after 7 days (`INVITATION_LIFETIME`) and can be revoked. Inviting the same
  person to the same role again replaces the earlier link.
- `POST /api/v1/invitations/preview` with `{"token": "..."}` shows the
  school, role, email and whether that email already has an account.
- `POST /api/v1/invitations/accept` with `{"token", "full_name", "password"}`
  creates the account (12 to 128 character password) and signs the person in.
  If the email already has an account, the person must be logged in as that
  account and only `{"token"}` is needed; the role is added.
- An unknown, expired, revoked or already used link always gets the same
  `404`.

### Students

A student record holds an admission number (unique within the school, 1 to
30 characters), a full name and an optional date of birth (`YYYY-MM-DD`, not
in the future, at most 30 years ago). Students are deactivated, never
deleted. Only the minimum is stored; further details will arrive with the
features that need them.

- `GET /api/v1/school/students` takes `page` (default 1), `per_page` (1 to
  100, default 50) and `q`, which matches part of the name or admission
  number regardless of letter case. Results are sorted by name.
- `not_enrolled_in=<school year id>` lists only active students with no class
  in that year (for enrolling); `404` for another school's year.
- `PATCH` changes only the fields sent; `"date_of_birth": null` clears it.
- The school is never taken from the request: a body containing `school_id`
  is refused.

### School years and terms

A school records each school year (for example "2027", 1 to 20 characters,
unique within the school) with its first and last day, and up to three
terms, numbered 1 to 3. Dates are `YYYY-MM-DD`, between the years 2000 and
2100. Years and terms are never deleted: mistakes are corrected by editing.

- A year ends after it starts and lasts at most 400 days. Years of one
  school never share a day (`409 overlapping_year`).
- Terms lie inside their year and follow each other in number order; a term
  may start the day after the previous one ends. A year's dates cannot be
  changed so that a term falls outside it.
- `POST` may include `terms` (0 to 3); either everything is saved or nothing
  is. `PATCH` changes only the fields sent (none may be null).
  `PUT .../terms/{number}` with `{"starts_on", "ends_on"}` creates or
  corrects one term.
- `current` in the list says which year and term contain today, and the next
  term when today is in none. "Today" is the date in Kenya
  (`Africa/Nairobi`, from the `tzdata` package), so it does not depend on
  the server's clock zone.
- Checks that compare rows run while the school's row is locked
  (`SELECT ... FOR UPDATE`), so two administrators saving at the same moment
  cannot both pass them.

### Classes and class teachers

A class is a grade, and optionally a stream (1 to 20 characters, such as
"East"), in one school year: "Grade 4 East", or "Grade 4". Grades are the
codes `pp1`, `pp2`, `grade_1` to `grade_12` and `form_1` to `form_4`. A grade
and stream appear once per year (also with no stream). Classes are corrected,
never deleted; the year cannot be changed.

- Which grades exist follows Kenya's move from 8-4-4 to CBC, by the calendar
  year the school year starts in (`app/models/school_class.py`): Grade 7 to 12
  from 2023 to 2028 (Grade n from 2016 + n), Form 1 to 4 until 2024 to 2027
  (Form n until 2023 + n). PP1, PP2 and Grades 1 to 6 always. The list
  response's `grades` gives the grades of that year. Checked 2026-10-27.
- A class teacher must be an active `teacher` of the same school; the
  database enforces school and role with a three-column foreign key. A class
  can have several. Removing one deletes only the assignment.
- A teacher sees only the classes they are an active class teacher of (or,
  since D3, teach a subject to). Once their membership is deactivated their
  assignments stop counting; school admins still see them, with
  `is_active: false`.

### Class lists (enrolments)

An enrolment puts a student in a class for that class's school year.

- A student is in at most one class per school year; enrolling one who
  already has a class that year is refused (`409`) and names the class:
  move them instead. Enrolling several is all or nothing.
- Only active students of the school can be enrolled (checked by the API: a
  database rule would stop enrolled students being deactivated).
- The database checks that the student, the class and the year belong
  together (multi-column foreign keys), so a move stays within the year.
- Removing an enrolment deletes it; the audit trail keeps the history.
  Enrolled students and classes cannot be deleted.
- Teachers get only `id`, `admission_number` and `full_name` for each
  student; staff who may read student records also get `is_active`.

### Attendance

A register is one class's attendance for one day, with one mark per student:
`present`, `absent` or `late`.

- Registers are taken for days inside a term of the class's school year, up
  to today in Kenya (weekends included, for Saturday classes). One register
  per class per day, one mark per student (both enforced by the database).
- Every absence has a reason from a fixed list: `sick`, `permission` or
  `unknown`. There is no free text about children. The database refuses any
  other reason, and a reason on a mark that is not an absence.
- A register is saved whole, all or nothing. A new register must cover
  exactly the class's active students; a correction must cover exactly the
  students it was taken for, so history stays as it was when students move
  or leave (decision of 2026-10-27).
- Teachers take and correct their own classes' registers for today and the
  previous 7 days; after that only a school administrator can change them.
- Nothing is deleted: the API's database user cannot delete or empty either
  table. Corrections change marks and are audited. A student with marks
  cannot be deleted.
- Teachers and readers get only `id`, `admission_number` and `full_name` for
  each student.

### Guardians

A guardian (parent or other contact) is stored once per school and linked to
each student they are responsible for, so siblings share one record
(decisions of 2026-10-28).

- Kept to a minimum: full name, a Kenyan mobile number, an optional email,
  and per student the relationship (`mother`, `father`, `guardian`,
  `grandparent`, `sibling`, `other_relative`) and whether this is the
  primary contact. No ID numbers, addresses or free-text notes.
- Phone numbers are accepted as people write them (`0712 345 678`,
  `+254 712 345678`, `254712345678`) and stored as `+254712345678`; the
  database refuses any other form, and a number appears once per school.
  Adding a guardian whose number is already recorded is refused
  (`guardian_exists`) so the existing record is linked instead.
- At most 4 guardians per student. A student with guardians always has
  exactly one primary: the first becomes primary, choosing another moves it,
  and removing the primary passes it to the guardian linked longest ago.
- Guardians are corrected, never deleted; removing one from a student
  deletes only the link. Linked students and guardians cannot be deleted.
- Phone numbers and emails never go into URLs, logs or the audit trail
  (lookups send the number in the request body; error messages never repeat
  it).

### Subjects and subject teachers

Each school keeps its own subject list, a class takes some of those
subjects, and each subject a class takes can have teachers (decisions of
2026-10-28).

- A subject has a name (up to 60 characters) and an optional short code (up
  to 10), both trimmed with spaces inside collapsed. Each is used once per
  school, whatever the letter case (the database enforces it).
- Subjects are renamed or made inactive, never deleted. An inactive subject
  cannot be added to a class, but stays on the classes that already take it.
- A class takes a subject once; a subject teacher must be an active
  `teacher` of the same school (a three-column foreign key, as for class
  teachers), and a class's subject can have several. Removing a subject from
  a class also removes its teachers there.
- A subject teacher sees the class in their class list (`is_class_teacher`
  false, the subject names in `my_subjects`) and its students' names and
  admission numbers. They do not take its attendance: registers stay with
  class teachers.
- A subject that has assessments in a class cannot be removed from it
  (`409`, since D4), so marks are never lost that way.

### Assessments and marks

A subject's marks in a class are kept per assessment (decisions of
2026-10-29). Grades are not stored: grading scales come in D5 and will be
worked out from the raw marks.

- An assessment belongs to one subject a class takes and one term of the
  class's school year. It has a name (up to 60 characters, used once per
  subject and term, whatever the letter case), a maximum score (a whole
  number from 1 to 1000), the date it was done (inside the term, not in
  the future) and, optionally, a weight (D6, below). The database checks that the class, subject and term all
  belong to the same school and year.
- A mark is a score from 0 to the maximum with at most one decimal place,
  or "did not sit"; never both and never neither (the database enforces
  it). A student has at most one mark per assessment. Sending neither for a
  student clears their mark; students not sent keep theirs.
- The maximum cannot be lowered below a mark already entered, and an
  assessment with marks cannot be deleted.
- A mark sheet lists the class's active students and anyone who already
  has a mark there (`in_class` false once they have left the class), so
  marks are never hidden.
- Subject teachers add assessments and enter marks for their subjects; the
  class teacher reads every subject's marks in their class; school
  administrators do everything; principals read. Registrars and others see
  no marks. Anyone else gets `404`, as if the class did not exist.
- An administrator can lock an assessment; teachers then read it but cannot
  change it (`403 assessment_locked`) until it is unlocked. Administrators
  can still correct it.
- Every changed mark is audited, student by student, with who changed it;
  scores themselves are never written to logs or the audit trail.

### Grading scales and grades

Grades are worked out from raw marks each time they are shown and never
stored, so changing a scale regrades every mark at once (decisions of
2026-10-29; rules in `app/grading.py`).

- A mark's percentage is score / maximum x 100 rounded to a whole number,
  halves up (89.5% shows as 90%). The grade comes from that rounded number,
  so it always matches the percentage on screen.
- Form classes (`form_1` to `form_4`) use KCSE grades A to E (12 to 1
  points); every other class uses the KJSEA scale: EE1 from 90 (8 points),
  EE2 75, ME1 58, ME2 41, AE1 31, AE2 21, BE1 11, BE2 0 (1 point). BE2
  starts at 0 so that a score of zero still gets a grade. Senior school
  (Grades 10 to 12) uses KJSEA until KNEC publishes its own scale.
- KNEC publishes no fixed KCSE cut-offs, so each school sets its own
  (`grade_boundaries`, one row per grade). Until it does, the default is
  A 80, A- 75, B+ 70, B 65, B- 60, C+ 55, C 50, C- 45, D+ 40, D 35, D- 30,
  E 0. Boundaries are whole numbers, strictly going down, and E starts at 0
  (the database checks the range and E; the API checks the order). All 12
  are saved together, one save per school at a time.
- A subject's term result adds up the scores of the term's assessments a
  student sat, against those assessments' maximums. "Did not sit" and
  marks not entered are left out of both, and a student who sat nothing
  has no term result.
- Grades go to exactly the people who can see the marks.

### Weights and term results

D6 (decisions of 2026-10-30; rules in `app/grading.py`):

- An assessment may have a weight, a whole percentage from 1 to 100. A
  subject's term result is weighted only when every one of the term's
  assessments has a weight and they add up to exactly 100; otherwise it
  adds up the raw marks as before, and the pages say why. Weighted, each
  assessment's percentage counts by its weight; an assessment a student
  did not sit is left out and the others are scaled up to 100. The raw
  totals are still sent but are not the weighted percentage.
- A class's term results show each student's subject results and an
  overall result. Form classes get a KCSE-style mean grade: Mathematics,
  the best language and the best five other subjects (seven in all), the
  points added up and their mean rounded half up to whole points, then
  graded (a mean of 9.5 becomes 10 points, B+). This follows common school
  practice and is still to be confirmed with a real school. Each subject is
  marked as Mathematics, a language or other (`subjects.kcse_category`,
  default other); a student without Mathematics, without a language or
  with fewer than seven results gets the mean of what they have, marked
  incomplete. Other classes get the average of their subjects' KJSEA
  points as a band, complete when they have a result in every subject
  assessed that term.
- Class positions are off unless a school administrator switches them on
  (`schools.show_class_positions`). They rank students still in the class
  with a complete result by total points; equal totals share a place (1, 2,
  2, 4), and everyone else has no position.
- Results go to the readers of the marks overview: school administrators,
  principals and the class teacher. Subject teachers who are not the class
  teacher get `404`.

### Database-level isolation (Row-Level Security)

The `students`, `invitations`, `academic_years`, `terms`, `classes`,
`class_teachers`, `enrolments`, `attendance_registers`, `attendance_marks`,
`guardians`, `student_guardians`, `subjects`, `class_subjects`,
`subject_teachers`, `assessments`, `marks` and `grade_boundaries` tables are protected by a PostgreSQL Row-Level Security policy:
the API's database user (`sms_app`) can only see or write rows of the school
set for the current transaction. The app sets it from the session's active
school (`app/school_context.py`); with no active school, the database
returns no rows. The setting ends with each transaction, so a reused
connection never carries another school's context. The schema owner
(`sms_migrator`) is not limited, so tests and migrations use it for set-up
and clean-up.

## Login sessions

`POST /api/v1/auth/login` takes `{"email": "...", "password": "..."}`. On
success the server creates a session and sends its random token in an
`HttpOnly`, `SameSite=Lax` cookie (`sms_session` in development,
`__Host-sms_session` with `Secure` in production). The database stores only a
SHA-256 hash of the token.

- A session ends after 30 minutes without activity, or 8 hours after login,
  whichever comes first. Logging out ends it immediately.
- Every failed login gets the same `401` "Invalid email or password.", so the
  response does not reveal which emails have accounts.
- After 10 failed logins for one account, or 50 from one IP address, within
  15 minutes, further attempts get `429` with a `Retry-After` header until
  the old failures leave the window. Accounts are never locked permanently.
- Requests that change data (`POST`, `PUT`, `PATCH`, `DELETE`) are refused
  with `403` if the browser says they come from any site other than
  `FRONTEND_ORIGIN`.

An expired session is deleted when its cookie is next used. To delete all
expired sessions and failed-login records older than 15 minutes (to be
scheduled with deployment):

    flask --app app prune-sessions

## Dependencies

- `requirements.txt`: runtime packages, pinned to exact versions. Production
  installs only this file.
- `requirements-dev.txt`: runtime packages plus test and lint tools.
