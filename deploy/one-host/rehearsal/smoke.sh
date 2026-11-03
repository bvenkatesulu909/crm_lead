#!/bin/bash
# REHEARSAL ONLY - NEVER run this against a real server (ADR 0021, step OH3).
#
# Tries the whole stack through the proxy over HTTPS, on a PC, and prints PASS or FAIL for each check:
#
#     ENV_FILE=<rehearsal .env> rehearsal/smoke.sh        (from deploy/one-host, stack already up)
#
# It uses the proxy's throwaway certificate authority and the names in the .env, pointed at this PC.
# Checks that matter most:
#   * the API, the database and pgvector answer through the proxy; protected pages need a token;
#   * the API documentation, the metrics and the Keycloak administration console are NOT reachable;
#   * the security headers are there and uploads above the limit are refused at the edge;
#   * the API can reach the sign-in keys over HTTPS (401 for a bad token, never 503) - and the script
#     proves the check can tell, by taking the API's trust away on purpose and seeing 503;
#   * the administration console opens for an allowed address and closes again.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
# MSYS_NO_PATHCONV: on Windows (Git Bash) keeps container paths like /data/... from being rewritten
# before Docker sees them; it is set for the Docker calls only, because curl needs its file paths
# converted. On Linux it does nothing.
dc() { MSYS_NO_PATHCONV=1 docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f rehearsal/docker-compose.rehearsal.yml "$@"; }
setting() { grep "^$1=" "$ENV_FILE" | cut -d= -f2-; }

API_HOST=$(setting API_HOST)
LOGIN_HOST=$(setting LOGIN_HOST)
HTTPS=8443
HTTP=8080
failures=0

say() { printf '  %-4s %s\n' "$1" "$2"; }
expect() { # expect "what" "wanted" "got"
  if [ "$2" = "$3" ]; then
    say PASS "$1 ($3)"
  else
    say FAIL "$1: wanted $2, got $3"
    failures=$((failures + 1))
  fi
}
contains() { # contains "what" "needle" "text"
  if printf '%s' "$3" | grep -q -- "$2"; then
    say PASS "$1"
  else
    say FAIL "$1: no '$2' in the answer"
    failures=$((failures + 1))
  fi
}

CA=$(mktemp)
BIG=$(mktemp)
trap 'rm -f "$CA" "$BIG"' EXIT

# --ssl-no-revoke: curl on Windows (Schannel) refuses a certificate it cannot look up in a revocation
# list, and a throwaway authority has none. The chain and the host name are still checked; other
# platforms ignore the option.
api() { curl -sS --ssl-no-revoke --max-time 30 --cacert "$CA" --resolve "$API_HOST:$HTTPS:127.0.0.1" "$@"; }
login() { curl -sS --ssl-no-revoke --max-time 30 --cacert "$CA" --resolve "$LOGIN_HOST:$HTTPS:127.0.0.1" "$@"; }
code() { "$1" -o /dev/null -w '%{http_code}' "${@:2}" || true; }

wait_for_proxy() {
  for _ in $(seq 1 40); do
    # Through standard output, so no host file path ever reaches Docker.
    dc exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > "$CA" 2> /dev/null || true
    if [ -s "$CA" ] && [ "$(code api "https://$API_HOST:$HTTPS/api/v1/health" 2> /dev/null)" = "200" ]; then return 0; fi
    sleep 3
  done
  echo "The proxy did not answer in time - is the rehearsal stack up?"
  exit 1
}

wait_for_api() {
  for _ in $(seq 1 40); do
    status=$(MSYS_NO_PATHCONV=1 docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q api)" 2> /dev/null || echo none)
    [ "$status" = "healthy" ] && return 0
    sleep 3
  done
  echo "The API did not become healthy in time."
  exit 1
}

# A token that looks like a JWT but is signed by nobody. The API has to fetch the sign-in service's
# keys to find out that it is not one of them: it can (401, "invalid token") or it cannot (503,
# "authentication service unavailable").
b64() { base64 | tr -d '=\n' | tr '+/' '-_'; }
FAKE_TOKEN="$(printf '{"alg":"RS256","kid":"rehearsal","typ":"JWT"}' | b64).$(printf '{"sub":"x"}' | b64).c2ln"

# Trust only the ordinary public certificate list: the API starts normally but no longer trusts the
# throwaway authority (a missing file would crash it at start instead of showing what we want to see).
break_trust() {
  REHEARSAL_SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt dc up -d --no-deps --force-recreate api > /dev/null 2>&1
  wait_for_api
}
restore_trust() {
  dc up -d --no-deps --force-recreate api > /dev/null 2>&1
  wait_for_api
}

wait_for_proxy

echo "The API through the proxy:"
expect "http redirects to https" "308" "$(code curl -sS --max-time 30 --resolve "$API_HOST:$HTTP:127.0.0.1" "http://$API_HOST:$HTTP/")"
expect "health" "200" "$(code api "https://$API_HOST:$HTTPS/api/v1/health")"
ready=$(api "https://$API_HOST:$HTTPS/api/v1/health/ready")
contains "ready: database ok" '"database":"ok"' "$ready"
contains "ready: pgvector ok" '"vector":"ok"' "$ready"
expect "a protected page needs a token" "401" "$(code api "https://$API_HOST:$HTTPS/api/v1/leads")"
expect "API documentation is off (/docs)" "404" "$(code api "https://$API_HOST:$HTTPS/docs")"
expect "API documentation is off (openapi.json)" "404" "$(code api "https://$API_HOST:$HTTPS/openapi.json")"
expect "metrics are hidden at the edge" "404" "$(code api "https://$API_HOST:$HTTPS/api/v1/internal/metrics")"

echo "Headers and limits:"
headers=$(api -D - -o /dev/null "https://$API_HOST:$HTTPS/api/v1/health")
contains "Strict-Transport-Security is sent" "Strict-Transport-Security" "$headers"
contains "X-Content-Type-Options is sent" "nosniff" "$headers"
if printf '%s' "$headers" | grep -qi '^server:'; then
  say FAIL "the Server header is still sent"
  failures=$((failures + 1))
else
  say PASS "no Server header"
fi
head -c 27000000 /dev/zero > "$BIG"
expect "a 27 MB upload is refused at the edge" "413" "$(code api -X POST --data-binary "@$BIG" "https://$API_HOST:$HTTPS/api/v1/leads")"

echo "Sign-in through the proxy:"
discovery=$(login "https://$LOGIN_HOST:$HTTPS/realms/crm/.well-known/openid-configuration")
contains "the realm answers" '"issuer"' "$discovery"
contains "its issuer is the public https name" "\"https://$LOGIN_HOST/realms/crm\"" "$discovery"
expect "the administration console is closed" "403" "$(code login "https://$LOGIN_HOST:$HTTPS/admin/")"
expect "the master realm is closed" "403" "$(code login "https://$LOGIN_HOST:$HTTPS/realms/master/.well-known/openid-configuration")"

echo "The API reaches the sign-in keys over HTTPS:"
auth=(-H "Authorization: Bearer $FAKE_TOKEN")
expect "a token nobody signed is refused as invalid (not 503)" "401" "$(code api "${auth[@]}" "https://$API_HOST:$HTTPS/api/v1/leads")"
break_trust
expect "WITHOUT trust in the certificate the answer is 503 (the check can tell)" "503" "$(code api "${auth[@]}" "https://$API_HOST:$HTTPS/api/v1/leads")"
restore_trust
expect "trust restored: 401 again" "401" "$(code api "${auth[@]}" "https://$API_HOST:$HTTPS/api/v1/leads")"

echo "The administration console follows the allow-list:"
ADMIN_ALLOWED_IPS="10.0.0.0/8 172.16.0.0/12 192.168.0.0/16" dc up -d --no-deps --force-recreate caddy > /dev/null 2>&1
wait_for_proxy
opened=$(code login "https://$LOGIN_HOST:$HTTPS/admin/")
if [ "$opened" != "403" ] && [ "$opened" != "000" ]; then say PASS "open for an allowed address ($opened)"; else say FAIL "still closed for an allowed address ($opened)"; failures=$((failures + 1)); fi
dc up -d --no-deps --force-recreate caddy > /dev/null 2>&1
wait_for_proxy
expect "closed again after the list is emptied" "403" "$(code login "https://$LOGIN_HOST:$HTTPS/admin/")"

echo
if [ "$failures" -eq 0 ]; then
  echo "SMOKE TEST PASSED"
else
  echo "SMOKE TEST FAILED - $failures check(s) above"
  exit 1
fi
