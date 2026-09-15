# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Relay Desk is a self-hosted ticketing system: a FastAPI + PostgreSQL backend
and a React (Vite) SPA. Customers file and track tickets in a portal; staff
triage and reply in a console. It is a single deployable product, not a
monorepo. See `README.md` for the operator-facing narrative and
`docs/relay-desk-whitepaper.md` for the design rationale.

> Note: a workspace-level `CLAUDE.md` in a parent directory may describe an unrelated
> DevOps workspace. It does not apply here — this file governs `relay-desk/`.

## Environment

**Use `/usr/bin/git`, never the bare `git` command.** On this WSL setup `git`
is aliased to the Windows git executable, which cannot operate on WSL paths.
Invoke `/usr/bin/git` explicitly for every git operation.

**`.env` holds live credentials** — the Gmail app password, `SECRET_KEY`, and
the Postgres password. Never read, print, or echo its contents.

**The production deployment holds real user data.**
Local development uses seed data (`scripts/seed.py`, `scripts/seed_users.py`).
Keep the two straight — never point local tooling or destructive commands at
production.

## Common commands

Backend (from repo root, with `.venv` active):

```bash
source .venv/bin/activate
alembic upgrade head                       # apply migrations (never create_all)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
python scripts/seed.py                     # demo tickets — TRUNCATES tickets+events
python scripts/seed_users.py               # demo accounts (see README for logins)
```

Frontend (`web/`):

```bash
npm install
npm run dev        # Vite on :5173, proxies /api to :8000 (so no CORS in dev)
npm run build      # emits web/dist — the backend serves this as ./static
npm run lint       # oxlint
```

Background jobs (neither runs on its own; nothing is delivered/fired until they do):

```bash
python scripts/mail_worker.py              # drains the outbox continuously; --once for one pass
python scripts/run_schedules.py            # fires due schedules, then exits
```

Integration tests — **scripts against a running server, not unit tests, not in CI**:

```bash
./scripts/guard_test.sh    # authorisation boundary — the important one; exits non-zero on failure
./scripts/sla_test.sh      # deadline recalculation and pause-on-customer
./scripts/delete_test.sh   # soft-delete rules (stale — passes ?email= to session-based endpoints)
./scripts/audit.sh         # dependency CVEs + static analysis
```

`scripts/smoke.sh` and `scripts/delete_test.sh` are known-stale (they pass
`?email=` to portal endpoints that now derive identity from the session).

## Architecture

### The authorisation boundary (the core invariant)

Everything hinges on one rule: **internal notes and their attachments never
cross into a portal response.** Read `app/api.py` top to bottom — it is split
by a literal comment (`# --- portal: no internal notes ever cross this line ---`).

- Auth is enforced by FastAPI route dependencies in `app/auth.py`:
  `current_user` (401 if not signed in), `require_agent` (403 for customers),
  `require_admin`. These run *after* routing, on the matched route — the app
  never authorises off `request.url` (this is why the pinned starlette
  advisories are assessed as non-exploitable; see README).
- Portal endpoints scope every query to `Ticket.email == me.email` and then
  strip non-`comment` events (`d.events = [e for e in ... if e.kind == "comment"]`).
- Attachments hang off **events, not tickets** (`app/models.py`), so a file on
  an internal note inherits that note's invisibility for free. `_attachment_or_404`
  in `app/api.py` re-derives access from the parent event's ticket + kind.

When touching any endpoint, preserve this and re-run `guard_test.sh`. That is
the class of bug scanners cannot find.

### Roles and identity

`User.effective_role` = `role_override` if set, else the stored `role` (from the
last successful login / LDAP group mapping). `is_staff` = agent or admin.
Two auth sources per user (`app/auth_api.py`): `local` (argon2, requires
`email_verified` before login) and `ldap` (per-user bind via `app/ldap_client.py`;
role comes from `ldap_agent_group` membership, but a local `role_override` still
wins). Sessions are JWTs (HS256, `app/security.py`) in an httpOnly cookie named
`relay_session`. Login is rate-limited per IP and per account (`app/ratelimit.py`,
in-memory/per-process — a fleet would need Redis).

### Settings: database-first with `.env` fallback

`app/settings_store.py` is the source of truth for runtime config. `get()`
resolves database value → `.env` (via the `env_attr` on each `Spec`) → declared
`DEFAULTS`. Admins edit these at `/settings` (`app/settings_api.py`). Secrets
(`secret=True` specs) are sealed with Fernet (`app/secrets_box.py`, key derived
from `SECRET_KEY`) and never returned to the browser — the API sends a `MASK`
and an empty submit leaves the stored value untouched.

Only three keys live permanently in `.env` because the app can't bootstrap
without them: `DATABASE_URL`, `SECRET_KEY` (≥32 bytes), `UPLOAD_DIR`.
**Rotating `SECRET_KEY` invalidates all sessions and makes stored secrets
unreadable.** When adding a config knob, add a `Spec` to `SPECS` and (if it has
no `.env` backing) a `DEFAULTS` entry.

### SLA engine

`app/sla.Calendar` computes and **stores** `Ticket.due_at`. Two modes: wall-clock
(add hours) or business-hours (walk the calendar counting only working minutes,
skipping weekends/holidays). Optional pause-on-customer: while a ticket is
"Waiting on customer" the clock stops, and on resume the deadline is pushed out
by the working time lost. All the transition logic lives in
`services.apply_patch` — priority changes recompute from `created_at`, status
changes drive pause/resume. Business-hours config (timezone, days, holidays,
targets) comes from the settings store.

### Events, tickets, soft delete

A ticket owns an ordered list of `Event`s (`comment` / `note` / `system`).
Two events are protected from deletion (`services.delete_event`): `system`
events (audit trail) and the `is_original` event (the customer's first
description). Deletion is soft (`deleted_at` / `deleted_by`), leaving a
tombstone. `services.add_event` also advances ticket state (first-response
timestamp, New→Open, Waiting→Open on a customer reply).

### Notifications (outbox pattern)

`app/notify.py` never sends inline — it queues rows in the `outbox` table
(`_queue`). `scripts/mail_worker.py` drains them with exponential backoff.
`SMTP_ALLOWLIST` is a safety valve: recipients outside it are stored as
`suppressed` rather than sent, so routing can be verified against the table.
Verification emails bypass the allowlist deliberately. `notes and system events
notify nobody` — check `on_event` before assuming an event mails anyone.

### Scheduled tickets

`Schedule` rows are ticket templates that materialise on a date or cadence.
`app/scheduler.run_due` (invoked by `scripts/run_schedules.py` on a timer) fires
due schedules with `SELECT ... FOR UPDATE SKIP LOCKED`, stamps each generated
ticket with an undeletable `system` event naming the schedule, and advances
`next_run_at`. A schedule that raises is set to `status="failed"` (stops firing)
and emails admins — a silent compliance reminder is worse than a visibly broken
one. Recurrence months = 30 days deliberately.

### Attachment safety (`app/storage.py`)

Three deliberate rules: (1) stored filenames are generated
(`secrets.token_hex`), never derived from client input — path traversal is
structurally impossible; (2) content type is **sniffed from bytes** via libmagic
against an allowlist, never trusted from the extension or `Content-Type`;
(3) downloads are served `Content-Disposition: attachment` + `nosniff` + a
locked-down CSP, so an uploaded file cannot execute against a viewer's session.
The download route also strips the `Range` header before it reaches Starlette's
quadratic parser (PYSEC-2026-1942).

### Frontend

React 19 + Vite, no router library. `web/src/route.js` parses `window.location`
(`/t/TKT-1234`, `/settings/<section>`, else home) and the server serves
`index.html` for any unmatched path (`app/main.py` SPA fallback). `web/src/App.jsx`
switches between `AgentConsole` (staff), `Portal` (customers), and `Settings`
(admins) off `me.role`. `web/src/api.js` / `auth.js` wrap fetch. Lint is oxlint,
not eslint.

## Migrations (Alembic owns the schema)

The app never calls `create_all` — `entrypoint.sh` runs `alembic upgrade head`
on container start. `alembic revision --autogenerate -m "..."` then edit.
Autogenerate reliably misses three things that have bitten this project:

- **Sequences** — `ticket_ref_seq` is created by explicit `op.execute` in the
  baseline. `services.next_ref` calls `nextval` directly.
- **`CHECK` constraint changes** — e.g. adding the `admin` role needed a
  hand-written `drop_constraint` / `create_check_constraint` pair. The model-side
  constraints are built from the tuples at the top of `app/models.py`
  (`PRIORITIES`, `STATUSES`, `ROLES`, etc.) via the `_in()` helper — changing an
  allowed value means both editing the tuple *and* writing the constraint migration.
- **`NOT NULL` on existing rows** — add with a `server_default`, then drop it.

## Deployment

Production: Rocky Linux 9 VPS, rootless Podman, three containers (`compose.yaml`:
`db`, `app`, `worker`), Cloudflare Tunnel (no inbound port). The app container
builds the SPA in a Node stage and serves `web/dist` as `./static`. systemd
*user* units + `loginctl enable-linger` in `deploy/` run the schedule timer,
backup timer, and mail worker. `podman-compose` doesn't reliably detect a
changed image — redeploy with `down` then `up`, not just `up`. Rootless
containers are invisible to root; run `podman ps` as the service user.
