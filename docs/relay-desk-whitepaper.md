# Relay Desk

## Building a self-hosted support desk with FastAPI, PostgreSQL and React

**Jamal Nasir** · September 2026
`github.com/jamal22066/relay-desk`

---

## Summary

Relay Desk is a customer-facing ticketing system covering both SaaS product
support and workplace IT. It was built from scratch rather than adopted, on a
stack chosen for operability rather than novelty: FastAPI and PostgreSQL behind
a React frontend, with LDAP authentication, email notifications, file
attachments, a business-hours SLA engine and scheduled ticket creation.

This paper describes the architecture, the decisions that shaped it, and the
places where the design deliberately favours auditability over convenience. It
also records the mistakes made during construction, because a document that only
lists successes is not much use to whoever maintains the thing next.

---

## 1. Why build rather than buy

The commercial help desk market is mature. Zendesk, Freshdesk and Jira Service
Management all solve this problem competently, and for most organisations
adopting one is the right answer.

Building made sense here for three reasons.

**Deployment constraints.** Systems that must run inside a compliance boundary
cannot use SaaS help desks. A self-hosted application with no external
dependencies beyond an SMTP relay and an LDAP directory can be deployed where a
hosted product cannot.

**Data residency.** Support tickets contain incident detail, internal notes,
customer contact information and now uploaded files. Keeping that in a database
you control removes an entire category of questions.

**Cost of the unusual case.** Commercial products are excellent at what they
anticipate and awkward at what they do not. An SLA that pauses while waiting on
the customer, respects business hours, and honours a holiday calendar is
standard in enterprise tiers and absent from lower ones. Building it took an
afternoon.

The counter-argument deserves stating plainly: this system has one developer, no
test suite beyond integration scripts, and no operational history. A commercial
product has none of those problems. The decision to build should be revisited if
this ever supports more than a handful of agents.

---

## 2. Architecture

### 2.1 Shape

Three containers, one database, two timers.

| Component | Responsibility |
|---|---|
| FastAPI application | HTTP API, authentication, business logic, static frontend |
| Mail worker | Drains the outbox queue continuously, retries failures |
| PostgreSQL | All state, including runtime configuration |
| Schedule timer | Fires due schedules hourly |
| Backup timer | Dumps database and uploads every six hours |

In development the frontend runs under Vite, proxying `/api` to the backend so
both share an origin. In production it is a static build served by FastAPI
itself — same-origin by construction, with no dev server in the deployment.

### 2.2 Data model

Seven tables carry everything.

**`tickets`** holds the request and its computed SLA state. **`events`** is an
append-only log of every comment, internal note and system action.
**`attachments`** hang off events. **`users`** covers staff and customers,
distinguished by role rather than by table. **`schedules`** are ticket templates
that materialise on a date or a cadence. **`outbox`** is a durable email queue.
**`settings`** is key-value runtime configuration.

Four choices in this model are worth defending.

*Events are one table, not three.* Comments, internal notes and system events
share a schema and differ by a `kind` discriminator. This keeps a ticket thread
a single ordered query, and an audit of "everything that happened" cannot
accidentally omit a category.

*Attachments hang off events, not tickets.* This was not the first design. The
obvious model attaches files to tickets, but it means a file on an internal note
needs a parallel visibility rule — and parallel rules diverge. Hanging
attachments off events means a file inherits its message's visibility for free:
the same check that hides an internal note hides its attachment.

*The original description is a real event.* Initially the ticket's `body` column
was rendered as a synthetic first message that the frontend fabricated. That
worked until attachments needed something to attach to. Making it a real
`comment` event with an `is_original` flag removed the special case entirely and
made the thread uniform. The migration backfilled one event per existing ticket.

*Status and priority are `TEXT` with `CHECK` constraints, not PostgreSQL enums.*
Enums are the more obvious choice and the wrong one: altering an enum is
awkward, cannot be done inside a transaction in older versions, and buys nothing
over a check constraint at this scale.

### 2.3 Migrations

Alembic owns the schema from the first commit. The application never calls
`create_all`.

The temptation to skip this is strong early on — `create_all` works, it is one
line, and migrations feel like ceremony when the schema changes hourly. The cost
arrives the first time there is data worth keeping and a column needs to change.
Adopting Alembic before that moment cost about twenty minutes. Adopting it
afterwards would have meant reconstructing a baseline against a live schema.

Four things autogenerate gets wrong, all of which bit during construction:

- **Sequences are invisible.** The ticket reference counter had to be created by
  explicit `op.execute` in the baseline migration.
- **`CHECK` constraint changes are not detected.** Adding an `admin` role meant
  widening a constraint; autogenerate created the table it was asked for and
  silently ignored the constraint. Without a hand-written
  `drop_constraint`/`create_check_constraint` pair, the first admin promotion
  would have failed at the database level.
- **`NOT NULL` columns fail on existing rows** without a `server_default`. Add
  the column with one, then drop it so future inserts use the model default.
- **Data migrations must follow the columns they touch.** A backfill inserted
  immediately after the first `add_column` failed because a second column in the
  same migration did not yet exist.

---

## 3. Authentication

### 3.1 Local and directory accounts side by side

Every user has an `auth_source` of `local` or `ldap`. Local accounts hold an
argon2 hash and never contact the directory. Anyone else is attempted against
LDAP and provisioned on first successful bind.

The bind is the only proof of identity. The application never retrieves or
compares password material — it attempts to bind as the user's DN with the
supplied password and treats success as authentication. A service account
performs the initial email-to-DN search and has no other privilege in the flow.

### 3.2 Role resolution

Roles come from directory group membership, with a local override that wins:

```
effective_role = role_override or role
```

`role` is refreshed from LDAP on every successful login. `role_override` is set
by an administrator and survives directory changes. An administrator can promote
someone without a directory change request, and a directory change cannot
silently strip a deliberate local grant.

Group membership reads `memberOf` when the directory provides it, falling back
to an explicit group search. FreeIPA populates `memberOf` natively; the fallback
exists because the 389 Directory Server instance used for testing did not, and
writing for both was cheaper than debugging the fixture.

### 3.3 Email verification

Local accounts must confirm their address before signing in. The token is
signed, valid 48 hours, and scoped to the user id *and* their current address —
so it stops working if the address changes — and carries a `purpose` claim so a
session token cannot be substituted for it.

This was not an aesthetic addition. Once the system sends notifications,
unverified registration makes it able to mail any address an anonymous party
types, carrying the sending domain's reputation. Verification came before the
recipient allowlist could be widened, deliberately: an open
registration endpoint plus unrestricted outbound mail is the combination worth
avoiding.

### 3.4 The lockout problem

Making the directory authoritative for staff access creates a failure mode: if
every administrator is LDAP-only and the directory configuration is saved
incorrectly, nobody can log in to fix it.

Three mitigations. A startup check warns when no local administrator exists. The
settings page validates LDAP configuration against a real credential *before*
saving. And the account management interface refuses to demote, deactivate or
delete the last active administrator, or the acting administrator's own account.

---

## 4. Authorisation and the internal note boundary

The single most important security property of a support desk is that internal
notes never reach the customer. It is also the easiest thing to get subtly
wrong.

The first implementation was wrong in exactly this way. The portal component
called a portal endpoint that filtered notes out of the response — which worked,
but only because the *component* chose the right endpoint. Nothing stopped a
customer from calling the agent endpoint directly and receiving the full thread.

The fix moved the boundary from the client to the server:

- Agent endpoints require the agent or admin role. A customer receives 403.
- Portal endpoints derive identity from the session, not a query parameter. A
  customer cannot request another's tickets by guessing an email address.
- Note filtering happens at serialisation, not in the component.

The lesson generalises. A guard that lives in the client is not a guard; it is a
convention that happens to hold until someone uses `curl`.

### 4.1 Soft deletion

Messages can be removed but not destroyed. A deleted event keeps its row and
gains `deleted_at` and `deleted_by`; the API blanks the body during
serialisation, so the text does not travel over the wire even though it remains
in the database.

Two categories cannot be deleted at all. **System events** — status changes,
reassignments, schedule provenance — are the audit trail, and an audit trail
that can be edited is not one. **The original description** is protected because
a ticket whose problem statement can vanish is more confusing than one that is
simply closed.

Customers may remove only their own messages; agents may remove any comment or
note. Both leave a visible tombstone, because a ticket history that can silently
lose messages is worse than useless in a dispute.

---

## 5. Attachments

Images, PDFs and plain text, up to 10 MB and five files at a time. Three rules
close specific holes.

**Type is determined by content, not by claim.** `libmagic` sniffs the actual
bytes; the extension and the client's `Content-Type` are ignored for this
decision. An allowlist of seven MIME types means anything unrecognised is
refused rather than something unsafe having to be anticipated. SVG is
deliberately excluded — it is an image format that executes script.

One subtlety: libmagic falls back to `text/plain` for content it cannot
identify, which would let arbitrary binary through as text. A null-byte check
closes that.

**Stored filenames are generated.** Sixteen random bytes plus a validated
extension. The client's filename is kept for display and never touches the
filesystem, making path traversal structurally impossible rather than something
sanitised.

**Downloads cannot execute.** Served as `application/octet-stream` with
`Content-Disposition: attachment`, `nosniff`, and a `default-src 'none';
sandbox` policy. An uploaded document cannot run against the viewer's session.

### 5.1 Validate before you commit

The first implementation posted the message, then uploaded the file, then
attempted to clean up if the upload failed. When a file was rejected this left
orphaned "(attachment)" messages in threads, because the cleanup call was
swallowed by a bare `catch`.

The fix was a dry-run validation endpoint that checks files without storing
anything. The client validates first and only posts if the files pass. There is
nothing to clean up because nothing was created.

This is a general shape worth recognising: when an operation spans two resources
and the second can fail, validating first is usually simpler than compensating
afterwards.

---

## 6. Service levels

### 6.1 Stored, not computed

The SLA deadline is a column, recalculated on the events that move it: creation,
priority change, and transitions in and out of *Waiting on customer*.

Computing on read avoids a column but forces every queue query to load all open
tickets into the application to filter. Storing the deadline keeps
`WHERE due_at < now()` a simple indexed comparison, and it preserves history —
you can see what the target *was*, rather than recomputing it against today's
settings.

### 6.2 The business-hours calendar

Wall-clock SLA punishes teams for nights and weekends. A P2 filed Friday at
16:00 with an eight-hour target is four hours overdue by Monday morning, having
consumed one working hour.

The calendar walks forward through working time, skipping non-working days,
holidays and hours outside the configured day. Elapsed time is computed the same
way, so a ticket parked over a weekend accrues nothing.

One consequence is counterintuitive and worth stating before enabling it:
**under business hours, a 24-hour target means three working days, not
"tomorrow."** With an eight-hour day, twenty-four hours of working time spans
three of them. Teams switching from wall-clock usually want to reduce their hour
targets at the same time.

### 6.3 Pausing on the customer

When a ticket moves to *Waiting on customer*, the clock stops. On resume,
accumulated pause time is added back and the deadline moves forward by the
working time lost. This is the difference between measuring your team's
responsiveness and measuring your customers'.

### 6.4 Retroactive changes

Changing SLA settings does not silently rewrite existing deadlines. An explicit
action recalculates open tickets from their original creation times, with a
warning that some may become past due. Silent recalculation would mean a
configuration change could move a dozen tickets into breach without anyone
deciding to.

---

## 7. Scheduled tickets

A ticket template that materialises on a date or a cadence. One-off schedules
fire once and complete; recurring ones advance to their next occurrence.

**The lead-time case is expressed by the date, not by an offset field.** For
"open a ticket 30 days before the maintenance window", the first run is set to
the computed date. Storing the target date and an offset separately would mean
two sources of truth for one moment.

**Catch-up is bounded.** A schedule left unrun advances to the next *future*
occurrence rather than firing once per missed interval. A week of downtime
produces one ticket, not seven — which for a maintenance reminder is always the
intent.

**The audit trail is the point.** Each generated ticket carries a system event
naming the schedule and its id. System events cannot be deleted, so the record
that a ticket was generated rather than filed by a person survives. That is what
makes it usable as compliance evidence rather than decoration.

**Failures are loud.** A schedule that fails stops firing, records the error,
and emails the administrators. A compliance reminder that silently stops is the
worst outcome, because it is discovered during an audit.

**Staff only.** Allowing customers to create schedules was considered and
rejected. A recurring schedule is an unbounded ticket generator and a mail
amplifier; on an instance with open registration that is a denial-of-service
primitive with a user interface.

One honest approximation: recurrence treats a month as 30 days. Calendar-correct
month arithmetic needs a policy for the 31st in February, and "about a month
later" is the honest intent for a maintenance reminder.

---

## 8. Notifications

### 8.1 Queue, not inline send

Notifications are queued inside the same transaction as the change that
triggered them, then delivered by a separate worker.

This costs a table and a process, and buys three things. Delivery survives an
application restart. Failures retry with exponential backoff rather than
vanishing. And every send is auditable — which matters when the content is a
support thread.

### 8.2 The allowlist

Notification routing is the kind of logic where a bug sends mail to strangers,
and mail cannot be unsent.

`SMTP_ALLOWLIST` is a hard guard evaluated twice: when queueing, and again by
the worker before sending. A recipient outside it is stored as `suppressed`
rather than `queued`. Suppressed rows are visible, so routing can be inspected —
*this event would have emailed this person for this reason* — without anything
leaving the building.

Every notification path was verified against suppressed rows before a single
real message was sent. The seed data contains plausible external domains;
without the guard, the first routing bug would have emailed people who do not
exist at companies that do.

Verification emails bypass it deliberately, since the address was just typed by
whoever is registering and the content is fixed. That exception had to be added
in two places — queueing and the worker's re-check — which is worth noting as
the cost of defence in depth.

### 8.3 Restraint

Emailing on every event produces a dozen messages per busy ticket, and people
filter noisy senders to trash — which means the one notification that mattered
is also lost. Every path is individually toggleable, and status and priority
changes notify nobody.

---

## 9. Runtime configuration

Configuration lives in the database with environment variables as fallback:
database value wins when set, otherwise the environment, otherwise a declared
default.

This moves LDAP and SMTP configuration into an admin interface, which is a real
usability gain and a real security cost. Secrets that lived in a gitignored file
with filesystem permissions now live somewhere reachable through the
application.

Four mitigations. Secret values are sealed with Fernet using a key derived from
`SECRET_KEY`. The API returns a mask, never the value, and an empty submission
leaves the stored secret unchanged. A separate admin role means not every agent
can read the directory bind password. And three bootstrap keys —
`SECRET_KEY`, `DATABASE_URL`, `UPLOAD_DIR` — are never database-configurable,
because the application cannot start without them.

Rotating `SECRET_KEY` invalidates every session and makes sealed secrets
unreadable. This was discovered when a dependency upgrade surfaced that the key
was 27 bytes, below the 32-byte minimum for HMAC-SHA256. Rotating it cost
nothing because no secrets had yet been stored through the settings page. Later
it would have cost re-entering every credential.

---

## 10. Deployment

The reference deployment is a single Linux host (built and tested on Rocky
Linux 9), deliberately separate from any development machine.

**Ingress is a Cloudflare Tunnel.** No inbound port needs to be open — the
tunnel establishes an *outbound* connection to Cloudflare's edge, so the host
firewall can refuse everything but administrative access. TLS terminates at
Cloudflare and the origin address need not be exposed.

**Containers are rootless Podman** under a dedicated service user with lingering
enabled, so the stack survives reboot without a login session. The application
publishes only to loopback.

Two things that confuse everyone the first time: rootless containers are
invisible to root, and `podman-compose` needs `XDG_RUNTIME_DIR` set when entered
via `su` or it looks in the wrong state directory and reports containers that do
not exist.

**Backups are local only.** Every six hours, a compressed `pg_dump` and a tar of
the uploads volume, kept 30 days. They protect against application mistakes, a
bad migration or accidental deletion — not against losing the host. The script
refuses to report success on a dump under 1 KB, because a partial `pg_dump`
still produces a valid-looking gzip. The backup was verified by restoring it
into a throwaway database and comparing row counts, because an untested backup
is a guess.

---

## 11. What is not built

Recording gaps honestly is more useful than an implied claim of completeness.

- **No test suite.** Verification is by integration shell scripts against a live
  server. They exercise the important paths but are not unit tests and do not
  run in CI.
- **No password reset.** A local user who forgets their password needs an
  administrator and a SQL statement.
- **No malware scanning on uploads.** Type is validated, content is not.
- **Off-site backup, monitoring and alerting are left to the operator.** The
  backup script writes locally, and nothing in the application reports a failed
  run.
- **Rate limiting is in-memory and per-process.** A fleet would need Redis.
- **Search is `ILIKE` only.** Adequate for hundreds of tickets, not tens of
  thousands.
- **Polling, not events.** Notifications deliver within 30 seconds and schedules
  fire hourly.

---

## 12. What generalised

Seven things from this build apply beyond it.

**Adopt migrations before you need them.** Twenty minutes early, a reconstructed
baseline late.

**Assert on your own patches.** Every scripted edit asserted its anchor matched
exactly once. This caught a duplicated block of endpoints that had been silently
registered twice — FastAPI used the first and ignored the second, so nothing
appeared broken. The assertion found what testing did not.

**Put the guard on the server.** Client-side filtering is a convention, not a
control.

**Build the safety valve before the feature.** The recipient allowlist was
written before the first notification, making it possible to verify every
routing path against a database table rather than an inbox.

**Validate before you commit.** When an operation spans two resources and the
second can fail, checking first beats compensating afterwards.

**Verify state changes in the database, not the UI.** Several times the
interface looked correct while the underlying state was wrong — and once the
reverse, where the calculation was right and the expectation written into the
test was wrong. Querying the table settles it.

**A deferred security assessment expires when the code changes.** The first
security review deferred several Starlette advisories with a reasoned argument
that none were reachable. That was correct when written. Then attachments
shipped, `FileResponse` entered the codebase, and one advisory became a 280×
CPU amplification exploitable by any registered user. The fix was five lines.
Noticing was the hard part.

---

## Appendix: stack

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
