#!/usr/bin/env bash
# Smoke-test hermes-bff (hermes.datadefi.ai) DFY surfaces.
#
# Usage:
#   export HERMES_BFF_URL=https://hermes.datadefi.ai
#   export HERMES_INGEST_TOKEN=...      # bearer for ingest + snapshot (x402)
#   export API_SERVER_KEY=...           # bearer for chat GUI read routes
#   bash scripts/smoke_test_hermes_bff.sh
#
# Optional: set X402_BFF_URL if x402_intel is on a different host/port.
set -euo pipefail

BASE="${HERMES_BFF_URL:-https://hermes.datadefi.ai}"
X402="${X402_BFF_URL:-${BASE}}"
INGEST="${HERMES_INGEST_TOKEN:-}"
APIKEY="${API_SERVER_KEY:-}"

pass=0
fail=0
skip=0

check() {
  local name="$1" expect="$2" got="$3" body="${4:-}"
  if [[ "$got" == "$expect" ]]; then
    echo "  OK   $name (HTTP $got)"
    pass=$((pass + 1))
  else
    echo "  FAIL $name (expected HTTP $expect, got $got)"
    [[ -n "$body" ]] && echo "       $(echo "$body" | head -c 240)"
    fail=$((fail + 1))
  fi
}

skip_test() {
  echo "  SKIP $1 (set ${2})"
  skip=$((skip + 1))
}

echo "=== hermes-bff smoke test ==="
echo "api_server: ${BASE}"
echo "x402:       ${X402}"
echo

code=$(curl -sS -m 20 -o /tmp/hbff_health.json -w "%{http_code}" "${BASE}/health")
check "GET /health" "200" "$code"
grep -q '"status".*"ok"' /tmp/hbff_health.json && echo "       status ok" || echo "       WARN: unexpected health body"

code=$(curl -sS -m 20 -o /tmp/hbff_body -w "%{http_code}" "${BASE}/v1/dfy/snapshot")
if [[ "$code" == "404" ]]; then
  echo "  INFO GET /v1/dfy/snapshot on api_server -> 404 (expected: route lives on x402_intel, use HERMES_INTERNAL_URL on Railway private network)"
elif [[ "$code" == "401" ]]; then
  check "GET /v1/dfy/snapshot (no auth)" "401" "$code" "$(cat /tmp/hbff_body)"
else
  check "GET /v1/dfy/snapshot (no auth)" "401" "$code" "$(cat /tmp/hbff_body)"
fi

if [[ -n "$INGEST" ]]; then
  code=$(curl -sS -m 20 -o /tmp/hbff_body -w "%{http_code}" \
    -H "Authorization: Bearer ${INGEST}" "${BASE}/v1/dfy/snapshot")
  if [[ "$code" == "200" ]]; then
    check "GET /v1/dfy/snapshot (api_server)" "200" "$code"
  elif [[ "$code" == "404" ]]; then
    echo "  INFO snapshot not on api_server (404) — trying x402_intel…"
    code=$(curl -sS -m 20 -o /tmp/hbff_body -w "%{http_code}" \
      -H "Authorization: Bearer ${INGEST}" "${X402}/v1/dfy/snapshot")
    check "GET /v1/dfy/snapshot (x402)" "200" "$code" "$(head -c 120 /tmp/hbff_body)"
    if [[ "$code" == "200" ]]; then
      python3 - <<'PY' /tmp/hbff_body
import json, sys
d = json.load(open(sys.argv[1]))
keys = sorted((d.get("mechanisms") or d).keys() if isinstance(d, dict) else [])
print("       snapshot top-level keys:", keys[:12])
PY
    fi
  else
    check "GET /v1/dfy/snapshot (authenticated)" "200" "$code" "$(cat /tmp/hbff_body)"
  fi

  code=$(curl -sS -m 20 -o /tmp/hbff_body -w "%{http_code}" -X POST \
    -H "Authorization: Bearer ${INGEST}" -H "Content-Type: application/json" \
    -d '{"kind":"runner","data":{"strategy_class":"smoke_test"},"bot":"smoke"}' \
    "${BASE}/v1/dfy/ingest")
  check "POST /v1/dfy/ingest (smoke event)" "200" "$code" "$(cat /tmp/hbff_body)"
else
  skip_test "authenticated snapshot + ingest" "HERMES_INGEST_TOKEN"
fi

if [[ -n "$APIKEY" ]]; then
  auth=(-H "Authorization: Bearer ${APIKEY}")
  for path in /v1/dfy/mechanisms /v1/dfy/signals /v1/dfy/activity /v1/dfy/freshness; do
    code=$(curl -sS -m 20 -o /tmp/hbff_body -w "%{http_code}" "${auth[@]}" "${BASE}${path}")
    check "GET ${path}" "200" "$code"
    if [[ "$code" == "200" ]]; then
      python3 - <<'PY' /tmp/hbff_body "$path"
import json, sys
path = sys.argv[2]
d = json.load(open(sys.argv[1]))
if "view" in d:
    print(f"       posture projection view={d.get('view')!r}")
elif "deprecated" in d:
    print(f"       legacy alias deprecated={d.get('deprecated')!r}")
elif "open_trades" in d or "latest_indicators" in str(d):
    print("       WARN: raw Tier-C mechanisms payload (DFY_ORACLE_ENABLED may be on)")
elif "items" in d and d["items"]:
    first = d["items"][0]
    if any(k in str(first) for k in ("digest", "values", "&-", "enter_")):
        print("       WARN: raw signal/activity rows")
    else:
        print(f"       items[0] keys: {sorted(first.keys())[:8]}")
else:
    print(f"       keys: {sorted(d.keys())[:10]}")
PY
    fi
  done
  for path in /v1/dfy/regime /v1/dfy/posture; do
    code=$(curl -sS -m 20 -o /tmp/hbff_body -w "%{http_code}" "${auth[@]}" "${BASE}${path}")
    if [[ "$code" == "200" ]]; then
      check "GET ${path} (new Tier-A route)" "200" "$code"
    elif [[ "$code" == "404" ]]; then
      echo "  INFO ${path} -> 404 (deploy may predate posture-only x402 routes on api_server)"
    else
      check "GET ${path}" "200" "$code" "$(cat /tmp/hbff_body)"
    fi
  done
else
  skip_test "authenticated read routes" "API_SERVER_KEY"
fi

echo
echo "=== summary: ${pass} passed, ${fail} failed, ${skip} skipped ==="
[[ "$fail" -eq 0 ]]
