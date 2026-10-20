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
| `schools`     | Each school on the platform                               | Planned (B3) |
| `memberships` | Links a user to a school with a role; one person can belong to several schools | Planned (B3) |
| `sessions`    | Hashed session tokens, expiry and the active school       | Planned (B2) |

`users.is_platform_admin` can only be set by the `flask create-platform-admin`
terminal command. No API endpoint can grant it. **Implemented.**

## Passwords

Argon2id via `argon2-cffi`, with OWASP's 19 MiB / 2 iterations / 1 thread
configuration, chosen to fit a 512 MB server. Passwords are 12 to 128
characters with no composition rules (NIST guidance). Parameters are stored
in each hash; hashes made with older parameters are detected so they can be
upgraded at login. **Implemented.**

## Sessions (planned, B2)

- On login the server creates a random token and stores only its hash.
- The browser receives the token in a cookie marked `HttpOnly`, `Secure`
  and `SameSite=Lax`. JavaScript cannot read it.
- Logging out, or deactivating a user, deletes their sessions immediately.
- JWTs were rejected: they are hard to revoke before expiry, and tokens kept
  in browser storage can be stolen through cross-site scripting.
- State-changing requests are protected against cross-site request forgery.
- Login attempts are rate-limited per account and per IP, with counters in
  PostgreSQL (no Redis on the free tier).

## Same-domain API access (planned, B6)

The browser only talks to the frontend's domain; Next.js forwards `/api/...`
to the Flask API. The session cookie stays first-party, so browsers that
block cross-site cookies do not break login. To be verified on the hosting
platforms before relying on it.

## School isolation (planned, B3 and B4)

Every school-owned row has a `school_id`. The current school always comes
from the logged-in user's membership, never from the request.

1. **Application layer:** every school-owned query goes through one shared
   helper that requires the current school.
2. **Database layer:** PostgreSQL Row-Level Security policies restrict rows
   to the current school, set per request. The API connects as `sms_app`,
   which does not own the tables, so the policies cannot be bypassed by it.

Every feature that touches school data includes tests in which a School A
user tries to read and change School B data and is refused.

## Roles and permissions (planned, B4)

The roles (platform administrator, school administrator, principal, teacher,
finance officer, registrar, parent or guardian, student) map to explicit
permissions in code, such as `students.read`. Each endpoint declares the
permission it requires and the server checks it. Roles have nothing by
default.

## Sign-up (planned, B5)

There is no public sign-up. A platform administrator creates a school and
invites its first school administrator, who invites staff, parents and
students. Invitations are single-use and expire.

## Password reset (planned, B7)

Self-service reset by email requires an email provider, still to be chosen.
Until then a school administrator can reset a user's password.

## Data protection

Student records include children's personal data. The design aims for data
minimisation and audit trails, with Kenya's Data Protection Act 2019 in mind.
A qualified legal review is required before real schools use the system; this
document does not claim compliance.
