"""LDAP authentication against FreeIPA / 389 Directory Server.

Two-stage: a service account searches for the user by email, then we attempt to
bind as that user's DN with their password. A successful bind is the only proof
of identity — we never compare password material ourselves.
"""
import logging
from dataclasses import dataclass

from ldap3 import ALL, SIMPLE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException

from app.config import settings

log = logging.getLogger(__name__)


@dataclass
class LdapIdentity:
    dn: str
    email: str
    display_name: str
    is_agent: bool


def _server() -> Server:
    tls = None
    if settings.ldap_server.startswith("ldaps://"):
        import ssl
        tls = Tls(validate=ssl.CERT_REQUIRED if settings.ldap_tls_verify else ssl.CERT_NONE)
    return Server(settings.ldap_server, get_info=ALL, tls=tls)


def _escape(value: str) -> str:
    """RFC 4515 filter escaping. Without this, a crafted email is an injection."""
    out = []
    for ch in value:
        if ch in "\\*()\x00":
            out.append("\\%02x" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def _in_agent_group(conn: Connection, user_dn: str, member_of: list[str]) -> bool:
    target = settings.ldap_agent_group
    if not target:
        return False

    # FreeIPA populates memberOf natively; prefer it when present
    if member_of:
        return any(g.lower() == target.lower() for g in member_of)

    # Fallback: ask the group whether it lists this user
    if not settings.ldap_group_base:
        return False
    conn.search(
        search_base=settings.ldap_group_base,
        search_filter=f"(&(objectClass=groupOfNames)(member={_escape(user_dn)}))",
        attributes=["cn"],
    )
    return any(e.entry_dn.lower() == target.lower() for e in conn.entries)


def authenticate(email: str, password: str) -> LdapIdentity | None:
    """Return an identity on successful bind, else None. Never raises."""
    if not settings.ldap_enabled or not password:
        return None

    try:
        server = _server()

        with Connection(
            server,
            user=settings.ldap_bind_dn or None,
            password=settings.ldap_bind_password or None,
            authentication=SIMPLE if settings.ldap_bind_dn else None,
            auto_bind=True,
        ) as svc:
            svc.search(
                search_base=settings.ldap_user_base,
                search_filter=settings.ldap_user_filter.format(email=_escape(email)),
                attributes=[settings.ldap_attr_name, settings.ldap_attr_email, "memberOf"],
            )
            if len(svc.entries) != 1:
                log.info("ldap: %d entries for %s", len(svc.entries), email)
                return None

            entry = svc.entries[0]
            user_dn = entry.entry_dn
            member_of = [str(g) for g in (entry.memberOf.values if "memberOf" in entry else [])]
            display = str(entry[settings.ldap_attr_name]) if settings.ldap_attr_name in entry else email
            mail = str(entry[settings.ldap_attr_email]) if settings.ldap_attr_email in entry else email

            # the actual credential check
            user_conn = Connection(server, user=user_dn, password=password, authentication=SIMPLE)
            if not user_conn.bind():
                log.info("ldap: bind rejected for %s", user_dn)
                return None

            is_agent = _in_agent_group(svc, user_dn, member_of)
            user_conn.unbind()

            return LdapIdentity(
                dn=user_dn,
                email=mail.lower().strip(),
                display_name=display.strip(),
                is_agent=is_agent,
            )

    except LDAPException as e:
        log.warning("ldap error for %s: %s", email, e)
        return None
