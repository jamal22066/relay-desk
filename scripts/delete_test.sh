#!/usr/bin/env bash
# Soft deletion: what may be removed, what may not, and what survives.
#
# Deletion leaves a tombstone rather than erasing a row, so both halves need
# checking — that the body really is gone from the API response, and that the
# row really is still in the database.
#
# The fixture is created here rather than taken from the seed data: a ticket
# filed through the API carries an `is_original` first event, which is one of
# the two protected kinds, and seeded tickets do not.
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

AJ=$(mktemp); CJ=$(mktemp)
REF=""
cleanup() {
  if [ -n "$REF" ]; then
    q "DELETE FROM outbox WHERE ticket_ref='$REF';" >/dev/null 2>&1
    q "DELETE FROM events WHERE ticket_id IN (SELECT id FROM tickets WHERE ref='$REF');" >/dev/null 2>&1
    q "DELETE FROM tickets WHERE ref='$REF';" >/dev/null 2>&1
  fi
  rm -f "$AJ" "$CJ"
}
trap cleanup EXIT

jq_() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null; }

echo "== sign in =="
check "agent login" \
  "$(http -c "$AJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
      -d "{\"email\":\"$AGENT_EMAIL\",\"password\":\"$AGENT_PASSWORD\"}")" 200
check "customer login" \
  "$(http -c "$CJ" -X POST "$API/auth/login" -H 'content-type: application/json' \
      -d "{\"email\":\"$CUSTOMER_EMAIL\",\"password\":\"$CUSTOMER_PASSWORD\"}")" 200

echo "== build a fixture ticket =="
REF=$(curl -s -b "$CJ" -X POST "$API/tickets" -H 'content-type: application/json' \
  -d '{"subject":"Deletion rules fixture","body":"Original description, which must be undeletable.","track":"it","category":"Laptop & hardware","priority":"P4"}' \
  | jq_ 'd["ref"]')
check_set "ticket created by the customer" "$REF"
[ -n "$REF" ] || finish delete_test

# a second customer message, which they are allowed to remove
curl -s -b "$CJ" -X POST "$API/portal/tickets/$REF/events" -H 'content-type: application/json' \
  -d '{"body":"A follow-up from the customer, which they may remove."}' -o /dev/null
# an agent reply, which they are not
curl -s -b "$AJ" -X POST "$API/tickets/$REF/events" -H 'content-type: application/json' \
  -d '{"body":"An agent reply, which the customer must not be able to remove.","kind":"comment"}' -o /dev/null
# a system event, which nobody may remove
curl -s -b "$AJ" -X PATCH "$API/tickets/$REF" -H 'content-type: application/json' \
  -d '{"priority":"P2"}' -o /dev/null

T=$(curl -s -b "$AJ" "$API/tickets/$REF")
OID=$(printf '%s' "$T" | jq_ '[e["id"] for e in d["events"] if e["is_original"]][0]')
CUSTID=$(printf '%s' "$T" | jq_ '[e["id"] for e in d["events"] if e["kind"]=="comment" and not e["is_original"] and e["actor"]==d["requester"]][0]')
AGID=$(printf '%s' "$T" | jq_ '[e["id"] for e in d["events"] if e["kind"]=="comment" and e["actor"]!=d["requester"]][0]')
SID=$(printf '%s' "$T" | jq_ '[e["id"] for e in d["events"] if e["kind"]=="system"][0]')
check_set "original description event" "$OID"
check_set "customer follow-up event" "$CUSTID"
check_set "agent reply event" "$AGID"
check_set "system event" "$SID"

echo "== protected events cannot be removed, even by an agent =="
check "DELETE original description" "$(http -b "$AJ" -X DELETE "$API/tickets/$REF/events/$OID")" 403
check "DELETE system event" "$(http -b "$AJ" -X DELETE "$API/tickets/$REF/events/$SID")" 403
check "original still live" \
  "$(q "SELECT (deleted_at IS NULL)::text FROM events WHERE id=$OID;" | tr -d ' ')" "true"

echo "== a customer may remove their own message, and only their own =="
check "portal DELETE of the agent's live reply" \
  "$(http -b "$CJ" -X DELETE "$API/portal/tickets/$REF/events/$AGID")" 403
check "agent's reply untouched" \
  "$(q "SELECT (deleted_at IS NULL)::text FROM events WHERE id=$AGID;" | tr -d ' ')" "true"
check "portal DELETE of their own follow-up" \
  "$(http -b "$CJ" -X DELETE "$API/portal/tickets/$REF/events/$CUSTID")" 200

echo "== the body is blank on the wire, not merely hidden in the UI =="
AFTER=$(curl -s -b "$AJ" "$API/tickets/$REF")
check "marked deleted" \
  "$(printf '%s' "$AFTER" | jq_ "[bool(e['deleted_at']) for e in d['events'] if e['id']==$CUSTID][0]")" "True"
check "deleted_by recorded" \
  "$(printf '%s' "$AFTER" | jq_ "[bool(e['deleted_by']) for e in d['events'] if e['id']==$CUSTID][0]")" "True"
check "body emptied in the API response" \
  "$(printf '%s' "$AFTER" | jq_ "'empty' if not [e['body'] for e in d['events'] if e['id']==$CUSTID][0] else 'LEAKED'")" \
  "empty"

echo "== the row survives in postgres (tombstone, not erasure) =="
check "row still present" "$(q "SELECT count(*) FROM events WHERE id=$CUSTID;" | tr -d ' ')" "1"
check "deleted_at set in the database" \
  "$(q "SELECT (deleted_at IS NOT NULL)::text FROM events WHERE id=$CUSTID;" | tr -d ' ')" "true"
check "the text is still on disk for the audit trail" \
  "$(q "SELECT (length(body) > 0)::text FROM events WHERE id=$CUSTID;" | tr -d ' ')" "true"

echo "== anonymous callers are refused =="
check "anonymous portal DELETE" "$(http -X DELETE "$API/portal/tickets/$REF/events/$AGID")" 401
check "anonymous agent DELETE" "$(http -X DELETE "$API/tickets/$REF/events/$AGID")" 401

finish delete_test
