"""OIDC authentication against an external identity provider.

The ID token's signature is verified against the provider's published JWKS.
Decoding without verification would let anyone mint a token claiming any
identity, so that verification is the entire security of this flow.

State is a signed, short-lived token rather than a server-side session entry:
it proves the callback corresponds to an authorisation request this application
started, without needing shared state across workers.
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from jwt import PyJWKClient

from app.config import settings

log = logging.getLogger(__name__)

STATE_PURPOSE = "oidc-state"
STATE_TTL_SECONDS = 600

_discovery: dict | None = None
_discovery_at: float = 0.0
_jwks: PyJWKClient | None = None


class OidcError(Exception):
    pass


@dataclass
class OidcIdentity:
    subject: str
    email: str
    display_name: str
    groups: list[str]
    # the raw, still-signed ID token. Kept only to pass back as id_token_hint
    # on RP-initiated logout, which is how the provider knows whose session to
    # end without us asserting it ourselves.
    id_token: str = ""

    @property
    def is_admin(self) -> bool:
        g = settings.oidc_admin_group
        return bool(g) and g in self.groups

    @property
    def is_agent(self) -> bool:
        g = settings.oidc_agent_group
        return bool(g) and g in self.groups


def discovery() -> dict:
    """Fetch and cache the provider's configuration for an hour."""
    global _discovery, _discovery_at
    if _discovery and time.time() - _discovery_at < 3600:
        return _discovery

    url = settings.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        r = httpx.get(url, timeout=10)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise OidcError(f"Could not reach the identity provider: {e}") from e

    _discovery = r.json()
    _discovery_at = time.time()
    return _discovery


def _jwk_client() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(discovery()["jwks_uri"], cache_keys=True)
    return _jwks


def issue_state(next_path: str = "/") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "purpose": STATE_PURPOSE,
            "next": next_path,
            "iat": now,
            "exp": now + timedelta(seconds=STATE_TTL_SECONDS),
        },
        settings.secret_key,
        algorithm="HS256",
    )


def read_state(token: str) -> dict | None:
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return claims if claims.get("purpose") == STATE_PURPOSE else None


def authorize_url(state: str) -> str:
    from urllib.parse import urlencode

    params = {
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "scope": settings.oidc_scopes,
        "redirect_uri": settings.oidc_redirect_uri,
        "state": state,
    }
    return discovery()["authorization_endpoint"] + "?" + urlencode(params)


def exchange(code: str) -> OidcIdentity:
    """Swap the authorisation code for tokens and verify the ID token."""
    try:
        r = httpx.post(
            discovery()["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri,
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
            },
            timeout=10,
        )
    except httpx.HTTPError as e:
        raise OidcError(f"Token exchange failed: {e}") from e

    if r.status_code != 200:
        log.warning("oidc token endpoint returned %s: %s", r.status_code, r.text[:200])
        raise OidcError("The identity provider rejected the sign-in.")

    id_token = r.json().get("id_token")
    if not id_token:
        raise OidcError("No ID token in the provider's response.")

    try:
        key = _jwk_client().get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256", "ES256"],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer,
        )
    except Exception as e:
        log.warning("oidc id_token verification failed: %s", e)
        raise OidcError("The identity provider's response could not be verified.")

    email = (claims.get("email") or "").lower().strip()
    if not email:
        raise OidcError("The identity provider did not supply an email address.")
    if claims.get("email_verified") is False:
        raise OidcError("That address is not verified with the identity provider.")

    groups = claims.get(settings.oidc_groups_claim) or []
    if isinstance(groups, str):
        groups = [groups]
    groups = [g.lstrip("/") for g in groups]

    return OidcIdentity(
        subject=claims["sub"],
        email=email,
        display_name=(claims.get("name") or email).strip(),
        groups=groups,
        id_token=id_token,
    )


def supports_end_session() -> bool:
    """Whether the provider advertises RP-initiated logout at all.

    Not every provider does — Google, for one, publishes no
    end_session_endpoint. The UI asks before offering to end a session that
    cannot be ended, rather than showing a button that quietly does nothing.
    """
    try:
        return bool(discovery().get("end_session_endpoint"))
    except OidcError:
        return False


def end_session_url(id_token: str | None, post_logout_redirect: str = "") -> str | None:
    """The provider's RP-initiated logout URL, or None if it offers none.

    Ending the IdP session is deliberately not part of signing out of this
    application: the person may have other applications open against the same
    provider, and taking their session away everywhere is a bigger decision
    than leaving this one. The caller asks for this explicitly.

    Returns None rather than raising when the provider does not advertise
    end_session_endpoint, or when it is unreachable — failing to reach the
    provider must not prevent a local sign-out.
    """
    try:
        endpoint = discovery().get("end_session_endpoint")
    except OidcError:
        return None
    if not endpoint:
        return None

    from urllib.parse import urlencode

    params = {}
    if id_token:
        params["id_token_hint"] = id_token
    else:
        # without a hint the provider cannot identify the session, and most
        # will show an "are you sure" interstitial instead
        params["client_id"] = settings.oidc_client_id
    if post_logout_redirect:
        params["post_logout_redirect_uri"] = post_logout_redirect

    return endpoint + ("&" if "?" in endpoint else "?") + urlencode(params)
