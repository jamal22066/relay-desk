# Relay Desk

A self-hosted ticketing system for SaaS product support and workplace IT.
FastAPI and PostgreSQL behind a React frontend, with LDAP authentication,
email notifications and a business-hours SLA engine.

Running at **[relaydesk.us](https://relaydesk.us)**.

## Design notes

[Architecture white paper](docs/relay-desk-whitepaper.md) — why this was built
rather than bought, the authorisation boundary, the SLA engine, and what is
deliberately not implemented.

[Security review](docs/security-review.md) — findings from dependency auditing,
static analysis and ZAP scanning, what was fixed, and what was assessed and
deferred with reasoning.

---

## What it does

Two surfaces over one dataset. Customers file and track tickets in a portal;
staff triage and respond in a console. Internal notes are visible only to staff
and never leave the building.

**Tickets** — impact-based priority at intake (customers describe how blocked
they are, not P-levels), threaded replies, internal notes, soft deletion that
leaves a tombstone rather than erasing history, and search across ref, subject,
requester, org and category.

**Service levels** — deadlines are computed and stored per ticket. Optional
business-hours mode counts only working time, skipping evenings, weekends and a
configurable holiday list. Optionally pauses while a ticket waits on the
customer, so your team is not measured against someone else's response time.

**Authentication** — local accounts with argon2 hashing and email verification,
plus optional per-user LDAP against FreeIPA or 389 Directory Server. Roles come
from directory group membership; a local override wins over the directory.
Sessions are JWTs in an httpOnly cookie.

**Notifications** — every event queues a row in an outbox table, drained by a
worker with exponential backoff. Customers hear about replies, resolutions and
receipts; staff hear about new tickets, assignments and customer replies.
Internal notes email nobody.

**Admin area** — queue and delivery health at a glance, account management
(roles, activation, verification, deletion), and a browsable mail queue showing
exactly what was sent, to whom, and why anything was not.

---

## Running it locally

Requires PostgreSQL 14+, Python 3.10+, Node 20+.

### Database

    sudo -u postgres psql -c "CREATE ROLE relay WITH LOGIN PASSWORD 'relay_dev';"
    sudo -u postgres psql -c "CREATE DATABASE relaydesk OWNER relay;"

### Backend

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env
    # SECRET_KEY must be at least 32 bytes:
    python3 -c "import secrets; print(secrets.token_urlsafe(48))"
    alembic upgrade head
    python scripts/seed.py        # optional demo tickets; TRUNCATES both tables
    python scripts/seed_users.py  # optional demo accounts
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

API docs at `http://127.0.0.1:8000/docs` (suppressed when `ENVIRONMENT=production`).

### Frontend

    cd web && npm install && npm run dev

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the backend, so both share
an origin and CORS never applies in development.

### Mail worker

Notifications queue whether or not the worker runs; nothing sends until it does.

    python scripts/mail_worker.py           # continuous
    python scripts/mail_worker.py --once    # single pass

Under systemd so it survives restarts — see `deploy/relay-mail.service.example`.

---

## Development accounts

Created by `python scripts/seed_users.py`. **Local development only** — these
passwords are in the seed script and in this file.

| Account | Role | Password |
|---|---|---|
| `jamal@relaydesk.io` | agent | `devpassword123` |
| `rokafor@relaydesk.io` | agent | `devpassword123` |
| `dana@northgate.io` | customer | `devpassword123` |
| `priya@ferrous.dev` | customer | `devpassword123` |

The admin role is not granted by the seed script. Promote an account manually:

    UPDATE users SET role='admin' WHERE email='jamal@relaydesk.io';

Then run `python scripts/check_admin.py`, which warns if no *local* admin
exists — a state that would lock you out if the directory config broke.

### Directory test accounts

Loaded into a local 389 DS instance by `ldap-dev/bootstrap.ldif`, password
`LdapTest123!`. Members of `cn=support-staff` resolve to the agent role; `ext`
is deliberately outside it, to prove group mapping denies as well as grants.

| Account | Resolves as |
|---|---|
| `jamal.nasir@relaydesk.test` | agent |
| `tremaine.hart@relaydesk.test` | agent |
| `ext@relaydesk.test` | customer |

---

## Configuration

Settings live in the database with `.env` as fallback: a database value wins
when set, otherwise the environment, otherwise a declared default. Administrators
edit them at `/settings`; secrets are sealed at rest with a Fernet key derived
from `SECRET_KEY` and never returned to the browser.

Two keys stay in `.env` permanently, because the app cannot bootstrap without
them: `DATABASE_URL` and `SECRET_KEY`.

**Rotating `SECRET_KEY` invalidates every session and makes stored secrets
unreadable.** The app falls back to `.env` for those, but anything entered
through the settings page must be re-entered.

`SMTP_ALLOWLIST` is a safety valve. Recipients outside it are stored as
`suppressed` rather than sent, so notification routing can be verified against a
database table instead of an inbox. Keep it narrow until the routing is trusted;
`*` disables the guard. Verification emails bypass it deliberately — the address
was just typed by whoever is registering, and the content is fixed.

---

## Schema changes

Alembic owns the schema. The application never calls `create_all`.

    alembic revision --autogenerate -m "what changed"
    alembic upgrade head

Three things autogenerate gets wrong, all of which have bitten this project:

- **Sequences are invisible to it.** `ticket_ref_seq` is created by explicit
  `op.execute` in the baseline migration.
- **`CHECK` constraint changes are not detected.** Adding the `admin` role
  needed a hand-written `drop_constraint` / `create_check_constraint` pair.
- **`NOT NULL` columns fail on existing rows** without a `server_default`. Add
  the column with one, then drop it so future inserts use the model default.

---

## Testing

    ./scripts/audit.sh          # dependency CVEs and static analysis
    ./scripts/guard_test.sh     # authorisation boundary — exits non-zero on failure
    ./scripts/sla_test.sh       # deadline recalculation and pause-on-customer
    ./scripts/delete_test.sh    # soft-delete rules and redaction

`guard_test.sh` is the important one. It asserts across three identities that
anonymous callers get 401, customers get 403 on every agent endpoint, portal
queries return only the session's own tickets, and no internal note appears in a
portal response. That is the class of bug scanners cannot find.

These are integration scripts against a running server, not unit tests, and they
do not run in CI.

---

## Deployment

Production runs on a Rocky Linux 9 VPS: rootless Podman, three containers, and
a Cloudflare Tunnel so no inbound port is open at all.

    git clone <repo> && cd relay-desk
    cp .env.production.example .env     # fill in SECRET_KEY and POSTGRES_PASSWORD
    podman-compose build
    podman-compose up -d

Migrations run automatically on container start via `entrypoint.sh`.

Deploying an update:

    git pull
    podman-compose build app
    podman-compose down && podman-compose up -d

`podman-compose` does not reliably detect a changed image, so `down` then `up`
is the dependable pattern. The `pgdata` volume survives it.

Two things that will confuse you otherwise:

- **Rootless containers are invisible to root.** `podman ps` as root shows
  nothing; run it as the service user.
- **`podman-compose` needs `XDG_RUNTIME_DIR`** set when entered via `su`, or it
  looks in the wrong state directory and reports containers that do not exist.

Boot persistence uses a systemd *user* unit plus `loginctl enable-linger`, so
the stack returns after a reboot without a login session.

Backups are `podman exec <db-container> pg_dump -U relay relaydesk > backup.sql`
— the data lives in a named volume, not on the host filesystem.

---

## Known gaps

- **No password reset.** A local user who forgets their password needs an
  administrator and a SQL statement.
- **Rate limiting is in-memory and per-process.** Adequate for a single
  instance; a fleet needs Redis or equivalent.
- **`style-src 'unsafe-inline'`** remains in the CSP because components use
  inline styles for priority colours. A real weakening, not a false positive.
- **No attachments.** Support tickets frequently need a screenshot or a log.
- **Search is `ILIKE` only.** Fine for hundreds of tickets, not for tens of
  thousands.
- **Delivery latency up to 30 seconds** — the worker polls rather than listening.
- **`scripts/smoke.sh` and `scripts/delete_test.sh` are stale.** They pass
  `?email=` to portal endpoints that now derive identity from the session, so
  those calls fail regardless of the address used.
- **Development credentials are committed** in `scripts/seed_users.py` and above.
  Acceptable while the repository is private; change them before that stops
  being true.

## Dependency advisories

`./scripts/audit.sh` reports open advisories in starlette, pinned by FastAPI.
They concern `request.url` reconstruction from a malformed `Host` header or
request path, and are exploitable only where authorisation decisions read
`request.url`. This application authorises via route dependencies
(`require_agent`, `require_admin`), which run after routing on the matched
route, and never reads `request.url`.

**If path-based authorisation middleware is ever added, upgrade FastAPI and
starlette first.**

The remaining `cryptography` advisories cover X.509 chain verification and
PKCS#7 decryption. This application uses Fernet only.

---

## Stack

| Layer | Choice |
|---|---|
| API | FastAPI, Pydantic 2 |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Database | PostgreSQL 14+ |
| Passwords | argon2-cffi |
| Sessions | PyJWT, HS256 in an httpOnly cookie |
| Directory | ldap3, FreeIPA / 389 DS |
| Secrets at rest | cryptography (Fernet) |
| Frontend | React 18, Vite |
| Typography | IBM Plex Sans / Mono |
| Containers | Podman (rootless), podman-compose |
| Ingress | Cloudflare Tunnel |
