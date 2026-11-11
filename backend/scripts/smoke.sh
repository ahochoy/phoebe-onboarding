#!/usr/bin/env bash
# End-to-end smoke test against a running Phoebe stack (see `make stack`).
set -euo pipefail

BASE="${PHOEBE_URL:-http://localhost:8080}"
PASSWORD="${PHOEBE_DEV_PASSWORD:-larkspur-demo}"
JAR="$(mktemp)"
BODY="$(mktemp)"
trap 'rm -f "$JAR" "$BODY"' EXIT

fail() {
  echo "SMOKE FAIL: $*" >&2
  exit 1
}

command -v jq >/dev/null || fail "jq is required"

# req METHOD PATH EXPECTED_STATUS [JSON_BODY]; response body lands in $BODY.
req() {
  local method="$1" path="$2" expect="$3" data="${4:-}" status
  local args=(-sS -o "$BODY" -w '%{http_code}' -X "$method" -b "$JAR" -c "$JAR"
    -H 'X-Phoebe-Csrf: 1' --max-time 30)
  if [ -n "$data" ]; then
    args+=(-H 'Content-Type: application/json' --data "$data")
  fi
  status="$(curl "${args[@]}" "$BASE$path")" || fail "$method $path: could not reach $BASE (is the stack up?)"
  [ "$status" = "$expect" ] || fail "$method $path: expected HTTP $expect, got $status"
}

req GET /api/health 200
[ "$(jq -r .status "$BODY")" = ok ] || fail "health: status is not ok"
echo "health ok"

# Build the login body with jq so the password never appears in argv of curl logs or output.
req POST /api/login 204 "$(jq -cn --arg p "$PASSWORD" '{password: $p}')"
echo "login ok"

req GET /api/me 200
[ "$(jq -r .id "$BODY")" = alex-rivera ] || fail "me: expected id alex-rivera"
echo "me ok"

req GET '/api/tasks?scope=mine' 200
n="$(jq 'length' "$BODY")"
[ "$n" = 14 ] || fail "tasks: expected 14 tasks for scope=mine, got $n"
echo "tasks ok (14)"

req POST /api/search 200 '{"query":"PTO days"}'
jq -e '[.. | strings | select(contains("20 days"))] | length > 0' "$BODY" >/dev/null \
  || fail "search: no passage containing \"20 days\" for query \"PTO days\""
echo "search ok"

req POST /api/reset 204
echo "reset ok"

echo OK
