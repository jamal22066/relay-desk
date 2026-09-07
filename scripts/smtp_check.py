"""Verify SMTP credentials by sending one message. Respects the allowlist."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.mailer import allowed, build, send  # noqa: E402

to = sys.argv[1] if len(sys.argv) > 1 else (settings.allowlist or [""])[0]
if not to:
    sys.exit("No recipient. Pass one as an argument or set SMTP_ALLOWLIST.")
if not allowed(to):
    sys.exit(f"{to} is not in SMTP_ALLOWLIST {settings.allowlist} — refusing.")

print(f"connecting to {settings.smtp_host}:{settings.smtp_port} as {settings.smtp_username}")
try:
    send(build(to, "", "Relay desk SMTP check",
               "If you are reading this, SMTP is configured correctly.\n\n"
               "Sent by scripts/smtp_check.py — no ticket is involved."))
    print(f"sent to {to}")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
    raise SystemExit(1)
