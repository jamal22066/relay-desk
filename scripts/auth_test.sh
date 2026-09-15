#!/usr/bin/env bash
API=${RELAY_API:-http://localhost:8000/api}
# Credentials: defaults match scripts/seed_users.py; passwords fall back to SEED_PASSWORD.
AGENT_EMAIL=${RELAY_AGENT_EMAIL:-arivera@example.com}
AGENT_PASSWORD=${RELAY_AGENT_PASSWORD:-${SEED_PASSWORD:-}}
CUSTOMER_EMAIL=${RELAY_CUSTOMER_EMAIL:-dana@example.com}
CUSTOMER_PASSWORD=${RELAY_CUSTOMER_PASSWORD:-${SEED_PASSWORD:-}}
: "${AGENT_PASSWORD:?set RELAY_AGENT_PASSWORD or SEED_PASSWORD}"
: "${CUSTOMER_PASSWORD:?set RELAY_CUSTOMER_PASSWORD or SEED_PASSWORD}"
JAR=$(mktemp)

echo "== unauthenticated /me =="
curl -s -o /dev/null -w "   http %{http_code} (expect 401)\n" "$API/auth/me"

echo "== wrong password =="
curl -s -o /dev/null -w "   http %{http_code} (expect 401)\n" -X POST "$API/auth/login" \
  -H 'content-type: application/json' -d "{\"email\":\"$AGENT_EMAIL\",\"password\":\"nope\"}"

echo "== unknown account, same error =="
curl -s -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d '{"email":"nobody@nowhere.test","password":"whatever"}' | python3 -c 'import json,sys; print("  ", json.load(sys.stdin)["detail"])'

echo "== agent login =="
curl -s -c "$JAR" -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$AGENT_EMAIL\",\"password\":\"$AGENT_PASSWORD\"}" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  ", d["display_name"], "-", d["role"])'

echo "== cookie is httponly =="
grep -qi "httponly" "$JAR" && echo "   yes" || echo "   NO - check set_cookie"

echo "== /me with cookie =="
curl -s -b "$JAR" "$API/auth/me" | python3 -c 'import json,sys; print("  ", json.load(sys.stdin)["email"])'

echo "== customer login yields customer role =="
curl -s -c "$JAR.cust" -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d "{\"email\":\"$CUSTOMER_EMAIL\",\"password\":\"$CUSTOMER_PASSWORD\"}" \
  | python3 -c 'import json,sys; print("  ", json.load(sys.stdin)["role"])'

echo "== logout clears it =="
curl -s -b "$JAR" -c "$JAR" -X POST "$API/auth/logout" -o /dev/null
curl -s -b "$JAR" -o /dev/null -w "   http %{http_code} (expect 401)\n" "$API/auth/me"

rm -f "$JAR" "$JAR.cust"
