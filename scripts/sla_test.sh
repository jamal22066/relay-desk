#!/usr/bin/env bash
# Deadline recalculation and pause-on-customer.
#
# The engine stores due_at rather than computing it on read, so the thing worth
# testing is that every transition writes the right value — a stale deadline is
# invisible until someone is measured against it.
cd "$(dirname "$0")/.." || exit 1
. scripts/_assert.sh

API=${RELAY_API:-http://localhost:8000/api}
# Credentials: defaults match scripts/seed_users.py; password falls back to SEED_PASSWORD.
AGENT_EMAIL=${RELAY_AGENT_EMAIL:-arivera@example.com}
AGENT_PASSWORD=${RELAY_AGENT_PASSWORD:-${SEED_PASSWORD:-}}
: "${AGENT_PASSWORD:?set RELAY_AGENT_PASSWORD or SEED_PASSWORD}"
REF=${RELAY_SLA_REF:-TKT-1044}

J=$(mktemp)
trap 'rm -f "$J"; q "DELETE FROM settings WHERE key='"'"'sla_pause_on_customer'"'"';" >/dev/null 2>&1' EXIT

echo "== sign in =="
check "agent login" \
  "$(http -c "$J" -X POST "$API/auth/login" -H 'content-type: application/json' \
      -d "{\"email\":\"$AGENT_EMAIL\",\"password\":\"$AGENT_PASSWORD\"}")" 200

patch() {  # patch <json>
  http -b "$J" -X PATCH "$API/tickets/$REF" -H 'content-type: application/json' -d "$1"
}
field() { q "SELECT coalesce($1::text,'') FROM tickets WHERE ref='$REF';" | tr -d ' '; }
due_epoch() { q "SELECT coalesce(extract(epoch from due_at)::bigint,0) FROM tickets WHERE ref='$REF';" | tr -d ' '; }

echo "== baseline =="
# Normalise: a previous run may have left accrued pause time on this ticket,
# and deadline() adds paused_seconds, so an un-reset ticket silently shifts
# every expectation below.
q "UPDATE tickets SET paused_seconds = 0, paused_at = NULL, status = 'Open'
   WHERE ref='$REF';" >/dev/null
CREATED=$(q "SELECT extract(epoch from created_at)::bigint FROM tickets WHERE ref='$REF';" | tr -d ' ')
check_set "$REF exists, created_at" "$CREATED"
check_set "due_at is set" "$(field due_at)"

echo "== raise to P1: deadline recalculates from creation, not from now =="
check "PATCH priority=P1" "$(patch '{"priority":"P1"}')" 200
check "priority stored" "$(field priority)" "P1"
P1_DUE=$(due_epoch)
# P1 target is 4h from created_at; allow a minute of slack for clock/rounding
check "due_at == created_at + 4h" \
  "$(python3 -c "print('yes' if abs($P1_DUE - ($CREATED + 4*3600)) <= 60 else 'no ($P1_DUE)')")" "yes"

echo "== back to P3 =="
check "PATCH priority=P3" "$(patch '{"priority":"P3"}')" 200
P3_DUE=$(due_epoch)
check "due_at == created_at + 24h" \
  "$(python3 -c "print('yes' if abs($P3_DUE - ($CREATED + 24*3600)) <= 60 else 'no ($P3_DUE)')")" "yes"
check "a later target moves the deadline out" \
  "$(python3 -c "print('yes' if $P3_DUE > $P1_DUE else 'no')")" "yes"

echo "== pause on customer =="
q "INSERT INTO settings (key, value, is_secret, updated_at)
   VALUES ('sla_pause_on_customer','true',false,now())
   ON CONFLICT (key) DO UPDATE SET value='true';" >/dev/null
BEFORE_PAUSE=$(due_epoch)

check "PATCH status=Waiting on customer" "$(patch '{"status":"Waiting on customer"}')" 200
check "paused_at recorded" "$(field "(paused_at is not null)")" "true"
check "deadline unchanged while parked" "$(due_epoch)" "$BEFORE_PAUSE"

echo "== resume after a backdated 3h pause =="
q "UPDATE tickets SET paused_at = paused_at - interval '3 hours' WHERE ref='$REF';" >/dev/null
check "PATCH status=Open" "$(patch '{"status":"Open"}')" 200
check "paused_at cleared" "$(field "(paused_at is null)")" "true"

PAUSED_MIN=$(q "SELECT coalesce(paused_seconds,0)/60 FROM tickets WHERE ref='$REF';" | tr -d ' ')
check "paused_seconds ~= 180 minutes" \
  "$(python3 -c "print('yes' if abs($PAUSED_MIN - 180) <= 2 else 'no ($PAUSED_MIN)')")" "yes"

AFTER=$(due_epoch)
check "deadline pushed out by the working time lost" \
  "$(python3 -c "print('yes' if abs(($AFTER - $BEFORE_PAUSE) - 3*3600) <= 120 else 'no (moved %ds)' % ($AFTER - $BEFORE_PAUSE))")" "yes"

echo "== restore =="
check "PATCH priority=P3 (leave as found)" "$(patch '{"priority":"P3"}')" 200
q "UPDATE tickets SET paused_seconds = 0 WHERE ref='$REF';" >/dev/null

finish sla_test
