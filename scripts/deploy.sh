#!/usr/bin/env bash
# Deploy the current origin/main to this host.
#
# Run on the VPS as the service user (rootless Podman — root cannot see these
# containers). It backs up, shows what is about to land, applies it, and proves
# the result is healthy before returning. Migrations run inside the app
# container's entrypoint on `up`, so the backup in step 1 is the only thing
# standing between a bad migration and the live database — it aborts the deploy
# if it fails.
#
#   ./scripts/deploy.sh
#
# set -e: stop at the first failure rather than plough on past a failed backup
# or a failed build. set -u: an unset variable is a bug, not an empty string.
# pipefail: a failure anywhere in a pipeline fails the pipeline.
set -euo pipefail

cd "$(dirname "$0")/.."

# Container names match scripts/backup.sh; override both together if your
# podman-compose project name differs.
DB_CONTAINER="${DB_CONTAINER:-relay-desk_db_1}"
APP_CONTAINER="${APP_CONTAINER:-relay-desk_app_1}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8080/healthz}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"   # seconds to wait for /healthz

step() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
abort() { printf '\033[31mDEPLOY ABORTED: %s\033[0m\n' "$*" >&2; exit 1; }

# The containers are rootless and belong to the service user. As root, podman
# sees none of them and every step below would fail with a confusing "no such
# container" — so refuse early with a clear message instead.
if [ "$(id -u)" -eq 0 ]; then
  abort "run this as the service user (relay), not root — the containers are rootless"
fi

# Entered via `su - relay` rather than a fresh login, XDG_RUNTIME_DIR can be
# unset; podman then reads the wrong state directory and reports that the
# containers do not exist. Anchor it to this user's runtime dir.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# --- preconditions: refuse to deploy from a divergent server tree ----------
# Checked before anything is touched, so a dirty or ahead tree costs nothing.
step "Preconditions"
git fetch --quiet origin

if [ -n "$(git status --porcelain)" ]; then
  git status --short
  abort "working tree is dirty — commit, stash or discard local changes on the server first"
fi

ahead="$(git rev-list --count origin/main..HEAD)"
if [ "$ahead" -ne 0 ]; then
  git log origin/main..HEAD --oneline
  abort "HEAD is $ahead commit(s) ahead of origin/main — the server has commits that were never pushed"
fi
echo "clean working tree, HEAD is not ahead of origin/main"

# --- 1. backup: the only safety net before migrations ----------------------
step "1. Backup (the safety net before migrations)"
./scripts/backup.sh || abort "backup failed — refusing to migrate without one"

# --- 2. what this pull will bring in ---------------------------------------
step "2. Incoming changes (HEAD..origin/main)"
if [ -z "$(git log HEAD..origin/main --oneline)" ]; then
  echo "already up to date with origin/main — nothing to pull"
else
  git log HEAD..origin/main --oneline
  echo
  echo "files changed:"
  git diff --stat HEAD origin/main
fi

# --- 3. current settings overrides -----------------------------------------
# A stale override can sit inert until unrelated code starts honouring it;
# seeing the live table before deploying is how that is caught. Secret values
# are sealed and shown masked — this never unseals or prints them.
step "3. Settings table (database overrides, secrets masked)"
podman exec "$DB_CONTAINER" psql -U relay -d relaydesk -P pager=off -c \
  "SELECT key,
          is_secret,
          CASE WHEN is_secret THEN '******' ELSE coalesce(value, '') END AS value,
          coalesce(updated_by, '-') AS updated_by,
          updated_at
     FROM settings
    ORDER BY key;"

# --- 4. pull, build, recreate ----------------------------------------------
# podman-compose does not reliably detect a changed image, so recreate with
# down then up rather than up alone.
step "4. Pull, build, recreate"
git pull --ff-only origin main
podman-compose build app
podman-compose down
podman-compose up -d

# --- 5. wait for health, bounded -------------------------------------------
# /healthz needs no session, so it answers over plain HTTP on the loopback even
# though COOKIE_SECURE=true makes authenticated endpoints reject an insecure
# cookie. That is why this is http://127.0.0.1:8080 and not https — do not
# "correct" it; an authenticated probe here would 401 for the cookie reason.
step "5. Waiting for $HEALTH_URL (up to ${HEALTH_TIMEOUT}s)"
deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
until curl -fsS -o /dev/null "$HEALTH_URL"; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "--- app container logs (tail) ---" >&2
    podman logs --tail 40 "$APP_CONTAINER" 2>&1 | sed 's/^/  /' >&2 || true
    abort "not healthy after ${HEALTH_TIMEOUT}s"
  fi
  sleep 3
done
echo "healthy"

# --- 6. resolved SMTP config -----------------------------------------------
# Prove settings resolution end to end (database -> .env -> default). A broken
# resolution is visible here, not weeks later when someone reports missing mail.
# The password is never read or printed.
step "6. Resolved SMTP config (as the running app sees it)"
# -i so podman forwards this heredoc to the container's stdin; without it
# `python -` reads nothing and the step silently prints an empty config.
podman exec -i "$APP_CONTAINER" python - <<'PY'
from app import mailer
from app.db import SessionLocal

db = SessionLocal()
try:
    c = mailer.config(db)
finally:
    db.close()

print(f"  enabled   : {c.enabled}")
print(f"  host:port : {c.host}:{c.port}")
print(f"  username  : {c.username}")
print(f"  from      : {c.from_name} <{c.from_addr}>")
print(f"  allowlist : {', '.join(c.allowlist) or '(empty — everything is suppressed)'}")
print(f"  base_url  : {c.base_url}")
PY

step "Deploy complete"
