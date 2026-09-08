#!/usr/bin/env bash
API=http://localhost:8000/api
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
try jamal@relaydesk.io devpassword123
try jamal@jamalsblog.com devpassword123

echo "== directory accounts =="
try jamal.nasir@relaydesk.test 'LdapTest123!'
try tremaine.hart@relaydesk.test 'LdapTest123!'
try ext@relaydesk.test 'LdapTest123!'

echo "== rejections =="
try jamal.nasir@relaydesk.test wrongpassword
try nobody@relaydesk.test 'LdapTest123!'

echo "== provisioned rows =="
PGPASSWORD=relay_dev psql -h 127.0.0.1 -U relay -d relaydesk -tAc \
  "SELECT email, role, auth_source, coalesce(role_override,'-') FROM users ORDER BY auth_source, email;" \
  | sed 's/|/  /g; s/^/   /'
