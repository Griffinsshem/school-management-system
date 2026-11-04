# Frontend

Next.js web application for the School Management System.

## Setup

Run from the `frontend/` folder:

```bash
npm ci
cp --update=none .env.example .env.local
```

`npm ci` installs the exact versions recorded in `package-lock.json`.

## Run

Start the backend first (`flask --app app run` in `backend/`), then:

```bash
npm run dev
```

Open `http://127.0.0.1:3000`. The dev server listens only on this computer.

The browser only ever talks to this address: `src/proxy.ts` forwards every
`/api/...` request to the Flask API at `API_ORIGIN`. The login cookie is
therefore first-party and `HttpOnly` (page scripts cannot read it). When
`PROXY_SHARED_SECRET` is set, the forwarded requests carry it, and the API
refuses any request without it.

To test from a phone on the same network, run
`npm run dev -- --hostname 0.0.0.0` and also set the backend's
`FRONTEND_ORIGIN` to the address the phone uses (for example
`http://192.168.1.20:3000`), or logging in will be refused.

## Screens

| Address | What it does |
|---------|--------------|
| `/login` | Log in. `?next=` (a path on this site only) says where to go afterwards. |
| `/` | Your active school, role and permissions; choose or switch school; log out. Needs a login. |
| `/students` | The school's students: search by name or admission number, 50 per page (`students.read`). School admins and registrars (`students.manage`) also add, edit and deactivate students. Needs a login. |
| `/people` | The school's members and invitations (`members.read`). School admins (`members.manage`) also invite people, withdraw invitations and remove members. Needs a login. |
| `/invitations/accept#token=...` | Accept an invitation: create an account, or log in and accept. The token is removed from the address bar at once. |

## Checks

```bash
npm run lint
npm run build
npx tsc --noEmit
```

## Browser tests

Playwright drives a real Chromium through every screen, against a production
build of the frontend and a real API on the backend's test database (see
`../backend/scripts/e2e_server.py`, which empties that database and adds
clearly fake data).

Once, to download the browser:

```bash
npx playwright install chromium
```

Then, from `frontend/` with the backend's virtual environment active (the
API is started with `python`):

```bash
npx playwright test
```

Both test servers share a fake proxy secret (in `playwright.config.ts` and
`../backend/scripts/e2e_server.py`), so the frontend-to-API handshake is
tested as on the real hosts, including that the API refuses direct requests.

The tests start their own servers on ports 3100 and 5001, so `npm run dev`
and `flask run` can keep running. Do not run `pytest` at the same time: both
use the test database. The tests rebuild `.next/` for port 5001, so run
`npm run build` again before using `npm start` yourself.

After a failure, `npx playwright show-trace` with the path printed in the
output replays it step by step.

`e2e/accessibility.spec.ts` (D8) checks every main page with axe-core
(`@axe-core/playwright`, a development-only package) against WCAG 2.1
level A and AA: as a school administrator and as a class teacher, in light
and dark mode, plus error messages, notices, open forms and the logged-out
pages. Results axe marks "needs review" fail the test too. Each problem is
printed as one line with the page, the rule and what to fix. No rule is
switched off; if one ever must be, do it for that one element only, with
the reason written in the test. New pages belong in its list.

Phone-width tests run at 320 px. The report card test also forces a wide
font and a long unbroken word, and checks that every element stays on
screen, not only that the page does not scroll sideways: test machines draw
Arial with a narrow font, so a page-width check alone can pass while real
phones overflow.

## Smoke checks against staging

A few read-only checks run against the deployed staging site instead of local
servers (`playwright.staging.config.ts`, folder `e2e-staging/`): logging in
with the demo accounts, the production cookie, the Students and People pages,
and logging out. They create and change nothing, so they can run after every
deploy. The demo password is typed at a hidden prompt and never saved;
traces and screenshots are off so it is not recorded either.

```bash
read -rsp "Demo password: " STAGING_PASSWORD; echo; export STAGING_PASSWORD
STAGING_URL=https://school-management-system-one-peach.vercel.app npx playwright test -c playwright.staging.config.ts
unset STAGING_PASSWORD
```

Plain `npx playwright test` never touches staging. See
[../docs/deployment.md](../docs/deployment.md).

## Configuration

| Variable | Purpose |
|----------|---------|
| `API_ORIGIN` | Where the Flask API runs, for example `http://127.0.0.1:5000`. Server-only. Optional for `npm run dev`; required for `npm run build` and `npm start`. |
| `PROXY_SHARED_SECRET` | The same value as the API's `PROXY_SHARED_SECRET`. Server-only. Added to every forwarded `/api` request so the API knows it came through this site. Required wherever the API requires it (staging, production); leave unset for local development unless the API sets it too. |
| `TRUST_X_FORWARDED_FOR` | `1` only where the host replaces any `X-Forwarded-For` a visitor sends, so it can be passed on as the visitor's address. Not needed on Vercel, which is recognised automatically. Never set it for a self-hosted Next.js server. |

See `.env.example`. Never put secrets in variables starting with
`NEXT_PUBLIC_`: those are sent to every visitor's browser.

## Notes

- Cache Components and Partial Prefetching are enabled in `next.config.ts`.
  Never cache per-user or per-school data with `"use cache"` unless the cache
  is keyed to that user and school.
- Security headers are set in `next.config.ts`. See
  `../docs/security-notes.md`.
- Pages that need a login are wrapped in `src/components/app-shell.tsx`
  (login check, header, navigation, log out). Add new ones to the
  `matcher` in `src/proxy.ts` too.
- Next.js keeps recently visited pages hidden in the tab. Never leave a
  password in a form after it is used, and leave the logged-in area with a
  full page load (`goToLogin`), not client-side navigation.
- Pages where typed work could be lost (the register, mark sheets, report
  card comments) call `useUnsavedChanges(dirty, discard)` from
  `src/lib/unsaved-changes.ts` (D8). While anything is unsaved, links inside
  the app, Log out and the term or date selectors ask first (call
  `confirmLeave()` before any other way of leaving), and closing or
  reloading the tab shows the browser's warning. Agreeing to leave calls
  `discard`, which must put back the saved values: the hidden page is kept,
  so otherwise the discarded typing reappears when the person comes back.
  The browser's Back button inside the app is not covered: Next.js offers no
  reliable way to stop it.
- `AGENTS.md` is generated by Next.js for AI coding assistants and is kept in
  the repository intentionally.
