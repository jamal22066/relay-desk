#!/usr/bin/env bash
API=http://localhost:8000/api
J=$(mktemp)
curl -s -c "$J" -X POST "$API/auth/login" -H 'content-type: application/json' \
  -d '{"email":"jamal@relaydesk.io","password":"devpassword123"}' -o /dev/null

show() {
  PGPASSWORD=relay_dev psql -h 127.0.0.1 -U relay -d relaydesk -tAc \
    "SELECT priority || ' ' || status || ' | due ' || to_char(due_at,'MM-DD HH24:MI')
     || ' | paused ' || coalesce(paused_seconds,0)/60 || 'm'
     FROM tickets WHERE ref='$1';" | sed 's/^/   /'
}

echo "== TKT-1044 baseline (P2, created 03:48) =="; show TKT-1044

echo "== raise to P1: deadline recalculates from creation, not now =="
curl -s -b "$J" -X PATCH "$API/tickets/TKT-1044" -H 'content-type: application/json' \
  -d '{"priority":"P1"}' -o /dev/null; show TKT-1044

echo "== back to P3 =="
curl -s -b "$J" -X PATCH "$API/tickets/TKT-1044" -H 'content-type: application/json' \
  -d '{"priority":"P3"}' -o /dev/null; show TKT-1044

echo
echo "== enable pause-on-customer =="
PGPASSWORD=relay_dev psql -h 127.0.0.1 -U relay -d relaydesk -tAc \
  "INSERT INTO settings (key, value, is_secret, updated_at) VALUES ('sla_pause_on_customer','true',false,now())
   ON CONFLICT (key) DO UPDATE SET value='true';" > /dev/null

echo "-- park it on the customer --"
curl -s -b "$J" -X PATCH "$API/tickets/TKT-1044" -H 'content-type: application/json' \
  -d '{"status":"Waiting on customer"}' -o /dev/null; show TKT-1044
PGPASSWORD=relay_dev psql -h 127.0.0.1 -U relay -d relaydesk -tAc \
  "SELECT '   paused_at set: ' || (paused_at IS NOT NULL) FROM tickets WHERE ref='TKT-1044';"

echo "-- backdate the pause by 3h, then resume --"
PGPASSWORD=relay_dev psql -h 127.0.0.1 -U relay -d relaydesk -tAc \
  "UPDATE tickets SET paused_at = paused_at - interval '3 hours' WHERE ref='TKT-1044';" > /dev/null
curl -s -b "$J" -X PATCH "$API/tickets/TKT-1044" -H 'content-type: application/json' \
  -d '{"status":"Open"}' -o /dev/null; show TKT-1044
echo "   (deadline should have moved ~3h later, paused ~180m)"

PGPASSWORD=relay_dev psql -h 127.0.0.1 -U relay -d relaydesk -c \
  "DELETE FROM settings WHERE key='sla_pause_on_customer';" > /dev/null
rm -f "$J"
