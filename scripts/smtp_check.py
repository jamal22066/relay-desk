"""Verify SMTP credentials by sending one message. Respects the allowlist."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal  # noqa: E402
from app.mailer import allowed, build, config, send  # noqa: E402

db = SessionLocal()
try:
    # the effective settings, so this checks what the application would really
    # use rather than what .env happens to say
    cfg = config(db)
finally:
    db.close()

to = sys.argv[1] if len(sys.argv) > 1 else (cfg.allowlist or [""])[0]
if not to:
    sys.exit("No recipient. Pass one as an argument or set a recipient allowlist.")
if not allowed(to, cfg.allowlist):
    sys.exit(f"{to} is not in the allowlist {cfg.allowlist} — refusing.")

print(f"connecting to {cfg.host}:{cfg.port} as {cfg.username}")
try:
    send(cfg, build(cfg, to, "", "Relay desk SMTP check",
                    "If you are reading this, SMTP is configured correctly.\n\n"
                    "Sent by scripts/smtp_check.py — no ticket is involved."))
    print(f"sent to {to}")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
    raise SystemExit(1)
