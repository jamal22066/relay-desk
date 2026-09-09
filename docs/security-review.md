# Security review

**Relay Desk** · September 2026
Reviewer: Jamal Nasir · Scope: full application and its production deployment
Self-assessed. No independent review has been performed.

---

## Summary

A security review of Relay Desk covering dependency vulnerabilities, static
analysis, dynamic scanning, manual review of the authorisation model, and the
production deployment on a public domain.

Five classes of issue were found and fixed: a broken authorisation boundary that
allowed customers to read internal notes, an unlimited login endpoint, missing
HTTP security headers, outdated cryptographic dependencies, and unverified email
addresses that made outbound mail an abuse vector. A further set of advisories
was assessed and deferred with reasoning recorded.

The most useful finding is methodological. Automated scanning found zero
application-logic issues across two ZAP runs and 499 Semgrep rules. The one
genuine vulnerability in this codebase was an authorisation flaw, found by
reading the code and confirmed by a purpose-written test. Scanners did not and
structurally could not find it.

---

## Tooling

| Tool | Version | Scope |
|---|---|---|
| `npm audit` | bundled | JavaScript dependency CVEs |
| `pip-audit` | 2.10.1 | Python dependency CVEs |
| Semgrep OSS | 1.176.1 | Static analysis, 499 rules |
| ZAP | 2.17.0 | Dynamic scanning, authenticated and unauthenticated |

All free and reproducible via `./scripts/audit.sh`. Semgrep and pip-audit are
installed through `pipx`, deliberately outside the application virtualenv — see
§7.1.

---

## 1. Authorisation boundary (Critical — fixed)

**Found:** manual review during development.

The customer portal filtered internal notes out of ticket threads in the React
component. The agent API endpoint, which returned the unfiltered thread, had no
authentication at all. A customer — or anyone who could reach the API — could
request `/api/tickets/{ref}` directly and receive every internal note on the
ticket.

The filtering worked in practice only because the portal *component* called the
portal endpoint. Nothing enforced that choice.

**Fixed by moving the boundary from the client to the server:**

- Agent endpoints require the agent or admin role via a FastAPI dependency.
  Customers receive 403.
- Portal endpoints derive the customer's identity from the session rather than
  from a query parameter, so one customer cannot request another's tickets by
  guessing an email address.
- Note filtering happens during serialisation, not in the component.

**Verified by `scripts/guard_test.sh`,** which asserts across three identities
that anonymous callers get 401, customers get 403 on every agent endpoint,
portal queries return only the session's own tickets, and no internal note
appears in a portal response. It exits non-zero on any mismatch — see §7.2 for
why that matters.

**Generalisation:** a guard implemented in the client is not a guard. It is a
convention that holds until someone uses `curl`.

---

## 2. Unlimited authentication attempts (High — fixed)

The login endpoint accepted unlimited attempts from any source. On a public
domain that is credential stuffing with no friction, and server logs showed
automated scanners probing the host within minutes of its DNS record appearing.

**Fixed** with two independent budgets in `app/ratelimit.py`:

| Scope | Budget | Purpose |
|---|---|---|
| Source IP | 30 per 5 minutes | Stops one source enumerating many accounts |
| Target email | 5 per 15 minutes | Stops one account being brute forced |

The split matters. A per-IP limit alone lets an attacker lock every user behind
a shared NAT out of the service by exhausting the budget. With a per-email
budget, an attack on one account trips that account's limit without affecting
anyone else — verified by confirming a valid login still succeeds from an IP
that has just been rate limited against a different address.

Registration is also rate limited per IP (§4), and a successful login clears the
counters so a legitimate user is not penalised for a typo.

**Known limitation:** the store is in-memory and per-process. Adequate for a
single instance; a fleet needs Redis or equivalent.

Behind Cloudflare the client address arrives in `CF-Connecting-IP`. That header
is trustworthy *only* because the tunnel means nothing reaches the application
except via Cloudflare. If the app is ever exposed directly, a client can forge
it and the limits become meaningless.

---

## 3. Missing HTTP security headers (Medium — fixed)

**Found:** ZAP 2.17.0, unauthenticated scan.

| Alert | Risk | Instances |
|---|---|---|
| Content Security Policy header not set | Medium | 3 |
| Missing anti-clickjacking header | Medium | 3 |
| `X-Content-Type-Options` header missing | Low | 5 |

Neither FastAPI nor Vite sets security headers by default. The application was
therefore clickjackable and had no policy restricting script or style sources.

**Fixed** by `app/headers.py`, a middleware setting `Content-Security-Policy`,
`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and
`Permissions-Policy` on every response including errors. Matching headers were
added to the Vite dev server config.

**Rescan** cleared all three. CSP-quality alerts replaced them:

- `script-src unsafe-eval` and `unsafe-inline` — required by Vite's hot module
  reload. Present only in the dev server config; production serves a static
  build through FastAPI, whose CSP uses plain `script-src 'self'`.
- `style-src unsafe-inline` — **genuine and unresolved.** Components use inline
  `style={{...}}` for priority colours and ticket row spines. Removing it
  requires moving every inline style into CSS classes. Residual risk is low,
  since no untrusted content is rendered as markup, but this is a real weakening
  of the policy rather than a false positive.

Verified in production: the headers are present on responses served through the
Cloudflare tunnel, not just locally.

---

## 4. Unverified email as an abuse vector (High — fixed)

Registration was open and created immediately usable accounts. Combined with
outbound notifications, that made the server able to send mail to any address an
anonymous party typed — a nuisance-mail vector carrying the sending domain's
reputation, with the domain's daily send quota as the only ceiling.

**Fixed** by requiring email verification for local accounts:

- New local accounts start `email_verified = false` and cannot sign in.
- A signed, 48-hour token is emailed to the address. The token is scoped to the
  user id *and* their current address, so it stops working if the address
  changes, and carries a `purpose` claim so a session token cannot be
  substituted for it. Both properties are asserted in testing.
- Directory accounts are exempt: the directory has already established the
  address.
- Accounts predating the feature were grandfathered as verified in the
  migration, since each was created deliberately.

Verification emails bypass the recipient allowlist by design — the address was
just typed by whoever is registering, the content is fixed, and no ticket data
is included. Registration is rate limited per IP to bound the abuse this
permits, and a failed login on an unverified account resends the link, which the
per-email budget caps at five in fifteen minutes.

Only with verification in place was the allowlist widened to `*` in production.
The ordering was deliberate: an open registration endpoint plus unrestricted
outbound mail is the combination worth avoiding.

---

## 5. Dependency vulnerabilities

### 5.1 Fixed

| Package | From | To | Rationale |
|---|---|---|---|
| `pyjwt` | 2.10.1 | 2.13.0 | Signs session and verification tokens |
| `cryptography` | 44.0.0 | 46.0.7 | Seals stored SMTP and LDAP credentials |
| `python-dotenv` | 1.0.1 | 1.2.2 | Config parsing |

Verified after upgrade: application imports, Fernet seal/unseal round-trip
(confirming stored secrets remained readable), and the full authentication test
suite.

The pyjwt upgrade surfaced a separate issue: **`SECRET_KEY` was 27 bytes, below
the 32-byte minimum for HMAC-SHA256.** It signs session cookies and verification
tokens, and derives the Fernet key sealing stored secrets. Rotated to 64 bytes
in both environments. Doing so invalidates every session and makes previously
sealed secrets unreadable — cheap at the time because nothing was yet stored
through the settings page, and considerably more expensive later.

### 5.2 Assessed and deferred

**`cryptography` — four advisories remain open, none applicable.**

`PYSEC-2026-3552` scopes to `pkcs7_decrypt_*`. `PYSEC-2026-3553` and `3554`
concern the X.509 chain verifier and name constraints. `GHSA-537c-gmf6-5ccf`
covers statically linked OpenSSL in the project's wheels.

This application uses `Fernet` and nothing else from the library. SMTP TLS goes
through Python's `ssl` module; LDAP through `ldap3`. None of the affected code
paths are reachable.

**`starlette` — advisories pinned behind FastAPI's `<0.42` constraint.**

The significant one is `PYSEC-2026-161`: a malformed `Host` header causes
`request.url.path` to differ from the routed path, so middleware performing
path-based authorisation can be bypassed. `PYSEC-2026-248` is the same class via
a request path lacking a leading `/`.

Both require the application to make security decisions based on `request.url`.
It does not. Authorisation runs as route dependencies, which execute after
routing on the matched route. Verified: `grep -rn "request.url" app/` returns
nothing, and the only middleware is CORS and the security-headers middleware.

**Condition for revisiting: if path-based authorisation middleware is ever
added, FastAPI and starlette must be upgraded first.** Recorded in the README.

---

## 6. Scanning results

### 6.1 Static analysis

Semgrep OSS, 499 rules across `p/default`, `p/security-audit`, `p/react` and
`p/python`, over 70 files: **zero findings.** `npm audit`: **zero
vulnerabilities.**

Both genuine, with a limit worth stating. Semgrep OSS matches patterns; it
cannot reason about whether an authorisation dependency is attached to the right
endpoints. It would not have found §1.

### 6.2 Dynamic scanning

**Unauthenticated:** ZAP found the three header issues in §3 and could not
proceed past the login screen — correct behaviour, confirming the authentication
gate holds against an anonymous crawler.

**Authenticated:** an admin session cookie was injected into every request, with
the endpoint list imported from the OpenAPI schema. Two runs, the second at
`defaultStrength: insane` and `defaultThreshold: low`. **Two informational
alerts, no findings.**

**This is weak evidence and should not be read as a clean bill of health.** Both
runs completed in roughly 75 seconds against a 90-minute budget. Inspecting the
alert instances showed ZAP fuzzing HTTP headers and a few query parameters — the
API takes JSON request bodies and path parameters, which ZAP's active scanner
does not vary without additional configuration. Coverage was low.

Two endpoints were excluded deliberately: `/api/auth/logout`, which would
invalidate the scanning session, and `/api/admin/test/smtp`, which would send
real email through a live relay.

**What dynamic scanning could not test:** a scanner authenticated as a single
identity cannot detect authorisation flaws, because it has nothing to compare
against. It never attempts a customer's session against an agent endpoint. That
is precisely the shape of §1.

---

## 7. Process findings

### 7.1 Security tooling broke the application

Installing Semgrep into the application virtualenv upgraded `starlette` to
1.6.0, along with `pydantic` and `pyjwt` — because Semgrep depends on `mcp`,
which pulls a modern dependency tree. FastAPI 0.115.6 requires
`starlette<0.42.0`. The application stopped importing:

```
TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'
```

pip reported the conflict but installed anyway. Recovered with
`pip install --force-reinstall -r requirements.txt`.

**Security tooling now installs through `pipx`, isolated from the application
environment.** A consequence: `pip-audit` then audits *its own* environment
unless pointed at the project explicitly, and reports "No known vulnerabilities
found" — true and useless. `scripts/audit.sh` sets `PIPAPI_PYTHON_LOCATION` to
avoid this, which is worth knowing because the misleading result looks exactly
like success.

### 7.2 A test that reported failures as passes

`guard_test.sh` printed observed status codes without comparing them to expected
ones. After a database restore, four checks returned 401 where 403 was expected
— a customer login was failing because that account's email had been changed —
and the output looked plausible at a glance.

The script now asserts each expected code, prints `EXPECTED nnn` on mismatch,
and exits non-zero.

### 7.3 Duplicated endpoint registrations

An `assert count == 1` in a scripted edit revealed that a block of two endpoints
had been appended to `app/api.py` twice. FastAPI registers the first and
silently ignores the second, so nothing appeared broken and no test failed.

Assertions in tooling found what testing did not.

### 7.4 Credential exposure during setup

A Google Workspace app password was exposed during SMTP configuration. It grants
full account access, not just SMTP, and bypasses 2FA. Revoked and regenerated;
subsequent entry used `read -s` so the value never appeared in a terminal or in
shell history.

The account it belongs to is a dedicated sender rather than a personal mailbox,
which bounded the exposure to one throwaway identity within the domain.

---

## 8. Deployment posture

Production runs on a Rocky Linux 9 VPS, deliberately separate from the
development laptop.

**Ingress:** a Cloudflare Tunnel. No inbound port is open — `firewalld` permits
only SSH, and the tunnel establishes an *outbound* connection to Cloudflare's
edge. TLS terminates at Cloudflare; the origin address is never exposed.

**Host:** SSH is key-only. Password authentication was enabled by the cloud-init
image and had to be explicitly disabled — the first attempt failed silently
because `sshd_config.d/` files load in lexical order and cloud-init's `50-`
prefix won over a `99-` hardening file. Verified with `sshd -T`, which prints
the *effective* configuration, and by confirming a password attempt is rejected
without a prompt.

**Containers:** rootless Podman under a dedicated service user with lingering
enabled, so the stack survives reboot without a login session. The application
publishes only to `127.0.0.1`, reachable by the tunnel and nothing else.

**Application:** `ENVIRONMENT=production` suppresses `/docs` and
`/openapi.json`, `COOKIE_SECURE=true` requires HTTPS for the session cookie, and
the frontend is a static build served by FastAPI rather than a dev server.

**Not yet done:** HSTS is not enabled at Cloudflare. No automated backups of the
`pgdata` volume. No log aggregation or alerting.

---

## 9. Open items

- `style-src 'unsafe-inline'` in the production CSP (§3).
- Rate limiting is in-memory and per-process (§2).
- No self-service password reset; a locked-out local user needs an
  administrator and a SQL statement.
- Development credentials are committed in `scripts/seed_users.py` and the
  README. Acceptable for a private repository; must change before that stops
  being true.
- ZAP coverage of JSON request bodies (§6.2).
- No automated backups, HSTS, or alerting on the production host (§8).
- The production database holds real third-party email addresses and ticket
  content. Ordinary for a support system, but it is personal data on a host with
  no backup or retention policy.

---

## Reproducing

    ./scripts/audit.sh          # dependency CVEs and static analysis
    ./scripts/guard_test.sh     # authorisation boundary; exits non-zero on failure
    ./scripts/sla_test.sh       # deadline recalculation and pause-on-customer
    ./scripts/delete_test.sh    # soft-delete rules and redaction

`scripts/smoke.sh` and `scripts/delete_test.sh` predate session-derived portal
identity and still pass `?email=` to endpoints that ignore it. They need
updating before their results mean anything.

ZAP requires Java 17+ and a plan file; see `deploy/zap-plan.yaml.example`. The
session cookie placeholder must be replaced with a live token before running.
