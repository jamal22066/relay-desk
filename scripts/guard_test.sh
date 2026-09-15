#!/usr/bin/env bash
API=${RELAY_API:-http://localhost:8000/api}
# Credentials: defaults match scripts/seed_users.py; passwords fall back to SEED_PASSWORD.
AGENT_EMAIL=${RELAY_AGENT_EMAIL:-arivera@example.com}
AGENT_PASSWORD=${RELAY_AGENT_PASSWORD:-${SEED_PASSWORD:-}}
CUSTOMER_EMAIL=${RELAY_CUSTOMER_EMAIL:-dana@example.com}
CUSTOMER_PASSWORD=${RELAY_CUSTOMER_PASSWORD:-${SEED_PASSWORD:-}}
: "${AGENT_PASSWORD:?set RELAY_AGENT_PASSWORD or SEED_PASSWORD}"
: "${CUSTOMER_PASSWORD:?set RELAY_CUSTOMER_PASSWORD or SEED_PASSWORD}"
AJ=$(mktemp); CJ=$(mktemp)
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }
FAIL=0
row() {
  printf "   %-46s %-4s" "$1" "$2"
  if [ -n "$3" ] && [ "$2" != "$3" ]; then echo "  EXPECTED $3"; FAIL=1; else echo; fi
}

curl -s -c "$AJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$AGENT_EMAIL\",\"password\":\"$AGENT_PASSWORD\"}" -o /dev/null
curl -s -c "$CJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$CUSTOMER_EMAIL\",\"password\":\"$CUSTOMER_PASSWORD\"}" -o /dev/null

echo "== anonymous is locked out (expect 401) =="
for p in /meta /counts "/tickets?view=all" /tickets/TKT-1041 /portal/tickets; do
  row "$p" "$(code "$API$p")" 401
done

echo "== customer cannot reach agent endpoints (expect 403) =="
for p in /meta /counts "/tickets?view=all" /tickets/TKT-1041; do
  row "$p" "$(code -b "$CJ" "$API$p")" 403
done

echo "== agent can (expect 200) =="
for p in /meta /counts "/tickets?view=all" /tickets/TKT-1041; do
  row "$p" "$(code -b "$AJ" "$API$p")" 200
done

echo "== customer portal returns only their own tickets =="
curl -s -b "$CJ" "$API/portal/tickets" | python3 -c '
import json,sys
d=json.load(sys.stdin)
print("   tickets:", len(d), "| emails:", set(t["email"] for t in d))
print("   notes leaked:", any(e["kind"]=="note" for t in d for e in t["events"]))'

echo "== customer cannot write an internal note (expect 403) =="
row "POST /tickets/TKT-1041/events kind=note" "$(code -b "$CJ" -X POST "$API/tickets/TKT-1041/events" \
  -H 'content-type: application/json' -d '{"body":"x","kind":"note"}')"

echo "== ticket creation attributes to the session, not the payload =="
curl -s -b "$CJ" -X POST "$API/tickets" -H 'content-type: application/json' \
  -d '{"subject":"Printer offline again","body":"Third time this week, same printer.","track":"it","category":"Laptop & hardware","priority":"P4"}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  ", d["ref"], "|", d["requester"], "|", d["email"], "|", d["org"])'

rm -f "$AJ" "$CJ"

[ "$FAIL" = 0 ] && echo "== all guards held ==" || echo "== GUARD FAILURES ABOVE =="
exit $FAIL
