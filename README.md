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

## Screenshots

### Agent console

![Relay Desk agent console: a queue of open tickets on the left with priority,
reference and SLA countdown per row, and the detail pane for TKT-1041 showing
status, priority and owner controls, a red past-due SLA bar, and a three-message
thread whose last entry is tagged "Internal, not sent"](docs/screenshots/agent-console.png)

Staff see every ticket. The counts down the left are live queue filters, and the
clock on each row is the stored deadline counting down — negative and red once
it is blown, which is why "Past due" reads 4. The last message in the thread
carries the *Internal, not sent* tag: that is an internal note, and this is the
only surface it appears on.

![Ticket TKT-1045 in the agent console with a reply carrying an attachment
chip reading "vpn-connection-log.txt 907 B"](docs/screenshots/attachment.png)

Attachments hang off events rather than tickets, so this log inherits the
visibility of the reply it is attached to — the same file on an internal note
would be invisible to the customer along with the note. The content type is
decided by sniffing the file's bytes rather than trusting the `.txt` extension
or the browser's `Content-Type`, and the stored filename is generated, so a
crafted name cannot escape the upload directory.

### Customer portal

![Relay Desk customer portal: a "Tell us what broke" filing form with service
line, topic and impact dropdowns above a one-line summary and description, and
below it a "Your tickets" list showing TKT-1041 with an agent
reply](docs/screenshots/customer-portal.png)

The same ticket, TKT-1041, as the customer who filed it sees it. Impact is
described in plain language — "Annoying, I can work around it" — rather than a
P-level, and the response target for that choice is stated before filing. The
internal note visible in the agent shot is absent here, and not because the
browser hides it: portal endpoints strip every non-comment event server-side, so
the note is never serialised into the response at all.

### Scheduled tickets

![Relay Desk schedules admin page listing one schedule, "EKS maintenance prep —
prod cluster", with status completed, cadence once, no next run, one run so far,
assigned to A. Rivera, and Run now and Delete
actions](docs/screenshots/schedules.png)

Schedules are ticket templates that fire on a date or a cadence. This one has
fired once and gone to `completed`; a recurring schedule would show its next run
in place of the em-dash. `Run now` fires a schedule immediately instead of
waiting for the timer.

![The new schedule form filled in for "EKS maintenance prep — prod cluster":
repeats once, a first-run date, filed on behalf of Priya Raghavan, assigned to
A. Rivera, service line Workplace IT, topic Laptop & hardware, priority P3, and
a ticket subject and description](docs/screenshots/schedule-form.png)

Creating that schedule. "First run" is the date the *ticket* should appear, not
the date of the work — set it 30 days before a maintenance window and the ticket
opens with the lead time already built in.

![Ticket TKT-1048 in the agent console, generated by the schedule: the
customer's description, then a greyed system line reading "Created automatically
by schedule EKS maintenance prep — prod cluster (#1) — Scheduler", then an agent
reply showing a Remove control that the other two entries do not
have](docs/screenshots/scheduled-ticket.png)

The ticket that schedule produced. Between the customer's description and the
agent's reply sits a system event naming the schedule that created it. Hovering
a message reveals its `Remove` control — the agent reply has one; the system
event and the original description do not, and the API refuses to delete either.
That is what keeps the audit trail honest: a scheduled ticket cannot be quietly
reattributed to a person who filed it after the fact.

### Administration

![Relay Desk admin overview: tiles for open, unassigned, past due and
due-within-4h tickets, a breakdown by priority, an email queue split into sent,
queued, suppressed and failed, schedule and account counts, and a recent
activity list](docs/screenshots/admin-overview.png)

Queue health and delivery health on one page. The *suppressed* count is the
`SMTP_ALLOWLIST` safety valve working as intended — a recipient outside the
allowlist is recorded rather than sent, so routing can be verified without
mailing real people. It is counted separately from *failed* precisely so the two
are never confused: nothing here is a delivery error.

![Relay Desk accounts page: four accounts listed with a role dropdown, auth
source, status, ticket count and last-seen column each, plus Disable and Delete
actions](docs/screenshots/accounts.png)

Everyone who can sign in. The role dropdown sets a local override that wins over
the directory, which is how someone is promoted without touching LDAP groups.
Deleting an account leaves its tickets in place, and neither your own account
nor the last remaining administrator can be removed.

![Relay Desk directory settings: Enable LDAP checked, with server URL, service
account DN, a masked service account password, user search base, user filter,
group search base and agent group DN, each tagged "from
.env"](docs/screenshots/directory.png)

Staff can authenticate against LDAP or FreeIPA with a per-user bind. Membership
of the agent group DN grants the agent role, though a role set on the Accounts
page still overrides the directory. Note the service account password: secrets
are sealed before storage and never sent back to the browser, so the field shows
a mask and submitting it untouched leaves the stored value alone.

![Relay Desk service level settings: P1 to P4 targets in hours, checkboxes for
business-hours-only and pause-while-waiting-on-customer, and working day start,
end and days fields](docs/screenshots/service-levels.png)

Response targets per priority, and the working calendar that business-hours mode
walks. The two checkboxes are what switch the engine from wall-clock to working
time and stop the clock while a ticket sits with the customer. The `from .env`
badges show where each value is currently resolving from — settings are
database-first and fall back to the environment, so a target can be changed here
without a redeploy.

![Relay Desk email delivery settings: enable-email checkbox, SMTP host, port,
username, a masked password, from address and name, recipient allowlist and app
URL, each tagged either "from .env" or "set here" with a Reset
button](docs/screenshots/email-delivery.png)

Outbound relay configuration. The badges are the settings model made visible: a
value tagged *from .env* is falling back to the environment, while *set here*
means a database override is in force and can be reverted with `Reset`. The
password reads as a mask — secrets are sealed before storage and never returned
to the browser, and submitting the field untouched leaves the stored value
alone. The recipient allowlist is the safety valve: anything outside it is
recorded as suppressed rather than sent.

![Relay Desk mail queue: filter tabs for all, queued, sent, suppressed and
failed, above a table of notifications showing status, recipient, ticket
reference, subject, reason code and created time, each row with Body and Retry
actions](docs/screenshots/mail-queue.png)

Nothing is emailed inline. Every notification is queued as a row here and
drained by a separate worker, so what the system intended to send is inspectable
after the fact — `Body` shows the exact message, `Retry` requeues a failure. The
`reason` column says which rule produced each message, and these are all
*suppressed*: the recipients fell outside the allowlist, so they were recorded
instead of delivered. Notes and system events appear nowhere here, because they
notify nobody.

![Relay Desk notifications settings: nine checkboxes controlling which events
generate email, all enabled, above a disabled "No changes"
button](docs/screenshots/notifications.png)

Which events generate email. These live in the database rather than the
environment, so changing one takes effect without a redeploy. There is no switch
for internal notes, because notes and system events never generate email at all.

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

### Single sign-on test realm

`keycloak-dev/relay-desk-realm.json` is an export of the local Keycloak realm
used to develop OIDC, so the test IdP can be rebuilt from scratch. Import it
into a throwaway container:

    # substitute the two placeholders first — the committed file has neither a
    # usable client secret nor a usable password
    export KC_CLIENT_SECRET='choose-something'
    export KC_TEST_PASSWORD='choose-something-else'
    mkdir -p /tmp/kc-import
    sed -e "s/CHANGE_ME_KEYCLOAK_CLIENT_SECRET/$KC_CLIENT_SECRET/" \
        -e "s/CHANGE_ME_KEYCLOAK_TEST_PASSWORD/$KC_TEST_PASSWORD/" \
        keycloak-dev/relay-desk-realm.json > /tmp/kc-import/relay-desk-realm.json

    podman run -d --name relay-keycloak -p 127.0.0.1:8081:8080 \
      -e KEYCLOAK_ADMIN=admin -e KEYCLOAK_ADMIN_PASSWORD=admin \
      -v /tmp/kc-import:/opt/keycloak/data/import:ro \
      quay.io/keycloak/keycloak:latest start-dev --import-realm

Set `OIDC_CLIENT_SECRET` in `.env` to the same value as `KC_CLIENT_SECRET`.
The realm comes up at `http://127.0.0.1:8081/realms/relay-desk`, with the
`relay-desk` client already holding `http://127.0.0.1:5173/*` as both a redirect
and a post-logout redirect URI.

Group membership drives the role, exactly as with the directory:

| Account | Keycloak group | Resolves as |
|---|---|---|
| `admin@example.com` | `administrators` | admin |
| `agent@example.com` | `support-staff` | agent |
| `customer@example.com` | none | customer |

A local `role_override` still beats whatever the IdP claims.

Two things are deliberately absent from the committed export. The realm's
signing and encryption keys were stripped — Keycloak generates fresh ones on
import, and a private key that signs ID tokens has no business in a repository.
User passwords are the placeholder rather than the original PBKDF2 hashes, so
the file carries no credential material at all.

Re-exporting is not quite the documented one-liner: `start-dev` holds an
exclusive lock on its H2 file, so `kc.sh export` cannot run inside the live
container. Stop it, copy the data out, and export from a throwaway container
against that copy:

    podman stop relay-keycloak
    podman cp relay-keycloak:/opt/keycloak/data /tmp/kc-data
    chmod -R 777 /tmp/kc-data /tmp/kc-export
    podman run --rm -v /tmp/kc-data/data:/opt/keycloak/data \
      -v /tmp/kc-export:/tmp/export quay.io/keycloak/keycloak:latest \
      export --dir /tmp/export --realm relay-desk --users realm_file
    podman start relay-keycloak

`podman stop` keeps the realm — the data lives in the container's writable
layer, so only `podman rm` destroys it. If the port bind fails on restart, a
stale `containers-rootlessport` process is still holding 8081; kill it and start
again. Never commit a raw export: pass it through `keycloak-dev/sanitise.py`,
which strips the realm's private keys and refuses to write if anything
key-shaped survives. `keycloak-dev/README.md` has the details.

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

The reference deployment is a single Linux host (tested on Rocky Linux 9):
rootless Podman, three containers, and a Cloudflare Tunnel so no inbound port
needs to be open.

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

- **Backups are local only and not monitored by the application.** A failed
  run logs to the journal; alerting on it is left to the operator.
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
