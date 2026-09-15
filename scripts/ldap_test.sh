#!/usr/bin/env bash
API=${RELAY_API:-http://localhost:8000/api}
# Credentials: defaults match scripts/seed_users.py; passwords fall back to SEED_PASSWORD.
AGENT_EMAIL=${RELAY_AGENT_EMAIL:-arivera@example.com}
AGENT_PASSWORD=${RELAY_AGENT_PASSWORD:-${SEED_PASSWORD:-}}
CUSTOMER_EMAIL=${RELAY_CUSTOMER_EMAIL:-dana@example.com}
CUSTOMER_PASSWORD=${RELAY_CUSTOMER_PASSWORD:-${SEED_PASSWORD:-}}
: "${AGENT_PASSWORD:?set RELAY_AGENT_PASSWORD or SEED_PASSWORD}"
: "${CUSTOMER_PASSWORD:?set RELAY_CUSTOMER_PASSWORD or SEED_PASSWORD}"
LDAP_TEST_PASSWORD=${LDAP_TEST_PASSWORD:-}
: "${LDAP_TEST_PASSWORD:?set LDAP_TEST_PASSWORD to the value substituted into ldap-dev/bootstrap.ldif}"
try() {
  printf "   %-32s " "$1"
  curl -s -X POST "$API/auth/login" -H 'content-type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$2\"}" \
    | python3 -c '
import json, sys
d = json.load(sys.stdin)
if "role" in d:
    print("%s | %s | %s" % (d["display_name"], d["role"], d["auth_source"]))
else:
    print("REJECTED")
'
}

echo "== local account still authenticates locally =="
try "$AGENT_EMAIL" "$AGENT_PASSWORD"
try "$CUSTOMER_EMAIL" "$CUSTOMER_PASSWORD"

echo "== directory accounts =="
try alex.smith@example.com "$LDAP_TEST_PASSWORD"
try sam.jones@example.com "$LDAP_TEST_PASSWORD"
try ext@example.com "$LDAP_TEST_PASSWORD"

echo "== rejections =="
try alex.smith@example.com wrongpassword
try nobody@example.com "$LDAP_TEST_PASSWORD"

echo "== provisioned rows =="
PGPASSWORD=relay_dev psql -h 127.0.0.1 -U relay -d relaydesk -tAc \
  "SELECT email, role, auth_source, coalesce(role_override,'-') FROM users ORDER BY auth_source, email;" \
  | sed 's/|/  /g; s/^/   /'
