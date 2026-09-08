# Relay desk

A customer-facing ticketing system for SaaS product and workplace IT support.
FastAPI + PostgreSQL behind a React frontend.

Two surfaces over one dataset: a customer portal for filing and tracking
tickets, and an agent console for triage and response. Internal notes are
visible only to agents.

## Design notes

[Architecture white paper](docs/relay-desk-whitepaper.md) — why this was built rather
than bought, the authorisation boundary, the SLA engine, and what is deliberately
not implemented.

## Features

- Ticket intake with impact-based priority (customers describe blockage, not P-levels)
- SLA clocks per priority (P1 4h, P2 8h, P3 24h, P4 72h) with past-due tracking
- Queue views: all open, assigned to me, unassigned, past due, resolved
- Threaded replies with agent-only internal notes
- Soft delete on messages — text is redacted at the API boundary, the row and
  audit trail survive
- Search across ticket ref, subject, requester, org and category

## Running it

Requires PostgreSQL 14+, Python 3.10+, Node 20+.

### Database

    sudo -u postgres psql -c "CREATE ROLE relay WITH LOGIN PASSWORD 'relay_dev';"
    sudo -u postgres psql -c "CREATE DATABASE relaydesk OWNER relay;"

### Backend

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env          # adjust if your Postgres differs
    alembic upgrade head
    python scripts/seed.py        # optional demo data; TRUNCATES both tables
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

API docs at http://127.0.0.1:8000/docs

### Frontend

    cd web && npm install && npm run dev

Open http://127.0.0.1:5173. Vite proxies `/api` to the backend, so both run on
one origin and CORS never applies in development.

## Development accounts

Created by `python scripts/seed_users.py` (idempotent). **Local development only** —
these passwords are in the seed script and this file. Change them before any
deployment, and before this repository becomes public.

| Account | Role | Password |
|---|---|---|
| `jamal@relaydesk.io` | admin | `devpassword123` |
| `rokafor@relaydesk.io` | agent | `devpassword123` |
| `dana@northgate.io` | customer | `devpassword123` |
| `priya@ferrous.dev` | customer | `devpassword123` |

The admin role is not granted by the seed script. Promote an account manually:

    UPDATE users SET role='admin' WHERE email='jamal@relaydesk.io';

Run `python scripts/check_admin.py` afterwards — it warns if no local admin exists,
which would leave you locked out if the directory config breaks.

### Directory test accounts

Loaded into the local 389 DS instance by `ldap-dev/bootstrap.ldif`, password
`LdapTest123!`. Members of `cn=support-staff` resolve to the agent role; `ext`
is deliberately outside it, to prove group mapping denies as well as grants.

| Account | Resolves as |
|---|---|
| `jamal.nasir@relaydesk.test` | agent |
| `tremaine.hart@relaydesk.test` | agent |
| `ext@relaydesk.test` | customer |

## Schema changes

Alembic owns the schema. Never use `create_all`.

    alembic revision --autogenerate -m "what changed"
    alembic upgrade head

Autogenerate does not detect `Sequence` objects — `ticket_ref_seq` is created
by explicit `op.execute` in the baseline migration.

## Tests

    ./scripts/smoke.sh          # status transitions, note containment, view filters
    ./scripts/delete_test.sh    # soft delete rules and redaction

Both mutate seeded data; re-run `scripts/seed.py` afterward.

## Authentication

Local accounts (argon2) with optional LDAP per user. A local account never
touches the directory; anyone else is tried against LDAP and provisioned on
first successful bind. Roles come from LDAP group membership, and a local
`role_override` column wins over whatever the directory says.

Sessions are JWTs in an httpOnly cookie. Agent endpoints require the agent
role; portal endpoints derive the customer's identity from the session rather
than from a request parameter.

## Notifications

Events queue rows in `outbox`; `scripts/mail_worker.py` drains it with
exponential backoff (1/5/20/60m, five attempts). Customers are emailed on agent
replies and on resolution; agents on assignment and on customer replies.
Internal notes email nobody.

`SMTP_ALLOWLIST` is a hard guard — recipients outside it are stored as
`suppressed` rather than sent. Keep it narrow until the routing is trusted.

    python scripts/mail_worker.py           # continuous
    python scripts/mail_worker.py --once    # single pass

Under systemd, so it survives restarts — see `deploy/relay-mail.service.example`:

    sudo cp deploy/relay-mail.service.example /etc/systemd/system/relay-mail.service
    # edit User and the paths, then
    sudo systemctl daemon-reload && sudo systemctl enable --now relay-mail
    journalctl -u relay-mail -f

## Known gaps

- SLA is elapsed wall-clock. It does not respect business hours and does not
  pause while a ticket waits on the customer.
- No self-service password reset.
- Delivery latency is up to 30 seconds (the worker polls rather than listening).
- No rate limiting on the login endpoint.

## Dependency advisories

`./scripts/audit.sh` reports open advisories in starlette 0.41.3, pinned by
FastAPI. They concern `request.url` reconstruction from a malformed `Host`
header or request path, and are exploitable only where authorization decisions
read `request.url`. This application authorizes via route dependencies
(`require_agent`, `require_admin`), which run after routing on the matched
route, and never reads `request.url`. The only middleware is CORS.

**If path-based authorization middleware is ever added, upgrade FastAPI and
starlette first.**

The remaining `cryptography` advisories cover X.509 chain verification and
PKCS#7 decryption. This application uses Fernet only.
