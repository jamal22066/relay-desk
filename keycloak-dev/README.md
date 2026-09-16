# Local Keycloak test realm

**A development fixture. Do not import this realm into anything that matters.**

`relay-desk-realm.json` rebuilds the Keycloak instance used to develop OIDC
sign-on, so the test IdP is reproducible rather than living only inside a
container. `../README.md` has the import and re-export commands.

## Keycloak is an example, not a requirement

Relay Desk speaks plain OIDC. It reads the provider's discovery document and
needs only four things from it — an authorization endpoint, a token endpoint, a
JWKS URI, and an ID token carrying `email` plus a groups claim. Anything that
offers those works: Entra ID, Okta, Auth0, Authentik, Google Workspace.
Keycloak is here because it runs locally in one container, not because the
application is coupled to it.

Nothing in this directory is needed to run against a real provider. Configure
the `OIDC_*` variables in `.env` and ignore this folder entirely. The
provider-specific notes — Entra's GUID group claims, Google's absent logout
endpoint — are in the main README under *Other identity providers*.

## Settings here that are wrong for production

This realm is tuned for a laptop. Four values in particular would be defects
anywhere else, and they are easy to inherit by copying the file:

| Setting | Here | Why it is wrong in production |
|---|---|---|
| `sslRequired` | `external` | Permits plaintext HTTP to the IdP from the host itself |
| `bruteForceProtected` | `false` | No lockout, so password guessing is unmetered |
| `directAccessGrantsEnabled` | `true` | Enables the password grant, which SSO exists to avoid |
| `redirectUris` | `http://127.0.0.1:5173/*` | A wildcard redirect URI is a token-leak vector off localhost |

`fullScopeAllowed` is also `true`, which hands the client every role in the
realm rather than the ones it needs.

## The two placeholders

`CHANGE_ME_KEYCLOAK_CLIENT_SECRET` and `CHANGE_ME_KEYCLOAK_TEST_PASSWORD` are
not usable credentials. Substitute them with `sed` at import time, exactly as
`ldap-dev/bootstrap.ldif` does, and never commit a substituted file.

## Re-exporting

A raw `kc.sh export` carries the realm's signing and encryption **private
keys**, the client secret, and a PBKDF2 hash per user. None of that belongs in
a repository. Always pass a fresh export through the sanitiser:

    python keycloak-dev/sanitise.py /tmp/kc-export/relay-desk-realm.json \
        keycloak-dev/relay-desk-realm.json

It strips the keys, replaces the secrets, and **refuses to write** if anything
key-shaped survives — so a future Keycloak that stores secrets somewhere new
fails loudly instead of leaking quietly. Check its exit code if you script it.
