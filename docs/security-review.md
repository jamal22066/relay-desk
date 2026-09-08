# Security review

**Relay Desk** · September 2026
Reviewer: Jamal Nasir · Scope: full application, self-assessed

---

## Summary

A security review of Relay Desk covering dependency vulnerabilities, static
analysis, dynamic scanning, and manual review of the authorisation model.

Three classes of issue were found and fixed: missing HTTP security headers,
outdated cryptographic dependencies, and — earlier in development — a broken
authorisation boundary that allowed customers to read internal notes. A further
set of advisories was assessed and deferred with reasoning recorded.

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

All are free and reproducible via `./scripts/audit.sh`.

Semgrep and pip-audit are installed through `pipx`, deliberately outside the
application virtualenv — see §6.1.

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
appears in a portal response.

**Generalisation:** a guard implemented in the client is not a guard. It is a
convention that holds until someone uses `curl`.

---

## 2. Missing HTTP security headers (Medium — fixed)

**Found:** ZAP 2.17.0, unauthenticated scan against the frontend.

| Alert | Risk | Instances |
|---|---|---|
| Content Security Policy header not set | Medium | 3 |
| Missing anti-clickjacking header | Medium | 3 |
| `X-Content-Type-Options` header missing | Low | 5 |

Neither FastAPI nor Vite sets security headers by default. The application was
therefore clickjackable, and had no policy restricting script or style sources.

**Fixed** by `app/headers.py`, a middleware setting `Content-Security-Policy`,
`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and
`Permissions-Policy` on every response including errors. Matching headers were
added to the Vite dev server config.

**Rescan** cleared all three. Three CSP-quality alerts replaced them:

- `script-src unsafe-eval` and `script-src unsafe-inline` — required by Vite's
  hot module reload. Present only in the dev server config; the API's CSP uses
  plain `script-src 'self'`. These disappear in a production build.
- `style-src unsafe-inline` — **genuine and unresolved.** The React components
  use inline `style={{...}}` for priority colours and ticket row spines.
  Removing it requires moving every inline style into CSS classes. The residual
  risk is low, since no untrusted content is rendered as markup, but this is a
  real weakening of the policy rather than a false positive.

---

## 3. Dependency vulnerabilities

### 3.1 Fixed

| Package | From | To | Rationale |
|---|---|---|---|
| `pyjwt` | 2.10.1 | 2.13.0 | Signs session tokens. Several 2026 advisories. |
| `cryptography` | 44.0.0 | 46.0.7 | Seals stored SMTP and LDAP credentials. |
| `python-dotenv` | 1.0.1 | 1.2.2 | Config parsing. |

Verified after upgrade: application imports, Fernet seal/unseal round-trip
(confirming stored secrets remained readable), and the full authentication test
suite.

### 3.2 Assessed and deferred

**`cryptography` — four advisories remain open, none applicable.**

`PYSEC-2026-3552` scopes to `pkcs7_decrypt_der`, `pkcs7_decrypt_pem` and
`pkcs7_decrypt_smime`. `PYSEC-2026-3553` and `3554` concern the X.509
certificate chain verifier and name constraints. `GHSA-537c-gmf6-5ccf` covers
statically linked OpenSSL in the project's wheels.

This application uses `Fernet` and nothing else from the library. SMTP TLS goes
through Python's `ssl` module; LDAP through `ldap3`. None of the affected code
paths are reachable.

**`starlette` 0.41.3 — nine advisories, pinned by FastAPI's `<0.42` constraint.**

The significant one is `PYSEC-2026-161`: a malformed `Host` header causes
`request.url.path` to differ from the routed path, so middleware performing
path-based authorisation can be bypassed. `PYSEC-2026-248` is the same class,
via a request path lacking a leading `/`, affecting `request.url.hostname`.

Both require the application to make security decisions based on `request.url`.
This application does not. Authorisation runs as route dependencies
(`require_agent`, `require_admin`), which execute after routing on the matched
route. The only middleware is CORS and the security-headers middleware, neither
of which reads `request.url`.

Verified: `grep -rn "request.url" app/` returns nothing.

**Condition for revisiting: if path-based authorisation middleware is ever
added, FastAPI and starlette must be upgraded first.** This is recorded in the
README.

**`pip` and `setuptools`** — build tooling in the virtualenv, not runtime
dependencies. Upgraded for report cleanliness; not an application exposure.

---

## 4. Static analysis

Semgrep OSS, 499 rules across `p/default`, `p/security-audit`, `p/react` and
`p/python`, over 70 files: **zero findings.**

`npm audit` over the frontend dependency tree: **zero vulnerabilities.**

Both are genuine results, with a limit worth stating. Semgrep OSS matches
patterns; it cannot reason about whether an authorisation dependency is attached
to the right endpoints. It would not have found §1.

---

## 5. Dynamic scanning

### 5.1 Unauthenticated

ZAP crawled the frontend and found the three header issues in §2. It could not
proceed past the login screen, which is the correct behaviour and confirms the
authentication gate holds against an anonymous crawler.

No junk accounts were created, despite an open registration endpoint, because
ZAP never reached the registration form.

### 5.2 Authenticated

An admin session cookie was injected into every request via ZAP's `replacer`
job, with the endpoint list imported from the application's OpenAPI schema.
Two runs: Default Policy, then `defaultStrength: insane` with
`defaultThreshold: low`.

**Result: two informational alerts, no findings.**

**This result is weak evidence and should not be read as a clean bill of
health.** Both runs completed in roughly 75 seconds against a 90-minute budget.
Inspecting the alert instances showed ZAP fuzzing HTTP headers and a small
number of query parameters — the API takes JSON request bodies and path
parameters, which ZAP's active scanner does not vary without additional
configuration. Coverage was low.

Two endpoints were excluded deliberately: `/api/auth/logout`, which would
invalidate the scanning session, and `/api/admin/test/smtp`, which would send
real email through a live relay.

### 5.3 What dynamic scanning could not test

A scanner authenticated as a single identity cannot detect authorisation flaws,
because it has nothing to compare against. It never attempts a customer's
session against an agent endpoint. That is precisely the shape of §1.

`scripts/guard_test.sh` covers this directly and is the more valuable test.

---

## 6. Process findings

### 6.1 Security tooling broke the application

Installing Semgrep into the application virtualenv upgraded `starlette` to
1.6.0, `pydantic` to 2.13.5 and `pyjwt` to 2.13.0 — because Semgrep depends on
`mcp`, which pulls a modern dependency tree. FastAPI 0.115.6 requires
`starlette<0.42.0`. The application stopped importing:

```
TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'
```

pip reported the conflict but installed anyway. Recovered with
`pip install --force-reinstall -r requirements.txt`.

**Security tooling now installs through `pipx`, isolated from the application
environment.** A consequence: `pip-audit` then audits *its own* environment
unless pointed at the project explicitly, and reports "No known vulnerabilities
found" — which is true and useless. `scripts/audit.sh` sets
`PIPAPI_PYTHON_LOCATION` to avoid this.

### 6.2 A test that reported failures as passes

`guard_test.sh` printed observed status codes without comparing them to
expected ones. After a database restore, four checks returned 401 where 403 was
expected — a customer login was failing because the account's email had been
changed — and the output looked plausible at a glance.

The script now asserts each expected code, prints `EXPECTED nnn` on mismatch,
and exits non-zero.

### 6.3 Duplicated endpoint registrations

An `assert count == 1` in a scripted edit revealed that a block of two endpoints
had been appended to `app/api.py` twice. FastAPI registers the first and
silently ignores the second, so nothing appeared broken and no test failed.

Assertions in tooling found what testing did not.

---

## 7. Open items

- `style-src 'unsafe-inline'` in the production CSP (§2).
- No rate limiting on `/api/auth/login`. Unlimited authentication attempts are
  accepted.
- `cookie_secure=false`, correct for local HTTP, must be `true` behind TLS.
- No self-service password reset; a locked-out local user needs an
  administrator and a SQL statement.
- Development credentials are committed in `scripts/seed_users.py` and the
  README. Acceptable for a private repository running on one laptop; must
  change before either stops being true.
- ZAP coverage of JSON request bodies (§5.2).

---

## Reproducing

```
./scripts/audit.sh          # dependency CVEs and static analysis
./scripts/guard_test.sh     # authorisation boundary
./scripts/smoke.sh          # status transitions and note containment
./scripts/delete_test.sh    # soft-delete rules and redaction
```

ZAP requires Java 17+ and a plan file; see `deploy/zap-plan.yaml.example`. The
session cookie placeholder must be replaced with a live token before running.
