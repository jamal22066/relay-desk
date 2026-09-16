# Shared assertion helpers for the integration scripts.
#
# Sourced, not executed. These scripts run against a live server and are the
# only automated verification this project has, so an assertion that prints
# without checking is worse than no assertion — it reports success it never
# established. Every observation goes through `check`, and the script exits
# non-zero if any of them failed.
#
# Deliberately no `set -e`: a failed check should be recorded and the remaining
# checks still run, so one run reports every problem rather than the first.

FAIL=0
CHECKS=0

# check <label> <actual> <expected>
check() {
  CHECKS=$((CHECKS + 1))
  if [ "$2" = "$3" ]; then
    printf "   ok    %-50s %s\n" "$1" "$2"
  else
    printf "   FAIL  %-50s %s  (expected %s)\n" "$1" "$2" "$3"
    FAIL=1
  fi
}

# check_ne <label> <actual> <must not equal>
check_ne() {
  CHECKS=$((CHECKS + 1))
  if [ "$2" != "$3" ]; then
    printf "   ok    %-50s %s\n" "$1" "$2"
  else
    printf "   FAIL  %-50s %s  (must not be %s)\n" "$1" "$2" "$3"
    FAIL=1
  fi
}

# check_set <label> <actual>   -- fails when empty or literally "null"
check_set() {
  CHECKS=$((CHECKS + 1))
  if [ -n "$2" ] && [ "$2" != "null" ] && [ "$2" != "None" ]; then
    printf "   ok    %-50s %s\n" "$1" "$2"
  else
    printf "   FAIL  %-50s <empty>  (expected a value)\n" "$1"
    FAIL=1
  fi
}

# http <curl args...>  -- status code only, 000 when the host is unreachable
http() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

# finish <script name>
finish() {
  echo
  if [ "$FAIL" = 0 ]; then
    echo "== $1: $CHECKS checks passed =="
  else
    echo "== $1: FAILURES ABOVE ($CHECKS checks run) =="
  fi
  exit "$FAIL"
}

# psql against the application database. Honours the standard PG* variables so
# the same script works locally and against a CI service container.
export PGHOST=${PGHOST:-127.0.0.1}
export PGPORT=${PGPORT:-5432}
export PGUSER=${PGUSER:-relay}
export PGPASSWORD=${PGPASSWORD:-relay_dev}
export PGDATABASE=${PGDATABASE:-relaydesk}
q() { psql -tAqc "$1"; }
