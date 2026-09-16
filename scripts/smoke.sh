#!/usr/bin/env bash
# The ticket lifecycle: what each kind of message does to a ticket's state.
#
# Works on a ticket it creates itself, so it can run repeatedly without
# dragging the seeded demo data out of shape.
cd "$(dirname "$0")/.." || exit 1
. scripts/_assert.sh

API=${RELAY_API:-http://localhost:8000/api}
# Credentials: defaults match scripts/seed_users.py; passwords fall back to SEED_PASSWORD.
AGENT_EMAIL=${RELAY_AGENT_EMAIL:-arivera@example.com}
AGENT_PASSWORD=${RELAY_AGENT_PASSWORD:-${SEED_PASSWORD:-}}
CUSTOMER_EMAIL=${RELAY_CUSTOMER_EMAIL:-dana@example.com}
CUSTOMER_PASSWORD=${RELAY_CUSTOMER_PASSWORD:-${SEED_PASSWORD:-}}
OTHER_EMAIL=${RELAY_OTHER_EMAIL:-priya@example.com}
OTHER_PASSWORD=${RELAY_OTHER_PASSWORD:-${SEED_PASSWORD:-}}
: "${AGENT_PASSWORD:?set RELAY_AGENT_PASSWORD or SEED_PASSWORD}"
: "${CUSTOMER_PASSWORD:?set RELAY_CUSTOMER_PASSWORD or SEED_PASSWORD}"

AJ=$(mktemp); CJ=$(mktemp); OJ=$(mktemp)
REF=""
cleanup() {
  if [ -n "$REF" ]; then
    q "DELETE FROM outbox WHERE ticket_ref='$REF';" >/dev/null 2>&1
    q "DELETE FROM events WHERE ticket_id IN (SELECT id FROM tickets WHERE ref='$REF');" >/dev/null 2>&1
    q "DELETE FROM tickets WHERE ref='$REF';" >/dev/null 2>&1
  fi
  rm -f "$AJ" "$CJ" "$OJ"
}
trap cleanup EXIT

jq_() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null; }
post_event() {  # post_event <jar> <json>
  curl -s -b "$1" -X POST "$API/tickets/$REF/events" -H 'content-type: application/json' -d "$2"
}

echo "== sign in =="
check "agent login" \
  "$(http -c "$AJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
      -d "{\"email\":\"$AGENT_EMAIL\",\"password\":\"$AGENT_PASSWORD\"}")" 200
check "customer login" \
  "$(http -c "$CJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
      -d "{\"email\":\"$CUSTOMER_EMAIL\",\"password\":\"$CUSTOMER_PASSWORD\"}")" 200
check "third-party login" \
  "$(http -c "$OJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
      -d "{\"email\":\"$OTHER_EMAIL\",\"password\":\"$OTHER_PASSWORD\"}")" 200

echo "== a customer files a ticket =="
NEW=$(curl -s -b "$CJ" -X POST "$API/tickets" -H 'content-type: application/json' \
  -d '{"subject":"Smoke test: laptop will not wake","body":"Closing the lid suspends it and it never comes back.","track":"it","category":"Laptop & hardware","priority":"P3"}')
REF=$(printf '%s' "$NEW" | jq_ 'd["ref"]')
check_set "ticket created" "$REF"
[ -n "$REF" ] || finish smoke
check "starts as New" "$(printf '%s' "$NEW" | jq_ 'd["status"]')" "New"
check "no first response yet" "$(printf '%s' "$NEW" | jq_ 'bool(d["first_response_at"])')" "False"
check "first event is the original description" \
  "$(printf '%s' "$NEW" | jq_ 'd["events"][0]["is_original"]')" "True"

echo "== an agent reply moves New -> Open and stamps the first response =="
R=$(post_event "$AJ" '{"body":"Taking a look. Does it wake on a keypress or only on the power button?","kind":"comment"}')
check "status now Open" "$(printf '%s' "$R" | jq_ 'd["status"]')" "Open"
check "first_response_at set" "$(printf '%s' "$R" | jq_ 'bool(d["first_response_at"])')" "True"

echo "== an internal note changes nothing the customer can see =="
R=$(post_event "$AJ" '{"body":"Known firmware bug on this model. Same as TKT-0987.","kind":"note"}')
check "status unchanged" "$(printf '%s' "$R" | jq_ 'd["status"]')" "Open"
check "note is recorded for staff" \
  "$(printf '%s' "$R" | jq_ '"yes" if any(e["kind"]=="note" for e in d["events"]) else "no"')" "yes"

echo "== the portal never shows that note =="
P=$(curl -s -b "$CJ" "$API/portal/tickets")
check "customer sees the ticket" \
  "$(printf '%s' "$P" | jq_ '"yes" if any(t["ref"]=="'"$REF"'" for t in d) else "no"')" "yes"
check "no note crosses the boundary" \
  "$(printf '%s' "$P" | jq_ '"yes" if any(e["kind"]!="comment" for t in d if t["ref"]=="'"$REF"'" for e in t["events"]) else "no"')" "no"

echo "== parking on the customer records a system event =="
R=$(curl -s -b "$AJ" -X PATCH "$API/tickets/$REF" -H 'content-type: application/json' \
    -d '{"status":"Waiting on customer"}')
check "status is Waiting on customer" "$(printf '%s' "$R" | jq_ 'd["status"]')" "Waiting on customer"
check "system event appended" \
  "$(printf '%s' "$R" | jq_ '"yes" if any(e["kind"]=="system" for e in d["events"]) else "no"')" "yes"

echo "== a customer reply brings it back to Open =="
R=$(curl -s -b "$CJ" -X POST "$API/portal/tickets/$REF/events" -H 'content-type: application/json' \
    -d '{"body":"Only the power button wakes it."}')
check "status back to Open" "$(printf '%s' "$R" | jq_ 'd["status"]')" "Open"

echo "== someone else's ticket is not reachable =="
check "third party GET portal ticket list excludes it" \
  "$(curl -s -b "$OJ" "$API/portal/tickets" | jq_ '"yes" if any(t["ref"]=="'"$REF"'" for t in d) else "no"')" "no"
check "third party cannot reply (expect 404)" \
  "$(http -b "$OJ" -X POST "$API/portal/tickets/$REF/events" \
      -H 'content-type: application/json' -d '{"body":"let me in"}')" 404
check "anonymous cannot reply (expect 401)" \
  "$(http -X POST "$API/portal/tickets/$REF/events" \
      -H 'content-type: application/json' -d '{"body":"let me in"}')" 401

echo "== queue views respond =="
for V in all mine unassigned breach done; do
  check "view=$V" "$(http -b "$AJ" "$API/tickets?view=$V")" 200
done

echo "== validation =="
check "category from the wrong track is rejected" \
  "$(http -b "$CJ" -X POST "$API/tickets" -H 'content-type: application/json' \
      -d '{"subject":"mismatched","body":"body text here","track":"it","category":"Login & SSO","priority":"P4"}')" 422
check "unknown priority is rejected" \
  "$(http -b "$CJ" -X POST "$API/tickets" -H 'content-type: application/json' \
      -d '{"subject":"bad priority","body":"body text here","track":"it","category":"Laptop & hardware","priority":"P9"}')" 422

finish smoke
