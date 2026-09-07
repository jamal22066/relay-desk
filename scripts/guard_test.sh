#!/usr/bin/env bash
API=http://localhost:8000/api
AJ=$(mktemp); CJ=$(mktemp)
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }
row() { printf "   %-46s %s\n" "$1" "$2"; }

curl -s -c "$AJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d '{"email":"jamal@relaydesk.io","password":"devpassword123"}' -o /dev/null
curl -s -c "$CJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d '{"email":"dana@northgate.io","password":"devpassword123"}' -o /dev/null

echo "== anonymous is locked out (expect 401) =="
for p in /meta /counts "/tickets?view=all" /tickets/TKT-1041 /portal/tickets; do
  row "$p" "$(code "$API$p")"
done

echo "== customer cannot reach agent endpoints (expect 403) =="
for p in /meta /counts "/tickets?view=all" /tickets/TKT-1041; do
  row "$p" "$(code -b "$CJ" "$API$p")"
done

echo "== agent can (expect 200) =="
for p in /meta /counts "/tickets?view=all" /tickets/TKT-1041; do
  row "$p" "$(code -b "$AJ" "$API$p")"
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
