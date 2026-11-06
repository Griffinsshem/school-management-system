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
| `/` | Your active school and role, and links to the pages your role can open, grouped by area (classes and teaching, students and staff, calendar and grading, fees). What your role allows is folded under a closed heading. Choose or switch school. Needs a login. |
| `/students` | The school's students: search by name or admission number, 50 per page (`students.read`). School admins and registrars (`students.manage`) also add, edit and deactivate students. Needs a login. |
| `/people` | The school's members and invitations (`members.read`). School admins (`members.manage`) also invite people, withdraw invitations and remove members. Needs a login. |
| `/fees` | Fees for a school year and term (`?year=&term=`, today's term by default): each grade with classes that year, its fee structure and how many students are billed (`fees.read`). |
| `/fees/{year}/{term}/{grade}` | A grade's fees for a term: the fee structure, edited until bills are issued (`fees.manage`), issuing bills after a confirmation, and the bills. |
| `/fees/bills/{id}` | One bill: its lines, total, what is paid and the balance (or credit), its payments, the guardians to contact; (`fees.manage`) adding an optional item or an adjustment; (`payments.record`) recording a payment; (`payments.cancel`) cancelling one with a reason. |
| `/fees/receipts/{id}` | A payment's receipt, ready to print (E2); marked CANCELLED with the reason when cancelled (`fees.read`). |
| `/fees/payments?date=` | Payments recorded on a day (today by default), with totals by method; cancelled ones listed but not counted (`fees.read`). |
| `/invitations/accept#token=...` | Accept an invitation: create an account, or log in and accept. The token is removed from the address bar at once. |

## Look and feel

Every logged-in page has the same frame (`src/components/app-shell.tsx`):
a dark band with the school's name, the person's name and Log out, and the
menu below it. The page being shown is underlined in red. On a phone the menu
folds away behind a **Menu** button, which says whether it is open
(`aria-expanded`) and closes again when a page is chosen. Who sees which menu
link is decided once, in `menuLinks`, which the home page uses too.

Colours have names, defined once in `src/app/globals.css` with a light,
a dark and a printed value: `ink` (text), `muted` (secondary text), `paper`
and `surface` (backgrounds), `rule` and `rule-strong` (lines), `field`
(input borders), `band`, `action` (main buttons), `link`, `margin` (the
thin red line), `ok`, `warn` and `danger`. Pages use these names
(`text-muted`, `border-rule`, `bg-action`, ...), never Tailwind's own colours
such as `text-zinc-600`, so a colour changes in one place and dark mode
needs no `dark:` classes. Every text colour meets WCAG AA contrast on the
backgrounds it is used on. A new colour must be checked the same way, and
the accessibility tests will fail if it is not good enough.

Shared pieces live in `src/components/ui.tsx`: buttons (`buttonClass`,
`inlineButtonClass`, `secondaryButtonClass`, `dangerButtonClass` for the
"Yes, remove" of a confirmation), `inputClass`, `ErrorMessage` and `Notice`.
On the fee pages, money uses `amountClass` (right-aligned, never split over
two lines), and every table lines its figures up (`tabular-nums`).

The typeface is Atkinson Hyperlegible Next, made for readers with low vision
(0 and O, 1, l and I are easy to tell apart). It comes from the
`@fontsource-variable/atkinson-hyperlegible-next` package (free, SIL Open
Font License) and is served from this site, so no page asks Google or any
other server for fonts.

Printed report cards keep dark text and the same greys on white paper, even
when the screen is in dark mode.

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
output replays it step by step. When browser tests fail on GitHub Actions,
the traces are kept for 7 days as a download named `playwright-traces` on
the run's page; `gh run download <run id> -n playwright-traces` fetches them.

`e2e/accessibility.spec.ts` (D8) checks every main page with axe-core
(`@axe-core/playwright`, a development-only package) against WCAG 2.1
level A and AA: as a school administrator and as a class teacher, in light
and dark mode, plus error messages, notices, open forms, a confirmation with its red
button, and the logged-out pages. Results axe marks "needs review" fail the test too. Each problem is
printed as one line with the page, the rule and what to fix. No rule is
switched off; if one ever must be, do it for that one element only, with
the reason written in the test. New pages belong in its list. The check
itself is in `e2e/axe.ts`, shared with `e2e/fees.spec.ts`, which checks the
fee pages in each state (open form, errors, confirmation, issued, bill).

The home page repeats the menu's links, so a test that means the menu
clicks inside it: `page.getByRole("navigation", { name: "Main" })`. The list
of what a role allows starts closed; `openRoleAllows(page)` in
`e2e/helpers.ts` opens it before a test reads it.

`e2e/fees.spec.ts` (E1) gives each test a school year of its own, far in the
future, so the bills it issues never reach other tests' students. It logs
in as School C's finance officer (`e2e.finance@example.com`, created by
`e2e_server.py`) as well as the administrator and teacher.
`e2e/payments.spec.ts` (E2) does the same (shared set-up in
`e2e/fees-data.ts`) and makes its own M-Pesa codes; receipt numbers are
shared by the whole school, so its tests read them rather than assume them.

Phone-width tests run at 320 px. The report card and fee tests also force a
wide font and a long unbroken word, and check that every element stays on
screen, not only that the page does not scroll sideways: test machines draw
Arial with a narrow font, so a page-width check alone can pass while real
phones overflow. The fee test also uses the longest class stream (20) and
admission numbers (30) a school can enter; without them, its tables fit
even with their safety net removed, and the test would prove nothing.

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
