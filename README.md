# Relay Desk

A self-hosted ticketing system for SaaS product support and workplace IT.
FastAPI and PostgreSQL behind a React frontend, with LDAP authentication, email
notifications, file attachments, a business-hours SLA engine and scheduled
ticket creation.

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
requester, org and category. Every ticket has a bookmarkable URL at `/t/TKT-1234`.

**Attachments** — images, PDFs and plain text, up to 10 MB and five files at a
time. The content type is determined by sniffing the bytes, not by the
extension or the client's `Content-Type`, and files are stored under generated
names. Downloads are served with `Content-Disposition: attachment` and a
restrictive CSP, so an uploaded document cannot execute against a viewer's
session. Attachments hang off events rather than tickets, so a file on an
internal note inherits that note's visibility.

**Service levels** — deadlines are computed and stored per ticket. Optional
business-hours mode counts only working time, skipping evenings, weekends and a
configurable holiday list. Optionally pauses while a ticket waits on the
customer, so your team is not measured against someone else's response time.

**Scheduled tickets** — a ticket template that materialises on a date or a
cadence. The lead-time case ("open a ticket 30 days before the maintenance
window") is expressed by setting the first run to the computed date. Each
generated ticket carries a system event naming the schedule, which cannot be
deleted — so the audit trail shows it was created automatically rather than
filed by a person after the fact. A schedule that fails stops firing and emails
the administrators, because a compliance reminder that goes quiet is worse than
one that visibly breaks.

**Authentication** — local accounts with argon2 hashing and email verification,
plus optional per-user LDAP against FreeIPA or 389 Directory Server. Roles come
from directory group membership; a local override wins over the directory.
Sessions are JWTs in an httpOnly cookie. Login is rate limited per source IP and
per target account; registration is rate limited per IP.

**Notifications** — every event queues a row in an outbox table, drained by a
worker with exponential backoff. Customers hear about replies, resolutions and
receipts; staff hear about new tickets, assignments, customer replies, signups,
confirmed addresses and failed schedules. Internal notes email nobody.

**Admin area** — queue and delivery health at a glance, account management
(roles, activation, verification, deletion), schedule management, and a
browsable mail queue showing exactly what was sent, to whom, and why anything
was not.

---

## Running it locally

Requires PostgreSQL 14+, Python 3.10+, Node 20+, and `libmagic1`
(`apt install libmagic1`) for attachment type detection.

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

Set `UPLOAD_DIR` in `.env` to a writable path — the default
(`/var/lib/relay/uploads`) suits the container, not a development machine.

API docs at `http://127.0.0.1:8000/docs` (suppressed when `ENVIRONMENT=production`).

### Frontend

    cd web && npm install && npm run dev

Open `http://127.0.0.1:5173`. Vite proxies `/api` to the backend, so both share
an origin and CORS never applies in development.

### Background work

Neither runs on its own; notifications queue and schedules wait until they do.

    python scripts/mail_worker.py           # continuous; --once for a single pass
    python scripts/run_schedules.py         # fires anything due, then exits

Under systemd in production — see `deploy/`.

---

## Creating accounts

No credentials ship with the repository.

**On a real install**, register through the sign-in page. Local accounts must
confirm their email address before they can sign in, so configure SMTP first
(see Configuration). New registrations are customers. Promote the first staff
account from the database:

    UPDATE users SET role='admin' WHERE email='you@example.com';

Then run `python scripts/check_admin.py`, which warns if no *local* admin
exists — a state that would lock you out if the directory config broke. After
that, manage roles from the admin area.

### Demo accounts for local development

`python scripts/seed_users.py` creates two agents and two customers on
`example.com`, marked verified so no mail is needed. Each gets a random
password printed once. To choose one yourself, set `SEED_PASSWORD`:

    SEED_PASSWORD='choose-something' python scripts/seed_users.py

The seed script does not grant the admin role; promote one of them as above.

The integration scripts in `scripts/*_test.sh` sign in as a seeded agent and
customer. They read `RELAY_AGENT_EMAIL`, `RELAY_AGENT_PASSWORD`,
`RELAY_CUSTOMER_EMAIL` and `RELAY_CUSTOMER_PASSWORD`, defaulting the addresses
to the seed accounts and the passwords to `SEED_PASSWORD`. `RELAY_API` overrides
the default `http://localhost:8000/api`.

### Directory test accounts

`ldap-dev/bootstrap.ldif` defines a small directory for a local 389 DS instance
under `dc=example,dc=com`, matching the `LDAP_*` examples in `.env.example`.
Its `userPassword` values are the placeholder `CHANGE_ME_LDAP_TEST_PASSWORD`;
substitute your own before loading, and export the same value for
`scripts/ldap_test.sh`:

    export LDAP_TEST_PASSWORD='choose-something'
    sed "s/CHANGE_ME_LDAP_TEST_PASSWORD/$LDAP_TEST_PASSWORD/" ldap-dev/bootstrap.ldif > /tmp/bootstrap.ldif

Members of `cn=support-staff` resolve to the agent role; `ext` is deliberately
outside it, to prove group mapping denies as well as grants.

| Account | Resolves as |
|---|---|
| `alex.smith@example.com` | agent |
| `sam.jones@example.com` | agent |
| `ext@example.com` | customer |

---

## Configuration

Settings live in the database with `.env` as fallback: a database value wins
when set, otherwise the environment, otherwise a declared default. Administrators
edit them at `/settings`; secrets are sealed at rest with a Fernet key derived
from `SECRET_KEY` and never returned to the browser.

Three keys stay in `.env` permanently, because the app cannot bootstrap without
them: `DATABASE_URL`, `SECRET_KEY` and `UPLOAD_DIR`.

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

Data migrations run after the columns they touch exist — obvious in hindsight,
easy to get wrong when appending to a generated file.

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
is the dependable pattern. Named volumes survive it.

### systemd units

All run as the service user, not root. Templates in `deploy/`.

| Unit | Purpose |
|---|---|
| `relay-desk.service` | Brings the compose stack up at boot |
| `relay-mail.service` | Drains the notification outbox continuously |
| `relay-schedules.timer` | Fires due schedules hourly |
| `relay-backup.timer` | Backs up the database and uploads every six hours |

Boot persistence uses *user* units plus `loginctl enable-linger`, so the stack
returns after a reboot without a login session.

Two things that will confuse you otherwise:

- **Rootless containers are invisible to root.** `podman ps` as root shows
  nothing; run it as the service user.
- **`podman-compose` needs `XDG_RUNTIME_DIR`** set when entered via `su`, or it
  looks in the wrong state directory and reports containers that do not exist.

Reading the journal as the service user needs membership of `systemd-journal`.

### Backups

`scripts/backup.sh` writes a compressed `pg_dump` and a tar of the uploads
volume to `~/backups`, keeping 30 days of database dumps and the eight most
recent upload archives. It refuses to report success on a dump under 1 KB, since
a partial `pg_dump` still produces a valid-looking gzip.

**Backups are local only.** They protect against application mistakes, a bad
migration or accidental deletion — not against losing the host. Copy them
elsewhere if the data matters.

Verify a backup by restoring it rather than trusting it:

    podman exec relay-desk_db_1 psql -U relay -d postgres -c "CREATE DATABASE restoretest OWNER relay;"
    zcat ~/backups/relaydesk-*.sql.gz | podman exec -i relay-desk_db_1 psql -U relay -d restoretest
    podman exec relay-desk_db_1 psql -U relay -d restoretest -c "SELECT count(*) FROM tickets;"
    podman exec relay-desk_db_1 psql -U relay -d postgres -c "DROP DATABASE restoretest;"

---

## Known gaps

- **Backups are local only and unmonitored.** A failed backup logs to the
  journal and otherwise goes unnoticed.
- **No password reset.** A local user who forgets their password needs an
  administrator and a SQL statement.
- **Rate limiting is in-memory and per-process.** Adequate for a single
  instance; a fleet needs Redis or equivalent.
- **`style-src 'unsafe-inline'`** remains in the CSP because components use
  inline styles for priority colours. A real weakening, not a false positive.
- **Uploaded files are not scanned for malware.** Type is validated, content is
  not. Files are served as downloads rather than rendered, which bounds but does
  not eliminate the risk.
- **Recurrence treats a month as 30 days.** Calendar-correct month arithmetic
  needs a policy for the 31st in February; "about a month later" is the honest
  intent for a maintenance reminder.
- **Search is `ILIKE` only.** Fine for hundreds of tickets, not for tens of
  thousands.
- **Notification delivery latency is up to 30 seconds** and schedules fire
  hourly — both poll rather than listen.
- **`scripts/smoke.sh` and `scripts/delete_test.sh` are stale.** They pass
  `?email=` to portal endpoints that now derive identity from the session, so
  those calls fail regardless of the address used.

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
| File type detection | python-magic (libmagic) |
| Frontend | React 18, Vite |
| Typography | IBM Plex Sans / Mono |
| Containers | Podman (rootless), podman-compose |
| Scheduling | systemd timers |
| Ingress | Cloudflare Tunnel |
