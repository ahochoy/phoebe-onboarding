#!/usr/bin/env bash
# ci/smoke.sh <site_url> <api_function_url>
#
# Post-deploy smoke test against a live env, through CloudFront. In order:
#   1. GET /api/health via CloudFront is 200 {"status":"ok"} (retried while the
#      distribution and the API cold-start settle).
#   2. GET / is the SPA (HTML with the root element).
#   3. GET /api/status via CloudFront is 200 JSON (passes the origin guard).
#   4. GET /api/status on the function URL directly is 403: only CloudFront
#      carries X-Phoebe-Origin (Review Focus 3, live). /api/health is exempt
#      from the guard, so it cannot be used for this check.
#   5. GET /pr-0/ is not a 404 or 5xx at the router level (no preview exists,
#      so the private bucket answers 403).
# The viewer-address check (CloudFront-Viewer-Address reaching the API) needs
# an endpoint that echoes it; the API has none, so it is reported as skipped
# and checked by hand in Task 9, along with the throttle.
#
# Env: SMOKE_ATTEMPTS (default 10), SMOKE_DELAY seconds (default 6).
set -euo pipefail

fail() {
  echo "SMOKE FAIL: $*" >&2
  exit 1
}

[ $# -eq 2 ] || fail "usage: ci/smoke.sh <site_url> <api_function_url>"
command -v jq >/dev/null || fail "jq is required"
SITE="${1%/}"
FUNCTION_URL="${2%/}"
ATTEMPTS="${SMOKE_ATTEMPTS:-10}"
DELAY="${SMOKE_DELAY:-6}"
BODY="$(mktemp)"
trap 'rm -f "$BODY"' EXIT

# fetch <url>: sets STATUS (000 when unreachable); the body lands in $BODY.
fetch() {
  : >"$BODY"
  STATUS="$(curl -sS -o "$BODY" -w '%{http_code}' --max-time 30 "$1")" || STATUS=000
}

# expect <url> <status> <label>: retries until the status matches.
expect() {
  local i=1
  while :; do
    fetch "$1"
    [ "$STATUS" = "$2" ] && return 0
    [ "$i" -ge "$ATTEMPTS" ] && fail "$3: $1 expected HTTP $2, got $STATUS"
    i=$((i + 1))
    sleep "$DELAY"
  done
}

expect "$SITE/api/health" 200 health
jq -e '.status == "ok"' "$BODY" >/dev/null 2>&1 || fail "health: body is not {\"status\":\"ok\"}"
echo "ok   health via CloudFront"
if jq -e 'has("client_ip")' "$BODY" >/dev/null 2>&1; then
  jq -e '.client_ip | type == "string" and length > 0' "$BODY" >/dev/null ||
    fail "viewer address: API saw no client address"
  echo "ok   viewer address reaches the API"
else
  echo "skip viewer address: the API exposes no echo of CloudFront-Viewer-Address (manual check in Task 9)"
fi

expect "$SITE/" 200 spa
grep -q '<div id="root">' "$BODY" || fail "spa: / is not the app's HTML (no root element)"
echo "ok   SPA at /"

expect "$SITE/api/status" 200 status
jq -e '(.state | type == "string") and (.chat_available | type == "boolean")' "$BODY" >/dev/null 2>&1 ||
  fail "status: /api/status is not the status JSON"
echo "ok   /api/status via CloudFront"

expect "$FUNCTION_URL/api/status" 403 "direct function URL"
echo "ok   direct function URL call is 403"

fetch "$SITE/pr-0/"
case "$STATUS" in
  404 | 000 | 5??) fail "preview route: $SITE/pr-0/ returned $STATUS" ;;
esac
echo "ok   /pr-0/ routed ($STATUS)"

echo "SMOKE OK $SITE"
