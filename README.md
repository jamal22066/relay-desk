# Relay desk

A customer-facing ticketing system for SaaS product and workplace IT support.
FastAPI + PostgreSQL behind a React frontend.

Two surfaces over one dataset: a customer portal for filing and tracking
tickets, and an agent console for triage and response. Internal notes are
visible only to agents.

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

## Known gaps

- **No authentication.** Agent endpoints are open, so internal notes are
  readable by anyone who can reach the API. The portal identifies customers by
  email address alone.
- All agent actions are attributed to a single hardcoded user.
- SLA is elapsed wall-clock. It does not respect business hours and does not
  pause while a ticket waits on the customer.
- Nothing sends email, despite what the portal confirmation says.
