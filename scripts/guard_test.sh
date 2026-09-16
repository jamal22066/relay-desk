#!/usr/bin/env bash
# The authorisation boundary. If one script has to pass, it is this one.
cd "$(dirname "$0")/.." || exit 1
. scripts/_assert.sh

API=${RELAY_API:-http://localhost:8000/api}
# Credentials: defaults match scripts/seed_users.py; passwords fall back to SEED_PASSWORD.
AGENT_EMAIL=${RELAY_AGENT_EMAIL:-arivera@example.com}
AGENT_PASSWORD=${RELAY_AGENT_PASSWORD:-${SEED_PASSWORD:-}}
CUSTOMER_EMAIL=${RELAY_CUSTOMER_EMAIL:-dana@example.com}
CUSTOMER_PASSWORD=${RELAY_CUSTOMER_PASSWORD:-${SEED_PASSWORD:-}}
: "${AGENT_PASSWORD:?set RELAY_AGENT_PASSWORD or SEED_PASSWORD}"
: "${CUSTOMER_PASSWORD:?set RELAY_CUSTOMER_PASSWORD or SEED_PASSWORD}"
REF=${RELAY_REF:-TKT-1041}

AJ=$(mktemp); CJ=$(mktemp)
trap 'rm -f "$AJ" "$CJ"' EXIT

echo "== sign in =="
check "agent login" \
  "$(http -c "$AJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
      -d "{\"email\":\"$AGENT_EMAIL\",\"password\":\"$AGENT_PASSWORD\"}")" 200
check "customer login" \
  "$(http -c "$CJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
      -d "{\"email\":\"$CUSTOMER_EMAIL\",\"password\":\"$CUSTOMER_PASSWORD\"}")" 200

echo "== anonymous is locked out (expect 401) =="
for p in /meta /counts "/tickets?view=all" "/tickets/$REF" /portal/tickets; do
  check "$p" "$(http "$API$p")" 401
done

echo "== customer cannot reach agent endpoints (expect 403) =="
for p in /meta /counts "/tickets?view=all" "/tickets/$REF"; do
  check "$p" "$(http -b "$CJ" "$API$p")" 403
done

echo "== agent can (expect 200) =="
for p in /meta /counts "/tickets?view=all" "/tickets/$REF"; do
  check "$p" "$(http -b "$AJ" "$API$p")" 200
done

echo "== customer portal returns only their own tickets =="
PORTAL=$(curl -s -b "$CJ" "$API/portal/tickets")
check_set "portal returned tickets" \
  "$(printf '%s' "$PORTAL" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d) or "")' 2>/dev/null)"
check "every ticket belongs to the caller" \
  "$(printf '%s' "$PORTAL" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("yes" if d and all(t["email"]=="'"$CUSTOMER_EMAIL"'" for t in d) else "no")' 2>/dev/null)" "yes"
check "no internal note crossed the boundary" \
  "$(printf '%s' "$PORTAL" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("yes" if any(e["kind"]!="comment" for t in d for e in t["events"]) else "no")' 2>/dev/null)" "no"

echo "== customer cannot write an internal note (expect 403) =="
check "POST /tickets/$REF/events kind=note" \
  "$(http -b "$CJ" -X POST "$API/tickets/$REF/events" \
      -H 'content-type: application/json' -d '{"body":"x","kind":"note"}')" 403

echo "== ticket creation attributes to the session, not the payload =="
NEW=$(curl -s -b "$CJ" -X POST "$API/tickets" -H 'content-type: application/json' \
  -d '{"subject":"Printer offline again","body":"Third time this week, same printer.","track":"it","category":"Laptop & hardware","priority":"P4","requester":"Someone Else","email":"attacker@elsewhere.io","org":"Evil Corp"}')
NEWREF=$(printf '%s' "$NEW" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("ref",""))' 2>/dev/null)
check_set "ticket created" "$NEWREF"
check "requester taken from the session" \
  "$(printf '%s' "$NEW" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("email",""))' 2>/dev/null)" \
  "$CUSTOMER_EMAIL"
check_ne "payload email ignored" \
  "$(printf '%s' "$NEW" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("email",""))' 2>/dev/null)" \
  "attacker@elsewhere.io"

# leave the dataset as we found it
if [ -n "$NEWREF" ]; then
  q "DELETE FROM outbox WHERE ticket_ref='$NEWREF';" >/dev/null 2>&1
  q "DELETE FROM events WHERE ticket_id IN (SELECT id FROM tickets WHERE ref='$NEWREF');" >/dev/null 2>&1
  q "DELETE FROM tickets WHERE ref='$NEWREF';" >/dev/null 2>&1
fi

finish guard_test
