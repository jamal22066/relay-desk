# Relay Desk

## Building a self-hosted support desk with FastAPI, PostgreSQL and React

**Jamal Nasir** · September 2026
`github.com/jamal22066/relay-desk`

---

## Summary

Relay Desk is a customer-facing ticketing system covering both SaaS product support and workplace IT. It was built from scratch rather than adopted, on a stack chosen for operability rather than novelty: FastAPI and PostgreSQL behind a React frontend, with LDAP authentication, SMTP notifications and a business-hours SLA engine.

This paper describes the architecture, the decisions that shaped it, and the places where the design deliberately favours auditability over convenience. It also records the mistakes made during construction, because a document that only lists successes is not much use to whoever maintains the thing next.

---

## 1. Why build rather than buy

The commercial help desk market is mature. Zendesk, Freshdesk and Jira Service Management all solve this problem competently, and for most organisations adopting one is the right answer.

Building made sense here for three reasons.

**Deployment constraints.** Systems that must run inside a compliance boundary cannot use SaaS help desks. A self-hosted application with no external dependencies beyond an SMTP relay and an LDAP directory can be deployed where a hosted product cannot.

**Data residency.** Support tickets contain incident detail, internal notes and customer contact information. Keeping that in a database you control removes an entire category of questions.

**Cost of the unusual case.** Commercial products are excellent at what they anticipate and awkward at what they do not. An SLA that pauses while waiting on the customer, respects business hours, and honours a holiday calendar is standard in enterprise tiers and absent from lower ones. Building it took an afternoon.

The counter-argument deserves stating plainly: this system has one developer, no test suite beyond integration scripts, and no operational history. A commercial product has none of those problems. The decision to build should be revisited if the system ever supports more than a handful of agents.

---

## 2. Architecture

### 2.1 Shape

Three processes, one database.

| Component | Responsibility |
|---|---|
| FastAPI application | HTTP API, authentication, business logic |
| React SPA | Agent console and customer portal |
| Mail worker | Drains the outbox queue, retries failures |
| PostgreSQL | All state, including runtime configuration |

The frontend is served by Vite in development, proxying `/api` to the backend so both surfaces share an origin. That means the session cookie works without CORS involvement, and it removes a class of configuration error that only appears in production.

### 2.2 Data model

Five tables carry everything.

**`tickets`** holds the request itself along with its computed SLA state. **`events`** is an append-only log of every comment, internal note and system action against a ticket. **`users`** covers both staff and customers, distinguished by role rather than by table. **`outbox`** is a durable email queue. **`settings`** is key-value runtime configuration.

Two choices in this model are worth defending.

*Events are one table, not three.* Comments, internal notes and system events (status changes, reassignments) share a schema and differ only by a `kind` discriminator. This keeps the ticket thread a single ordered query, and it means an audit of "everything that happened to this ticket" cannot accidentally omit a category.

*Status and priority are `TEXT` with `CHECK` constraints, not PostgreSQL enums.* Enums are the more obvious modelling choice and the wrong one. Altering an enum in PostgreSQL is awkward, cannot be done inside a transaction in older versions, and buys nothing over a check constraint at this scale.

### 2.3 Migrations

Alembic owns the schema from the first commit. The application never calls `create_all`.

This is worth stating because the temptation to skip it is strong early on — `create_all` works, it is one line, and migrations feel like ceremony when the schema changes hourly. The cost arrives the first time there is data worth keeping and a column needs to change. Adopting Alembic before that moment cost about twenty minutes. Adopting it afterwards would have meant reconstructing a baseline against a live schema.

Two things Alembic's autogenerate does not detect, both of which bit during construction:

- **Sequences.** A `Sequence` object attached to metadata is invisible to autogenerate. The ticket reference counter had to be created by explicit `op.execute` in the baseline migration.
- **`CHECK` constraint changes.** Adding an `admin` role meant widening a check constraint. Autogenerate created the new table it was asked for and silently ignored the constraint change. Without a hand-written `drop_constraint` / `create_check_constraint` pair, the first admin promotion would have failed at the database level.

A third issue is generic rather than Alembic-specific: adding a `NOT NULL` column to a table with existing rows fails unless a `server_default` is supplied. The fix is to add the column with a default and immediately drop it, so the default applies to the backfill but not to future inserts.

---

## 3. Authentication

### 3.1 Local and directory accounts side by side

Every user has an `auth_source` of either `local` or `ldap`. Local accounts hold an argon2 hash and never contact the directory. Anyone else is attempted against LDAP and provisioned on first successful bind.

The bind is the only proof of identity. The application never retrieves or compares password material from the directory — it attempts to bind as the user's DN with the supplied password, and treats success as authentication. A service account performs the initial search to resolve email to DN; it has no other privilege in the flow.

### 3.2 Role resolution

Roles come from directory group membership, with a local override that wins.

```
effective_role = role_override or role
```

`role` is refreshed from LDAP on every successful login. `role_override` is set manually in the database and survives directory changes. This means an administrator can promote someone without a directory change request, and a directory change cannot silently strip a deliberate local grant.

Group membership is read from `memberOf` when the directory provides it, falling back to an explicit group search otherwise. FreeIPA populates `memberOf` natively; the fallback exists because the 389 Directory Server instance used for testing did not, and writing for both was cheaper than debugging the fixture.

### 3.3 Sessions

Sessions are JWTs in an `httpOnly`, `SameSite=Lax` cookie. Not `localStorage` — the application holds internal notes that must not be readable by injected script. Not an `Authorization` header — the frontend is same-origin through the dev proxy, so cookies work without ceremony.

The token carries the user id, email and effective role, signed with HMAC-SHA256. Role is re-read from the database on every request rather than trusted from the token, so a demotion takes effect immediately rather than at session expiry.

### 3.4 The lockout problem

Making the directory authoritative for staff access creates a failure mode: if every administrator is LDAP-only and the directory configuration is saved incorrectly, nobody can log in to fix it.

Two mitigations. A startup check warns when no local administrator exists. And the settings page validates LDAP configuration against a real credential *before* saving, so a typo in a base DN is caught while the current configuration is still active.

---

## 4. Authorisation and the internal note boundary

The single most important security property of a support desk is that internal notes never reach the customer. It is also the easiest thing to get subtly wrong.

The first implementation was wrong in exactly this way. The portal component called a portal endpoint that filtered notes out of the response — and that worked, but only because the *component* chose the right endpoint. Nothing stopped a customer from calling the agent endpoint directly and receiving the full thread, notes included.

The fix was to move the boundary from the client to the server:

- Agent endpoints require the agent or admin role. A customer receives 403.
- Portal endpoints derive the customer's identity from the session, not from a query parameter. A customer cannot request another customer's tickets by guessing an email address.
- Note filtering happens at serialisation, not in the component.

The lesson generalises. A guard that lives in the client is not a guard; it is a convention that happens to hold until someone uses `curl`.

### 4.1 Soft deletion

Messages can be removed but not destroyed. A deleted event keeps its row and gains `deleted_at` and `deleted_by`; the API blanks the body during serialisation, so the text does not travel over the wire even though it remains in the database.

System events — status changes, reassignments — cannot be deleted at all. They are the audit trail, and an audit trail that can be edited is not one.

Customers may remove only their own messages. Agents may remove any comment or note. Both leave a visible tombstone in the thread, because a ticket history that can silently lose messages is worse than useless in a dispute.

---

## 5. Notifications

### 5.1 Queue, not inline send

Notifications are queued as rows in an `outbox` table inside the same transaction as the change that triggered them, then delivered by a separate worker process.

This costs a table and a process, and buys three things. Delivery survives an application restart. Failures retry with exponential backoff (1, 5, 20, 60 minutes; five attempts) rather than vanishing. And every send is auditable — which matters when the content being emailed is a support thread.

It also solves a safety problem, addressed next.

### 5.2 The allowlist

Notification routing is the kind of logic where a bug sends mail to strangers, and mail cannot be unsent.

`SMTP_ALLOWLIST` is a hard guard evaluated twice: once when queueing, once again by the worker before sending. A recipient outside the list is stored with status `suppressed` rather than `queued`. Suppressed rows are visible, so the routing logic can be inspected — *this event would have emailed this person for this reason* — without anything leaving the building.

Every notification path in this system was verified against suppressed rows before a single real message was sent. The seed data contains plausible external domains; without the guard, the first routing bug would have emailed people who do not exist at companies that do.

The guard is a development safety valve, not a production feature. It is disabled by setting `*` — and that should happen only once the routing is trusted.

### 5.3 Routing rules

| Event | Recipient |
|---|---|
| Agent replies publicly | Customer |
| Ticket resolved or closed | Customer |
| Ticket assigned | Receiving agent |
| Customer replies | Owning agent |
| Internal note added | Nobody |
| Status or priority changed | Nobody |

Restraint is the design principle. Emailing on every event produces a dozen messages per busy ticket, and people filter noisy senders to trash — which means the one notification that mattered is also lost.

---

## 6. Service levels

### 6.1 Stored, not computed

The SLA deadline is a column, recalculated on the events that move it: creation, priority change, and transitions in and out of *Waiting on customer*.

The alternative — computing deadlines on read — avoids a column but forces every queue query to load all open tickets into the application to filter. Storing the deadline keeps `WHERE due_at < now()` a simple indexed comparison, and it preserves history: you can see what the target *was*, rather than recomputing it against today's settings.

### 6.2 The business-hours calendar

Wall-clock SLA punishes teams for nights and weekends. A P2 filed Friday at 16:00 with an eight-hour target is four hours overdue by Monday morning, having consumed one working hour.

The calendar engine walks forward through working time, skipping non-working days, holidays, and hours outside the configured day. Elapsed time is computed the same way, so a ticket parked over a weekend accrues nothing.

One consequence is counterintuitive and worth stating before enabling it: **under business hours, a 24-hour target means three working days, not "tomorrow."** With an eight-hour working day, twenty-four hours of working time spans three of them. Teams switching from wall-clock to business-hours mode usually want to reduce their hour targets at the same time.

### 6.3 Pausing on the customer

When a ticket moves to *Waiting on customer*, the clock stops. On resume, accumulated pause time is added back and the deadline moves forward by the working time lost.

This is the difference between measuring your team's responsiveness and measuring your customers'. A ticket that sat three days waiting on a customer's reply should not appear in the past-due queue.

### 6.4 Retroactive changes

Changing SLA settings does not silently rewrite existing deadlines. An explicit action in the settings page recalculates open tickets from their original creation times, with a warning that some may become past due as a result.

Silent retroactive recalculation would mean a configuration change could move a dozen tickets into breach without anyone deciding to.

---

## 7. Runtime configuration

Configuration lives in the database, with environment variables as fallback. Database value wins when set; otherwise the environment; otherwise a declared default.

This moves LDAP and SMTP configuration out of files and into an admin interface, which is a real usability gain and a real security cost. Secrets that lived in a gitignored file with filesystem permissions now live somewhere reachable through the application.

Four mitigations:

**Encryption at rest.** Secret values are sealed with Fernet using a key derived from `SECRET_KEY`. A database dump alone does not yield the SMTP password.

**Write-only fields.** The API returns a mask for secrets, never the value. An empty submission leaves the stored secret unchanged, so saving the form without retyping a password does not clear it.

**A separate admin role.** Not every agent should be able to read the directory bind password. Admins satisfy agent checks — they can work tickets — but the reverse is not true.

**Bootstrap keys stay in the environment.** `SECRET_KEY` and `DATABASE_URL` are never database-configurable. The application cannot read the database without one and cannot validate a session without the other.

---

## 8. What is not built

Recording gaps honestly is more useful than an implied claim of completeness.

- **No test suite.** Verification is by integration shell scripts against a live server. They exercise the important paths — auth guards, note containment, SLA arithmetic, notification routing — but they are not unit tests and they do not run in CI.
- **No password reset.** A local user who forgets their password needs an administrator and a SQL statement.
- **No supervision for the worker.** The mail worker runs in a foreground process. A systemd unit is roughly fifteen lines and has not been written.
- **No rate limiting.** The login endpoint will accept unlimited attempts.
- **No attachments.** Support tickets frequently need a screenshot or a log file.
- **No search beyond `ILIKE`.** Adequate for hundreds of tickets, inadequate for tens of thousands.

---

## 9. What generalised

Five things from this build apply beyond it.

**Adopt migrations before you need them.** The cost is twenty minutes early and a reconstructed baseline late.

**Assert on your own patches.** Every scripted edit during construction asserted that its anchor matched exactly once. This caught a duplicated block of endpoints that had been silently registered twice — FastAPI used the first and ignored the second, so nothing appeared broken. The assertion found what testing did not.

**Put the guard on the server.** Client-side filtering is a convention, not a control.

**Build the safety valve before the feature.** The recipient allowlist was written before the first notification. It made it possible to verify every routing path against a database table rather than an inbox.

**Verify state changes in the database, not the UI.** Several times during construction, the interface looked correct while the underlying state was wrong — and once the reverse, where the calculation was right and the expectation written into the test was wrong. Querying the table settles it.

---

## Appendix: stack

| Layer | Choice |
|---|---|
| API | FastAPI 0.115, Pydantic 2 |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic 1.14 |
| Database | PostgreSQL 14 |
| Passwords | argon2-cffi |
| Sessions | PyJWT, HS256 |
| Directory | ldap3, FreeIPA / 389 DS |
| Secrets at rest | cryptography (Fernet) |
| Frontend | React 18, Vite |
| Typography | IBM Plex Sans / Mono |
