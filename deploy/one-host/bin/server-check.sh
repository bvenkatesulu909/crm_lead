#!/bin/bash
# Looks at the SERVER (not the code) and tells you what is not yet as the hardening guide asks
# (ADR 0021, step OH3):    cd deploy/one-host && sudo bin/server-check.sh
#
# It only LOOKS. It changes nothing, installs nothing and never prints the contents of .env. Every
# line is PASS, WARN (worth fixing) or FAIL (fix before real data goes in). A check that cannot be
# made on this machine says so instead of passing. It reports every problem and does not stop at the
# first one, so it has no `set -e`.
#
# Written for Ubuntu LTS. First run on a real server on 2026-11-06 (Google Cloud, Ubuntu 24.04);
# that run found the migrate-line bug fixed below.
set -uo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env}"
fails=0
warns=0

pass() { printf '  PASS  %s\n' "$1"; }
warn() { printf '  WARN  %s\n' "$1"; warns=$((warns + 1)); }
fail() { printf '  FAIL  %s\n' "$1"; fails=$((fails + 1)); }
note() { printf '  ----  %s\n' "$1"; }
have() { command -v "$1" > /dev/null 2>&1; }
dc() { docker compose --env-file "$ENV_FILE" "$@"; }

echo "Firewall"
if have ufw; then
  status=$(ufw status 2> /dev/null || true)
  if printf '%s' "$status" | grep -q "Status: active"; then
    pass "ufw is active"
    extra=$(printf '%s\n' "$status" | awk '/ALLOW/ {print $1}' | grep -vE '^(22|80|443)(/tcp)?$|\(v6\)' | sort -u | tr '\n' ' ')
    if [ -z "$extra" ]; then pass "only 22, 80 and 443 are allowed"; else warn "ufw also allows: $extra"; fi
  else
    fail "ufw is installed but not active (or you are not root: run with sudo)"
  fi
else
  warn "ufw is not installed - if your provider has a firewall panel, check ports 22, 80, 443 there"
fi

echo "SSH"
if have sshd; then
  config=$(sshd -T 2> /dev/null || true)
  if [ -z "$config" ]; then
    note "cannot read the SSH settings without root (run with sudo)"
  else
    printf '%s' "$config" | grep -qi '^passwordauthentication no' && pass "PasswordAuthentication is no (keys only)" || fail "PasswordAuthentication is not 'no'"
    printf '%s' "$config" | grep -qiE '^permitrootlogin (no|prohibit-password)' && pass "PermitRootLogin is no / prohibit-password" || fail "PermitRootLogin allows a root password login"
  fi
else
  note "no SSH server found here"
fi

echo "Updates"
if have dpkg && dpkg -s unattended-upgrades > /dev/null 2>&1; then
  pass "unattended-upgrades is installed"
  if grep -qs 'Unattended-Upgrade "1"' /etc/apt/apt.conf.d/20auto-upgrades; then pass "automatic security updates are on"; else warn "automatic security updates are not switched on (20auto-upgrades)"; fi
else
  warn "unattended-upgrades is not installed - security updates will not install themselves"
fi
if [ -e /var/run/reboot-required ]; then warn "the server wants a reboot (a security update is waiting for it)"; else pass "no reboot is waiting"; fi

echo "The .env file"
if [ -f "$ENV_FILE" ]; then
  mode=$(stat -c %a "$ENV_FILE" 2> /dev/null || echo "?")
  owner=$(stat -c %U "$ENV_FILE" 2> /dev/null || echo "?")
  if [ "$mode" = "600" ] || [ "$mode" = "400" ]; then pass ".env is private (mode $mode, owner $owner)"; else fail ".env has mode $mode - it must be 600 (only you can read it)"; fi
  if have git && git check-ignore -q "$ENV_FILE" 2> /dev/null; then pass ".env is ignored by git"; else warn "git does not ignore .env here (or this is not a git checkout)"; fi
  if have python3 && python3 bin/check_env.py "$ENV_FILE" > /dev/null 2>&1; then pass "check_env.py accepts the settings"; else fail "check_env.py refuses the settings - run: python3 bin/check_env.py $ENV_FILE"; fi
else
  fail "there is no $ENV_FILE - run bin/make_env.py"
fi

echo "What is reachable"
if have docker; then
  open=$(docker ps --format '{{.Names}} {{.Ports}}' 2> /dev/null | tr ',' '\n' | grep -E '(0\.0\.0\.0|\[::\]):[0-9]+->' | grep -vE ':(80|443)->' || true)
  if [ -z "$open" ]; then pass "Docker publishes nothing except 80 and 443"; else fail "Docker publishes other ports: $open"; fi
else
  warn "docker is not installed here"
fi
if have ss; then
  listening=$(ss -tlnH 2> /dev/null | awk '{print $4}' | sed 's/.*://' | sort -un | grep -vE '^(22|80|443|53)$' | tr '\n' ' ')
  if [ -z "$listening" ]; then pass "nothing else listens on the network"; else note "other listening ports (check they are local only): $listening"; fi
fi

echo "The services"
if have docker && [ -f "$ENV_FILE" ]; then
  # '|' between the fields: a job without a health check (migrate) has an EMPTY Health, and
  # splitting on spaces would move its exit code one field to the left.
  states=$(dc ps -a --format '{{.Service}}|{{.State}}|{{.Health}}|{{.ExitCode}}' 2> /dev/null || true)
  if [ -z "$states" ]; then
    warn "the stack is not running here"
  else
    bad=$(printf '%s\n' "$states" | awk -F'|' '$1 != "migrate" && ($2 != "running" || $3 == "unhealthy" || $3 == "starting") {print $1}' | tr '\n' ' ')
    if [ -z "$bad" ]; then pass "every service is running and healthy"; else fail "not running or not healthy: $bad"; fi
    printf '%s\n' "$states" | awk -F'|' '$1 == "migrate" && $2 == "exited" && $4 == "0" {found=1} END {exit !found}' && pass "the migration job finished with exit code 0" || fail "the migration job did not finish cleanly"
  fi
  last=$(dc exec -T backup cat /backups/last_success 2> /dev/null | tr -d '\r' || true)
  if [ -n "$last" ]; then
    age=$(($(date -u +%s) - last))
    if [ "$age" -lt 93600 ]; then pass "the last good backup is $((age / 3600)) hours old"; else fail "the last good backup is $((age / 3600)) hours old (last_success)"; fi
    note "a backup only counts once restored: bin/restore-test.sh (about once a month)"
  else
    warn "no good backup yet (last_success is missing)"
  fi
fi

echo "The machine"
free_percent=$(df -P / 2> /dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')
if [ -n "$free_percent" ]; then
  if [ "$free_percent" -lt 80 ]; then pass "disk is ${free_percent}% full"; elif [ "$free_percent" -lt 90 ]; then warn "disk is ${free_percent}% full"; else fail "disk is ${free_percent}% full"; fi
fi
if have free; then
  ram=$(free -m | awk '/^Mem:/ {print $2}')
  swap=$(free -m | awk '/^Swap:/ {print $2}')
  if [ "${ram:-0}" -ge 3800 ]; then pass "memory is ${ram} MB"; else warn "memory is ${ram:-?} MB - the stack wants 4 GB"; fi
  if [ "${swap:-0}" -gt 0 ]; then pass "swap is ${swap} MB"; else warn "no swap - a memory spike can kill the database; the guide adds 2 GB"; fi
fi
if have timedatectl; then
  synced=$(timedatectl show -p NTPSynchronized --value 2> /dev/null || echo "?")
  if [ "$synced" = "yes" ]; then pass "the clock is synchronised"; else warn "the clock is not synchronised (tokens and certificates depend on the time)"; fi
fi

echo
printf '%d FAIL, %d WARN\n' "$fails" "$warns"
[ "$fails" -eq 0 ]
