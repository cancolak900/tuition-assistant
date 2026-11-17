#!/usr/bin/env bash
# Gateway / end-to-end smoke test (docs/03_Test_Plan.md §5, E-01..E-06).
#
# Usage:
#   bash scripts/smoke.sh                          # local stack: http://localhost
#   bash scripts/smoke.sh http://<elastic-ip>      # AWS deployment
#   bash scripts/smoke.sh http://localhost | tee docs/evidence/smoke-local.log
#
# Needs only bash and curl. Exit code 0 when every check passes.
# Safe to run many times a day: the rate-limit check reads X-RateLimit-Remaining-Day and skips
# students whose daily quota is already used, so it never depends on a fresh counter.

set -u

BASE_URL="${1:-${BASE_URL:-http://localhost}}"
BASE_URL="${BASE_URL%/}"
API="$BASE_URL/api/v1"
USER_NAME="${SMOKE_USER:-s1001}"
USER_PASS="${SMOKE_PASS:-Pass1001!}"
OWN_STUDENT="${SMOKE_OWN_STUDENT:-S1001}"

HOST="$(echo "$BASE_URL" | sed -E 's#^[a-z]+://##; s#[:/].*$##')"
case "$HOST" in
  localhost|127.0.0.1) BACKEND_PORTS="${SMOKE_BACKEND_PORTS:-8000 8200}" ;;   # locally Postgres/MCP are bound to 127.0.0.1 for debugging
  *)                   BACKEND_PORTS="${SMOKE_BACKEND_PORTS:-8000 8100 8200 5432}" ;;
esac

PASS=0
FAIL=0
BODY="$(mktemp)"
HEADERS="$(mktemp)"
trap 'rm -f "$BODY" "$HEADERS"' EXIT

# request <curl args...>  -> sets CODE, fills $BODY and $HEADERS
request() { CODE="$(curl -sS -o "$BODY" -D "$HEADERS" -w '%{http_code}' --max-time 10 "$@" 2>/dev/null || echo 000)"; }
header() { grep -i "^$1:" "$HEADERS" | head -1 | cut -d' ' -f2- | tr -d '\r'; }
body_short() { tr -d '\n' < "$BODY" | tr -s ' ' | cut -c1-110; }

check() {  # check <id> <description> <expected> <actual> [detail]
  local id="$1" desc="$2" want="$3" got="$4" detail="${5:-}"
  if [ "$want" = "$got" ]; then
    PASS=$((PASS + 1)); printf '  PASS  %-5s %-55s expected %-4s got %-4s %s\n' "$id" "$desc" "$want" "$got" "$detail"
  else
    FAIL=$((FAIL + 1)); printf '  FAIL  %-5s %-55s expected %-4s got %-4s %s\n' "$id" "$desc" "$want" "$got" "$detail"
  fi
}

echo "Smoke test against $BASE_URL  ($(date -u '+%Y-%m-%d %H:%M:%S UTC'))"
echo

# ---------------------------------------------------------------------------------------------
echo "E-01 / E-02  Protected route through the gateway"
request "$API/banking/tuition/$OWN_STUDENT"
check E-01 "GET /banking/tuition/$OWN_STUDENT without a token" 401 "$CODE" "$(body_short)"

request -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  --data "{\"username\":\"$USER_NAME\",\"password\":\"$USER_PASS\"}"
TOKEN="$(grep -o '"accessToken":"[^"]*"' "$BODY" | cut -d'"' -f4)"
check login "POST /auth/login as $USER_NAME" 200 "$CODE"

request "$API/banking/tuition/$OWN_STUDENT" -H "Authorization: Bearer $TOKEN"
check E-02 "GET /banking/tuition/$OWN_STUDENT with a token" 200 "$CODE" "balance=$(grep -o '"balance":"[^"]*"' "$BODY" | head -1 | cut -d'"' -f4)"

request "$API/banking/tuition/$OWN_STUDENT" -H "Authorization: Bearer ${TOKEN%?}x"
check extra "same route with a forged token (bad signature)" 401 "$CODE" "$(body_short)"
echo

# ---------------------------------------------------------------------------------------------
echo "E-03 / E-04  Mobile query: 3 calls per student per day, keyed by student number"
LIMITED=""
for n in $(seq 1004 1030); do   # extra seed students only: the demo logins S1001-S1003 keep their quota
  s="S$n"
  request "$API/mobile/tuition/$s"
  if [ "$CODE" = "200" ]; then
    remaining="$(header X-RateLimit-Remaining-Day)"; limit="$(header X-RateLimit-Limit-Day)"
    calls=1
    while [ "${remaining:-0}" -gt 0 ]; do
      request "$API/mobile/tuition/$s"; calls=$((calls + 1))
      [ "$CODE" = "200" ] || break
      remaining="$(header X-RateLimit-Remaining-Day)"
    done
    request "$API/mobile/tuition/$s"; calls=$((calls + 1))
    check E-03 "GET /mobile/tuition/$s after the daily quota ($limit/day)" 429 "$CODE" "(call $calls today) $(body_short)"
    LIMITED="$s"
    break
  fi
done
[ -n "$LIMITED" ] || check E-03 "found a student with quota left (S1004-S1030)" 200 "none"

OTHER=""
for n in $(seq 1030 -1 1004); do
  s="S$n"
  [ "$s" = "$LIMITED" ] && continue
  request "$API/mobile/tuition/$s"
  if [ "$CODE" = "200" ]; then OTHER="$s"; break; fi
done
check E-04 "GET /mobile/tuition/${OTHER:-?} (separate counter)" 200 "${OTHER:+200}" "remaining today=$(header X-RateLimit-Remaining-Day)"

request "$API/mobile/tuition/$LIMITED" -H "X-RateLimit-Student: SOMEONE-ELSE"
check extra "spoofed X-RateLimit-Student header cannot bypass the limit" 429 "$CODE"
echo

# ---------------------------------------------------------------------------------------------
echo "E-05  Backend services are not reachable directly"
for port in $BACKEND_PORTS; do
  got="$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 "http://$HOST:$port/" 2>/dev/null)"
  [ "$got" = "000" ] && got="refused" || got="open"
  check E-05 "direct connection to $HOST:$port" refused "$got"
done
echo

# ---------------------------------------------------------------------------------------------
echo "E-06  Documentation and correlation id through the gateway"
request "$API/docs"
check E-06 "GET /api/v1/docs (Swagger UI)" 200 "$CODE"
request "$API/openapi.json"
check extra "GET /api/v1/openapi.json" 200 "$CODE"
request "$API/health"
rid="$(header X-Request-ID)"
check extra "X-Request-ID header returned by the gateway" yes "$([ -n "$rid" ] && echo yes || echo no)" "$rid"
echo

echo "Result: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
