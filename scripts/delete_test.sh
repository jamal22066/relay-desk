#!/usr/bin/env bash
API=http://localhost:8000/api
REF=TKT-1041
show() { python3 -c '
import json, sys
for e in json.load(sys.stdin).get("events", []):
    mark = "[removed by %s]" % e["deleted_by"] if e.get("deleted_at") else e["body"][:44]
    print("   %3d %-7s %-16s %s" % (e["id"], e["kind"], e["actor"], mark))
' ; }

echo "== before =="; curl -s "$API/tickets/$REF" | show

CID=$(curl -s "$API/tickets/$REF" | python3 -c 'import json,sys; print([e["id"] for e in json.load(sys.stdin)["events"] if e["actor"]=="Dana Whitfield"][0])')
SID=$(curl -s -X PATCH "$API/tickets/$REF" -H 'content-type: application/json' -d '{"priority":"P2"}' \
      | python3 -c 'import json,sys; print([e["id"] for e in json.load(sys.stdin)["events"] if e["kind"]=="system"][0])')

echo "== agent removes customer comment $CID =="
curl -s -X DELETE "$API/tickets/$REF/events/$CID" | show

echo "== system event $SID must be refused =="
curl -s -o /dev/null -w "   http %{http_code}\n" -X DELETE "$API/tickets/$REF/events/$SID"

echo "== body must be blank on the wire, not just hidden =="
curl -s "$API/tickets/$REF" | python3 -c 'import json,sys
e=[e for e in json.load(sys.stdin)["events"] if e["id"]=='"$CID"'][0]
print("   LEAK:", repr(e["body"])) if e["body"] else print("   blank, clean")'

echo "== customer cannot remove an agent message =="
AID=$(curl -s "$API/tickets/$REF" | python3 -c 'import json,sys; print([e["id"] for e in json.load(sys.stdin)["events"] if e["actor"]=="J. Nasir" and e["kind"]=="comment"][0])')
curl -s -o /dev/null -w "   http %{http_code}\n" -X DELETE \
  "$API/portal/tickets/$REF/events/$AID?email=dana@northgate.io"

echo "== row survives in postgres =="
PGPASSWORD=relay_dev psql -h 127.0.0.1 -U relay -d relaydesk -tAc \
  "SELECT id, deleted_by, left(body,30) FROM events WHERE id=$CID;" | sed 's/^/   /'
