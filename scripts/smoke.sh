#!/usr/bin/env bash
set -euo pipefail
API=${RELAY_API:-http://localhost:8000/api}
AGENT_NAME=${RELAY_AGENT_NAME:-A. Rivera}
CUSTOMER_EMAIL=${RELAY_CUSTOMER_EMAIL:-dana@example.com}
REF=${1:-TKT-1041}
J() { python3 -m json.tool; }

echo "== 1. agent replies: New -> Open, first_response_at set =="
curl -s -X POST "$API/tickets/$REF/events" -H 'content-type: application/json' \
  -d '{"body":"Picking this up. Was your IdP certificate rotated in the last 48 hours?","kind":"comment"}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" status:",d["status"]," first_response_at:",d["first_response_at"])'

echo "== 2. internal note: status unchanged =="
curl -s -X POST "$API/tickets/$REF/events" -H 'content-type: application/json' \
  -d '{"body":"Stale cert in the SP metadata. Same root cause as TKT-0987.","kind":"note"}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" status:",d["status"]," events:",[e["kind"] for e in d["events"]])'

echo "== 3. portal view must hide the note =="
curl -s "$API/portal/tickets?email=$CUSTOMER_EMAIL" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)[0]; print(" events:",[e["kind"] for e in d["events"]]); print(" LEAK" if any(e["kind"]=="note" for e in d["events"]) else " clean")'

echo "== 4. patch to Waiting on customer, system event appended =="
curl -s -X PATCH "$API/tickets/$REF" -H 'content-type: application/json' \
  -d "{\"status\":\"Waiting on customer\",\"assignee\":\"$AGENT_NAME\"}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" status:",d["status"]," assignee:",d["assignee"]); print(" system:",[e["body"] for e in d["events"] if e["kind"]=="system"])'

echo "== 5. customer replies: Waiting on customer -> Open =="
curl -s -X POST "$API/portal/tickets/$REF/events?email=$CUSTOMER_EMAIL" \
  -H 'content-type: application/json' -d '{"body":"Yes, security rotated it Tuesday night."}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" status:",d["status"])'

echo "== 6. wrong email cannot reply =="
curl -s -o /dev/null -w " http %{http_code}\n" -X POST \
  "$API/portal/tickets/$REF/events?email=attacker@elsewhere.io" \
  -H 'content-type: application/json' -d '{"body":"let me in"}'

echo "== 7. views =="
for V in all mine unassigned breach done; do
  N=$(curl -s "$API/tickets?view=$V" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
  echo " $V: $N"
done

echo "== 8. bad category is rejected =="
curl -s -o /dev/null -w " http %{http_code}\n" -X POST "$API/tickets" \
  -H 'content-type: application/json' \
  -d '{"subject":"test","body":"test body","track":"it","category":"Login & SSO","requester":"X","email":"x@y.com"}'
