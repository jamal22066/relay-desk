"""Reset and load demo tickets. DESTRUCTIVE: truncates tickets + events."""
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Event, Ticket, utcnow  # noqa: E402

NOW = utcnow()
H = lambda h: NOW - timedelta(hours=h)  # noqa: E731

ROWS = [
    dict(
        ref="TKT-1041", hours=5.5, priority="P1", status="Open", track="saas",
        category="Login & SSO", assignee="A. Rivera",
        requester="Dana Whitfield", email="dana@example.com", org="Acme",
        subject="SAML login loops back to the sign-in page",
        body="Since this morning nobody gets past the identity provider redirect. "
             "It bounces straight back to the login screen. Roughly 40 people blocked.",
        first_response=5.0,
        events=[
            (5.0, "A. Rivera", "comment", "Picking this up now. Can you confirm whether the "
                                          "certificate on your IdP was rotated in the last 48 hours?"),
            (4.2, "Dana Whitfield", "comment", "Our security team rotated it Tuesday night. "
                                               "Should we have told you?"),
            (4.0, "A. Rivera", "note", "Stale cert in the SP metadata. Same root cause as TKT-0987."),
        ],
    ),
    dict(
        ref="TKT-1042", hours=52, priority="P2", status="Open", track="it",
        category="Security concern", assignee="R. Okafor",
        requester="Marcus Bell", email="mbell@example.com", org="Internal",
        subject="Phishing mail got past the filter and two people clicked",
        body="Spoofed finance sender asking for a wire approval. Two clicks confirmed. "
             "Passwords reset already, need to know what else was exposed.",
        first_response=50,
        events=[(50, "R. Okafor", "comment", "Both accounts are locked and sessions revoked. "
                                             "Pulling sign-in logs now.")],
    ),
    dict(
        ref="TKT-1043", hours=31, priority="P3", status="Waiting on customer", track="saas",
        category="Billing & licensing", assignee="M. Delacroix",
        requester="Owen Baptiste", email="owen@example.com", org="Initech",
        subject="Invoice shows 60 seats, we only bought 45",
        body="The renewal invoice bills us for 60 seats. Our order form says 45. "
             "Holding payment until this is sorted.",
        first_response=20,
        events=[(20, "M. Delacroix", "comment", "I see 15 seats added on 3 March by an admin on "
                                                "your side. Could you send the PO number?")],
    ),
    dict(
        ref="TKT-1044", hours=9, priority="P2", status="New", track="saas",
        category="API / integration", assignee="Unassigned",
        requester="Priya Raghavan", email="priya@example.com", org="Globex",
        subject="Webhook deliveries stopped after we changed the endpoint",
        body="We moved our receiver to a new hostname and nothing arrives. "
             "The endpoint returns 200 when I curl it directly.",
    ),
    dict(
        ref="TKT-1045", hours=14, priority="P3", status="Open", track="it",
        category="Network / VPN", assignee="R. Okafor",
        requester="Colin Yates", email="cyates@example.com", org="Internal",
        subject="VPN drops every twenty minutes on the new laptop",
        body="Reconnects on its own but I lose whatever I was doing. Started after "
             "imaging on Monday. Only on wifi, wired is fine.",
        first_response=11,
        events=[(11, "R. Okafor", "comment", "Can you export the connection log and attach it? "
                                             "Instructions are on the intranet.")],
    ),
    dict(
        ref="TKT-1046", hours=2, priority="P4", status="New", track="it",
        category="Account & password", assignee="Unassigned",
        requester="Amara Sowande", email="asowande@example.com", org="Internal",
        subject="Need Figma access for the two new designers",
        body="Starting Monday. Both need edit on the product file, view on everything else.",
    ),
    dict(
        ref="TKT-1039", hours=96, priority="P3", status="Resolved", track="saas",
        category="Data export", assignee="S. Iyer",
        requester="Dana Whitfield", email="dana@example.com", org="Acme",
        subject="Export to CSV truncates at 10,000 rows",
        body="We need the full dataset for a quarterly filing. The export stops silently.",
        first_response=90, resolved=48,
        events=[(48, "S. Iyer", "comment", "Fixed in this week's release. Exports over 10,000 rows "
                                           "now queue and arrive by email.")],
    ),
]

db = SessionLocal()
db.execute(text("TRUNCATE tickets, events RESTART IDENTITY CASCADE"))
db.execute(text("ALTER SEQUENCE ticket_ref_seq RESTART WITH 1048"))

for r in ROWS:
    evs = r.pop("events", [])
    age = r.pop("hours")
    fr = r.pop("first_response", None)
    res = r.pop("resolved", None)
    t = Ticket(
        **r,
        created_at=H(age),
        updated_at=H(min([e[0] for e in evs], default=age)),
        first_response_at=H(fr) if fr else None,
        resolved_at=H(res) if res else None,
    )
    db.add(t)
    db.flush()
    for at, actor, kind, body in evs:
        db.add(Event(ticket_id=t.id, at=H(at), actor=actor, kind=kind, body=body))

db.commit()
print(f"seeded {len(ROWS)} tickets")
