# Authentication and school isolation

Status: approved design (Phase B). Sections are marked **Implemented** or
**Planned** so this document always matches the code.

## Goals

- Only invited people can use the system, and each sees only what their role
  in their school allows.
- A user of School A can never read or change School B's data by changing a
  URL, an identifier, a request body or an API call.
- Access can be revoked immediately.

## Users, schools and memberships

| Table         | Purpose                                                   | Status      |
|---------------|-----------------------------------------------------------|-------------|
| `users`       | One login identity per person                             | Implemented |
| `schools`     | Each school on the platform, with its county (1 to 47, Constitution order) | Implemented |
| `memberships` | Links a user to a school with a role; one person can belong to several schools and hold several roles in one | Implemented |
| `sessions`    | Hashed session tokens, expiry and the active school       | Implemented |
| `login_attempts` | Recent failed logins, keyed by hashed account and IP | Implemented |

`users.is_platform_admin` can only be set by the `flask create-platform-admin`
terminal command. No API endpoint can grant it. Platform administrators
manage schools but have no automatic access to any school's data; that needs
a membership. Schools and memberships are deactivated, never deleted.
**Implemented.**

## Passwords

Argon2id via `argon2-cffi`, with OWASP's 19 MiB / 2 iterations / 1 thread
configuration, chosen to fit a 512 MB server. Passwords are 12 to 128
characters with no composition rules (NIST guidance). Parameters are stored
in each hash; hashes made with older parameters are detected so they can be
upgraded at login. **Implemented.**

## Sessions

**Implemented** (B2):

- On login the server creates a random 256-bit token and stores only its
  SHA-256 hash. Every login issues a new token.
- The browser receives the token in a cookie marked `HttpOnly` and
  `SameSite=Lax`, plus `Secure` with the `__Host-` prefix in production.
  JavaScript cannot read it.
- A session ends after 30 minutes without activity or 8 hours after login.
  Activity is written to the database at most once a minute.
- Logging out deletes the session. A deactivated user's sessions are deleted
  on their next request.
- Endpoints: `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`,
  `GET /api/v1/auth/me`.
- JWTs were rejected: they are hard to revoke before expiry, and tokens kept
  in browser storage can be stolen through cross-site scripting.
- CSRF protection: `SameSite=Lax`, JSON-only bodies, and an `Origin` check
  against `FRONTEND_ORIGIN` on state-changing requests.
- Failed logins are rate-limited (10 per account, 50 per IP, in 15 minutes)
  with counters in PostgreSQL (no Redis on the free tier). Emails and IPs
  are stored only as HMAC hashes; records older than 15 minutes are ignored
  and deleted by `flask prune-sessions`. Every failure returns the same
  message, and unknown emails still run a password check so timing does not
  reveal which accounts exist.

## Same-domain API access (planned, B7)

The browser only talks to the frontend's domain; Next.js forwards `/api/...`
to the Flask API. The session cookie stays first-party, so browsers that
block cross-site cookies do not break login. To be verified on the hosting
platforms before relying on it.

## School isolation

Every school-owned row has a `school_id`. The current school always comes
from the logged-in user's membership, never from the request.

**Implemented** (B3): the session stores an active school, set only by
`POST /api/v1/auth/active-school` after checking for an active membership in
an active school (or automatically at login when the user has exactly one
school). `current_school()` repeats the check on every request and clears the
active school if access has ended. Inaccessible schools all get the same
`403`. Tests cover a School A user trying to switch to School B, to an
unknown ID, to an inactive school and to a school whose membership ended.

1. **Application layer** (implemented): every school-owned query goes
   through `current_school()`, `school_required` or `permission_required`.
   The member endpoints (B4) look up IDs only within the active school.
2. **Database layer** (planned, B5): PostgreSQL Row-Level Security policies
   restrict rows to the current school, set per request. The API connects as
   `sms_app`, which does not own the tables, so the policies cannot be
   bypassed by it.

Every feature that touches school data includes tests in which a School A
user tries to read and change School B data and is refused.

## Roles and permissions

**Implemented** (B4). The school roles (school administrator, principal,
teacher, finance officer, registrar, parent or guardian, student) map to
explicit permissions in `app/auth/permissions.py`, such as `members.read`.
Roles have nothing by default; features add the permissions they need. A
user's permissions are the union of their active roles in the active school.
Each endpoint declares the permission it requires with
`permission_required`, and the server checks it. Platform administrators are
separate: they manage schools but hold no school permissions unless they
are also given a membership.

## Audit trail

**Implemented** (B4). `audit_events` records who did what, in which school,
to what, the outcome (`success` or `denied`) and the request ID, with IDs
only. The API's database user can only add and read events. Successful
changes are recorded in the same transaction as the change; refusals are
recorded separately.

## Sign-up (planned, B6)

There is no public sign-up. A platform administrator creates a school and
invites its first school administrator, who invites staff, parents and
students. Invitations are single-use and expire.

## Password reset (planned, B8)

Self-service reset by email requires an email provider, still to be chosen.
Until then a school administrator can reset a user's password.

## Data protection

Student records include children's personal data. The design aims for data
minimisation and audit trails, with Kenya's Data Protection Act 2019 in mind.
A qualified legal review is required before real schools use the system; this
document does not claim compliance.
