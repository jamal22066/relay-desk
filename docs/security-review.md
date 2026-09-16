# Security review

**Relay Desk** · Second review, September 2026
Reviewer: Jamal Nasir · Scope: full application, the reference container
deployment, and the attachment, scheduling, backup and single sign-on
subsystems added since the first review, plus a penetration test of the running
instance.
Self-assessed. No independent review has been performed.

---

## Summary

The first review covered authentication, authorisation and transport. This one
re-tests those and adds the surface introduced since: file uploads, scheduled
ticket creation, backups, and OIDC single sign-on.

Seven classes of issue have been found and fixed across both reviews. Two
findings in this round were introduced by the project's own dependency
management rather than by feature work, which is worth noting: the most recent
vulnerability was self-inflicted by a version pin.

The methodological finding from the first review holds and strengthened.
Automated scanning again found zero application-logic issues. Both real findings
this round came from forming a hypothesis about a specific code path and
measuring it — one hypothesis was confirmed, one was wrong, and the measurement
is what distinguished them.

A penetration test of the running instance followed. The authorisation boundary
held under direct attack, including the file-on-an-internal-note case it exists
to defend. It surfaced two Low findings — account enumeration via the
registration endpoint, and a per-account lockout that punished the victim rather
than the attacker — both since fixed and re-verified against the live server.

---

## Tooling

| Tool | Version | Scope |
|---|---|---|
| `npm audit` | bundled | JavaScript dependency CVEs |
| `pip-audit` | 2.10.1 | Python dependency CVEs |
| Semgrep OSS | 1.176.1 | Static analysis, 499 rules |
| ZAP | 2.17.0 | Dynamic scanning, authenticated and unauthenticated |

Reproducible via `./scripts/audit.sh`. Semgrep and pip-audit install through
`pipx`, outside the application virtualenv — see §9.1.

---

## Findings this round

### 1. Quadratic Range header parsing on attachment downloads (High — fixed)

**Found:** by inspecting which newly-added code paths touched dependencies with
open advisories, then measuring.

`PYSEC-2026-1942` describes quadratic-time Range header parsing in Starlette's
`FileResponse`. The attachment download endpoint returns a `FileResponse`, so
the advisory became reachable the moment attachments shipped. It did not apply
before.

Measured against a 70-byte attachment:

| Range header size | Response time | Ratio |
|---|---|---|
| no Range header | 0.016 s | baseline |
| 5,000 characters | 0.106 s | — |
| 10,000 characters | 0.391 s | 3.7× |
| 20,000 characters | 1.106 s | 2.8× |
| 40,000 characters | 4.468 s | 4.0× |

Doubling the header roughly quadruples the time, confirming quadratic
behaviour. A single request consumed 4.5 seconds of CPU against a 16 ms
baseline — 280× amplification — and blocked the event loop throughout. A handful
of concurrent requests would take the service down.

Any authenticated account can reach the endpoint, and registration is open, so
the barrier is one email verification.

**Fixed** by stripping the Range header in the endpoint before `FileResponse`
sees it. Attachments are small and partial downloads serve no purpose, so
discarding the header costs nothing:

```python
request.scope["headers"] = [
    (k, v) for k, v in request.scope["headers"] if k.lower() != b"range"
]
```

**After the fix:** 40,000 characters returns in 0.028 s against a 0.013 s
baseline, and the file still downloads at full length. A 160× improvement on the
attack case.

This matters beyond the specific bug. The first review deferred the Starlette
advisories on the grounds that none were reachable. That assessment was correct
when written and became wrong when a feature shipped. **A deferred advisory is
a claim about current code, not a permanent exemption.**

### 2. Vulnerable multipart parser, self-inflicted (Medium — fixed)

`python-multipart` 0.0.20 carries six advisories. Two are reachable here:

- `PYSEC-2026-3039` — unbounded multipart part headers, CPU exhaustion.
  Directly on the upload path, since Starlette drives `MultipartParser`.
- `PYSEC-2026-3036` / `3037` — `QuerystringParser` issues via `request.form()`.
  Lower relevance, as this application uses JSON bodies throughout, but the
  parser ships regardless.

`PYSEC-2026-1852` and `PYSEC-2026-3040` do not apply: they require
`UPLOAD_KEEP_FILENAME` or a direct `parse_form()` call, neither of which is
used.

**The cause is worth recording.** Semgrep's installation had pulled
`python-multipart` 0.0.32 into the environment. When attachments were added, a
`requirements.txt` pin of `==0.0.20` silently *downgraded* it. The vulnerability
was introduced by the project's own dependency management, not inherited.

**Fixed** by pinning 0.0.32. Uploads verified working afterwards, since this is
the parser they depend on.

### 3. Upload memory exhaustion (hypothesis — disproved)

The upload endpoint calls `await f.read()` before checking file size, which
looked like it would buffer an arbitrarily large upload into memory on a small
host.

Measured by sampling the uvicorn process's RSS every 200 ms while posting a
300 MB file:

- RSS before: 30,636 kB
- Peak RSS during: 30,636 kB
- Result: 422, file rejected

No change. Starlette spools large uploads to a temporary file on disk, so
`f.read()` reads from disk rather than accumulating in memory.

**Not a memory exhaustion vector.** It remains a *disk* consumption vector —
an authenticated client can force temporary files to be written before the size
check rejects them — which is bounded by the host's disk and by the rate limit
on authentication, but is not otherwise capped. Recorded as an open item rather
than a finding.

Worth stating plainly: the initial measurement attempt was wrong. Running
`/usr/bin/time -v` on `curl` reported curl's memory, not the server's. The
finding only resolved once the right process was measured.

---

## Carried forward from the first review

### 4. Authorisation boundary (Critical — fixed, re-verified)

The agent API originally returned unfiltered ticket threads with no
authentication, so internal notes were readable by anyone who could reach the
API. Note filtering lived in the React component, which is a convention rather
than a control.

Fixed by moving the boundary to the server: agent endpoints require the agent or
admin role, portal endpoints derive identity from the session rather than a
query parameter, and note filtering happens during serialisation.

**Extended for attachments.** Attachments hang off events rather than tickets,
so a file on an internal note inherits that note's visibility automatically
rather than needing a parallel rule. Verified: a customer requesting an
attachment on an internal note receives 404, not 403 — the resource does not
acknowledge its own existence.

`scripts/guard_test.sh` re-run this round: all assertions pass.

### 5. Unlimited authentication attempts (High — fixed)

Two independent budgets: 30 per 5 minutes per source IP, 5 per 15 minutes per
target account. The split prevents an attacker locking out everyone behind a
shared NAT while still stopping a targeted brute force. Registration is rate
limited per IP, added because the signup notification made it a mail amplifier.

### 6. Missing HTTP security headers (Medium — fixed)

CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` and
`Permissions-Policy` are set by middleware on every response including errors.
`style-src 'unsafe-inline'` remains, because components use inline styles for
priority colours — a real weakening, not a false positive.

### 7. Unverified email as an abuse vector (High — fixed)

Local accounts must confirm their address before signing in. Tokens are signed,
48-hour, scoped to the user id *and* their current address, and carry a
`purpose` claim so a session token cannot be substituted. Only with verification
in place is it safe to widen the recipient allowlist.

### 7a. The recipient allowlist ignored the administrator (Medium — fixed)

The allowlist is the guard that keeps a development instance from mailing real
addresses, and the settings page presents it as editable at runtime. It was
not. `settings_store` writes the database row but does not update
`app.config.settings`, and the whole mail path — `mailer.allowed`, `notify`, the
mail worker, the outbox view — read that environment object, loaded once at
import. Tightening the allowlist in the admin interface appeared to save and
changed nothing, and the Mail queue page kept displaying the old sending address
while delivery used it too.

Demonstrated before the fix: with a database override setting the allowlist to
`@nope.test`, `allowed("x@nope.test")` still returned `False`. The gap is
silent, which is what makes it worth recording — an operator narrowing the
allowlist before a test run would have believed a guard that was not there, and
an operator widening it would have wondered why nothing sent.

Mail settings now resolve through `mailer.config(db)`, which is `settings_store`
resolution — database value, then `.env`, then default — so the value shown, the
value saved and the value used are the same. Verified after the fix: the same
override makes `allowed` return `True`, and the built message carries the
overridden From address and Message-ID domain. `smtp_timeout` remains
environment-only, since it is not a settings-store key.

---

## New subsystems assessed

### 8.1 Attachments

**Type validation is by content, not by claim.** `python-magic` sniffs the
actual bytes; the extension and the client's `Content-Type` are both ignored for
this decision. An allowlist of seven MIME types, so anything unrecognised is
refused rather than something unsafe having to be anticipated.

Tested against disguised content:

| Uploaded as | Actual content | Result |
|---|---|---|
| `shot.png` | real PNG | accepted |
| `doc.pdf` | real PDF | accepted |
| `app.log` | plain text | accepted |
| `evil.png` | HTML with `<script>` | **refused** — detected as text/html |
| `x.svg` | SVG with `<script>` | **refused** — SVG not in the allowlist |
| `payload.txt` | binary with null bytes | **refused** |

SVG is deliberately excluded. It is an image format that executes script, and
accepting it would undermine the rest of the controls.

The null-byte check exists because libmagic falls back to `text/plain` for
content it cannot identify, which would otherwise let arbitrary binary through
as text.

**Storage is under generated names.** A 16-byte random hex name plus a
validated extension; the client's filename is stored for display only and never
touches the filesystem. Path traversal is structurally impossible rather than
something sanitised, and `path_for()` additionally refuses any resolved path
outside the upload root.

**Downloads cannot execute.** Served as `application/octet-stream` with
`Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, and
`Content-Security-Policy: default-src 'none'; sandbox`. Verified on the wire.

**Validation happens before the message is posted.** An earlier implementation
posted the reply, then uploaded, then attempted to clean up on failure — leaving
orphaned "(attachment)" messages when a file was rejected, because the cleanup
call was swallowed by a bare `catch`. Replaced with a dry-run validation
endpoint that checks files without storing anything. Confirmed: a rejected
upload now creates no event at all.

### 8.2 Scheduled tickets

**Staff only.** Allowing customers to create schedules was considered and
rejected: a recurring schedule is an unbounded ticket generator and a mail
amplifier, and on an instance with open registration that is a denial-of-service
primitive with a user interface. Verified: a customer requesting `/api/schedules`
receives 403.

**The audit trail is immutable.** Each generated ticket carries a `system` event
naming the schedule and its id. System events cannot be deleted — the same rule
that protects status changes — so the record that a ticket was generated rather
than filed by a person cannot be removed after the fact. This is the property
that makes it usable as compliance evidence rather than decoration.

**Failures are loud.** A schedule that fails stops firing, records the error,
and emails the administrators. A compliance reminder that silently stops is the
worst outcome, because it is discovered during an audit. Verified end to end: a
schedule referencing a deleted account failed, recorded `ValueError: no active
account for …`, and queued a notification per admin.

**Catch-up is bounded.** A schedule left unrun advances to the next *future*
occurrence rather than firing once per missed interval, so a week of downtime
produces one ticket rather than seven.

### 8.3 Backups

`scripts/backup.sh` writes a compressed `pg_dump` and a tar of the uploads
volume every six hours, keeping 30 days of dumps and the eight most recent
upload archives.

**Verified by restoring, not by inspection.** The dump was loaded into a
throwaway database and row counts compared against the source database, table
by table. An untested backup is a guess.

The script refuses to report success on a dump under 1 KB, because a `pg_dump`
that fails partway still produces a valid-looking gzip.

**Backups are local only.** They protect against application mistakes, a bad
migration or accidental deletion — not against losing the host. They also
contain argon2 password hashes and Fernet-sealed credentials, so their file
permissions matter. The script does not restrict them beyond the permissions
of the directory it writes to; operators should.

### 8.4 Single sign-on (OIDC)

Staff and customers can authenticate against an external provider. The
application is a confidential client using the authorization code flow, and the
local Keycloak realm in `keycloak-dev/` is the test rig.

**ID token verification is the whole of the security.** Everything the
application believes about the caller — subject, address, group membership —
comes from the ID token, so accepting an unverified one would let anyone assert
any identity. The token is verified against the provider's published JWKS, with
audience and issuer pinned. Tested against a genuine Keycloak token:

| Attempt | Result |
|---|---|
| Genuine token | accepted |
| Payload edited, original signature kept | `InvalidSignatureError` |
| Re-signed HS256 with an attacker key | `PyJWKClientError` — no matching JWK |
| `alg: none` | `PyJWKClientError` |
| Correct signature, wrong audience | `InvalidAudienceError` |
| Correct signature, wrong issuer | `InvalidIssuerError` |

The algorithm allowlist is `RS256`/`ES256`, so the classic `alg: none` and
HMAC-confusion substitutions fail before a key is even selected.

**The callback is bound to a request this application started.** `state` is a
short-lived JWT signed with `SECRET_KEY`, carrying a purpose and a ten-minute
expiry, rather than a server-side session entry. Verified: a state signed with a
different key is rejected, and so is one carrying a valid signature but a
different purpose, which stops a token minted for another flow being replayed
here.

**Signing in adopts a matching local account — a deliberate trade with a sharp
edge.** When the address in a verified ID token matches an existing `local`
account, that account is taken over rather than duplicated: `auth_source`
becomes `oidc` and `password_hash` is cleared. Demonstrated against a local
account holding its own password, where an SSO sign-in for the same address
produced the same row id, a null password hash, and an overwritten display name.
The account keeps its tickets, so whoever completes that sign-in inherits the
history too.

This is right when the provider is authoritative for the addresses it asserts,
which is the ordinary case: a company IdP for a company domain, where the person
behind `someone@company.example` is the same person either way. **It is wrong
where the provider federates identities it does not own** — a Keycloak brokering
to social logins, a multi-tenant provider, or any configuration where a user can
set their own address. There, controlling an address at the IdP is enough to
take over the matching local account, including an administrator's. An operator
in that position should not enable OIDC without first confirming the provider
will only ever assert addresses it controls.

**Address verification is trusted, not proven.** The flow rejects a token whose
`email_verified` claim is explicitly `false`, but a provider that omits the
claim entirely passes. That is a deliberate accommodation — not every provider
sends it — and it means the adoption behaviour above rests on the provider's
diligence rather than on anything checked here.

**Roles come from group claims, and a local override still wins.** The group
claim is mapped to admin or agent by configured group names; anything else is a
customer. `role_override` is applied after, so an administrator can promote or
demote someone regardless of the directory. Verified: an account the IdP reports
with no groups, carrying `role_override='admin'`, signs in and resolves as
admin, while the IdP-derived `role` column still reads `customer`. The
consequence worth stating is that the IdP cannot demote someone who holds an
override — removing a user from the admin group in the directory does not
revoke their access here.

**Logout does not end the provider's session unless asked.** Signing out clears
the local cookie only; ending the provider session is a separate, explicit
action that redirects to `end_session_endpoint` with the stored ID token as
`id_token_hint`. Verified both directions: after a plain sign-out, returning
through SSO re-authenticates silently, and after *Sign out everywhere* the
provider prompts for a password again.

**The stored ID token is credential material at rest.** It is kept between
sign-in and sign-out solely to hint that logout, and cleared on any logout. It
is stored in plaintext, unlike settings secrets, which are Fernet-sealed — so it
appears unencrypted in `pg_dump` output and therefore in backups. It is an ID
token rather than an access or refresh token, and it is short-lived, so what it
grants an attacker who already has the database is limited; it is recorded here
because "we store a token from your IdP in the clear" should be a stated
property, not a discovered one.

**Not implemented: PKCE and `nonce`.** Neither is required for a confidential
client performing a server-side code exchange over TLS with client
authentication, which is the deployed configuration. Both are defence in depth
that a public client would need, and their absence is a reason this flow should
not be repurposed for one.

---

## Penetration test of the running instance

A grey-box pass against a live instance, source-informed, across three roles
(customer, agent, admin) plus anonymous. The goal was to break the invariants
the earlier sections assert rather than to re-read the code. What held is worth
recording as plainly as what did not.

**The authorisation boundary held under direct attack.** The sharpest test:
an internal note *carrying a file attachment* was planted on a customer's own
ticket, then reached for as that customer. Ticket-ownership scoping passes —
it is her ticket — so only the note's kind stands between her and the file. The
note never appeared in her portal view, and a direct request for the attachment
by id returned 404 to the ticket's owner and to other customers, 200 only to
staff, with no bytes served. This is the file-on-an-internal-note case the
architecture is built to handle, confirmed end to end rather than assumed.

**Also confirmed, each by attempting the bypass:** cross-customer IDOR on
tickets, portal replies and attachments (403/404); SQL injection in search
(inert — the query is parameterised through SQLAlchemy); session-cookie forgery
via `alg:none`, payload tampering with the signature kept, and HS256 re-signing
under guessed keys (all 401, and the role is re-derived from the database at
authorisation time regardless of the token's claim); `role: admin` supplied at
registration (ignored — the account is created a customer); the agent/admin
split, tested with a genuine non-admin agent session against `/api/admin/*`
(403); attachment content-type spoofing, HTML and SVG rejected by byte-sniffing;
the `Range` header parser (a 10,000-range header served in 11 ms, stripped, no
quadratic blow-up); and the OIDC `state` and `next` handling (forged state
rejected, `next=//evil.com` reset to `/`).

### PT-1. Account enumeration via registration (Low — fixed)

`POST /auth/register` answered `409 "An account with that address already
exists"` for a registered address and `201` for a new one, so anyone could test
whether an address had an account. Login was already careful to give one generic
message for both the unknown-account and wrong-password cases; registration
undid that.

Registration now answers identically either way — the same `201` and the same
response shape, built from the submitted values — and creates nothing on a
collision. The real owner is told out of band instead: a one-off notice email
("you already have an account") goes to the registered address, which alerts
them without disclosing anything to whoever made the request. The password is
hashed before the existence check on both paths, so argon2's cost cannot be used
as a timing oracle for the same fact the status code used to leak.

### PT-2. Account-lockout denial of service (Low — fixed)

Login recorded a per-account rate-limit hit on *every* attempt, before the
password was checked. Five wrong guesses against a known address therefore
locked out that address's real owner: their correct password returned `429`
along with everyone else's. Confirmed against a seeded account before the fix.

The per-account budget now counts *failed* attempts only. The pre-authentication
gate enforces the per-source-IP budget alone; a wrong credential spends one of
the account's failure tokens through a new `ratelimit.fail`, and a correct one
never touches that budget. A brute-force run against one account is throttled
exactly as before — five failures then `429` — but the account's owner is never
turned away by someone else's guesses, and a successful login clears the
counter, erasing an attacker's progress. Verified: after an attacker trips the
lockout, the victim's correct password still returns `200`.

Both are Low: PT-1 discloses only whether an address is registered, and PT-2 is
a temporary, self-clearing lockout of a single named account, not a service-wide
outage. Neither crosses the authorisation boundary. They are recorded because a
generic login message paired with a talkative registration endpoint, and a
lockout that punishes the victim rather than the attacker, are the kind of small
inconsistencies that are cheap to fix and awkward to explain later.

---

## 9. Process findings

### 9.1 Security tooling breaks the application it audits

Installing Semgrep into the application virtualenv upgraded `starlette` past
FastAPI's pin and broke imports entirely. Tooling now installs through `pipx`.

A consequence worth repeating, because it produces a *convincing wrong answer*:
`pip-audit` run from pipx audits its own environment and reports "No known
vulnerabilities found". `scripts/audit.sh` sets `PIPAPI_PYTHON_LOCATION`
accordingly. During this review that trap was hit again, and the clean result
was believed for several minutes before the warning text was read.

### 9.2 Measuring the wrong process

The upload memory hypothesis (§3) was first tested with `/usr/bin/time -v` on
`curl`, which reports curl's memory rather than the server's. The result looked
like evidence and was not. Re-measuring the uvicorn process directly disproved
the hypothesis.

### 9.3 Assertions in tooling find what tests do not

Both reviews have had findings surfaced by `assert count == 1` guards in scripted
edits rather than by testing — a duplicated endpoint registration in the first
round, and in this round several silently-skipped patches that would otherwise
have left the frontend and backend inconsistent.

---

## 10. Architectural limitations

Known limitations of the application's design, independent of any particular
deployment.

- **Upload disk consumption.** Large files are spooled to temporary storage
  before the size check rejects them. Bounded by disk and by authentication
  rate limits, not otherwise capped.
- **Uploaded files are not scanned for malware.** Type is validated, content is
  not. Serving everything as a download bounds but does not eliminate the risk.
- **`scripts/backup.sh` writes locally and reports failure only to its own
  output.** Off-site copies and failure alerting are left to the operator.
- **Backup archives contain password hashes and sealed secrets.** The script
  does not set restrictive permissions on them; operators should.
- **An SSO sign-in adopts a matching local account.** Correct where the provider
  is authoritative for the addresses it asserts; a takeover primitive where it
  federates identities it does not own. See 8.4.
- **A local role override cannot be revoked by the directory.** Removing someone
  from the admin group at the provider does not remove an override set here.
- **The provider's ID token is stored unencrypted** between sign-in and
  sign-out, so it appears in database backups. Settings secrets are sealed;
  this is not.
- **No SAML.** Single sign-on is OIDC only; a SAML-only organisation needs a
  broker in front.
- **Rate limiting remains in-memory and per-process** (see below); the
  failure-only per-account budget fixes the lockout DoS but still does not share
  counters across instances.
- `style-src 'unsafe-inline'` in the CSP, because components use inline styles.
- Rate limiting is in-memory and per-process; multiple instances do not share
  counters.
- No self-service password reset.
- ZAP coverage of JSON request bodies remains low (see the first review).
- Transport hardening such as HSTS, log aggregation and alerting are outside
  the application and must be provided by the deployment.

---

## 11. Remaining dependency advisories

`starlette` remains pinned by FastAPI's `<0.42` constraint. Following §1, the
reachability of each was re-assessed rather than carried forward:

| Advisory | Concerns | Reachable? |
|---|---|---|
| `PYSEC-2026-161` | `request.url.path` vs routed path | No — authorisation is by route dependency, and `request.url` is never read |
| `PYSEC-2026-248` | `request.url.hostname` | No — same |
| `PYSEC-2026-1942` | Quadratic Range parsing | **Was yes** — mitigated in the endpoint (§1) |
| `PYSEC-2026-1941` | Event loop blocked spooling uploads | Partially — bounded by the size limit and rate limiting |
| `PYSEC-2026-2281` | Windows path handling | No — Linux only |

`cryptography` advisories cover X.509 chain verification and PKCS#7 decryption.
This application uses Fernet only.

**These assessments expire when the code changes.** §1 is the demonstration:
a correctly-deferred advisory became exploitable because a feature shipped that
used the affected code path. Re-check reachability when adding features, not
only when the advisory list changes.

---

## Reproducing

    ./scripts/audit.sh          # dependency CVEs and static analysis
    ./scripts/guard_test.sh     # authorisation boundary; exits non-zero on failure
    ./scripts/sla_test.sh       # deadline recalculation and pause-on-customer
    ./scripts/delete_test.sh    # soft-delete rules and redaction

`scripts/smoke.sh` and `scripts/delete_test.sh` predate session-derived portal
identity and still pass `?email=` to endpoints that ignore it. They need
updating before their results mean anything.

ZAP requires Java 17+ and a plan file; see `deploy/zap-plan.yaml.example`.
