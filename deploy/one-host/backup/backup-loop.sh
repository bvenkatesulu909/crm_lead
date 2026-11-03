#!/bin/sh
# The backup service's main process (ADR 0021, step OH2): one backup every night at 02:30 UTC.
#
# A new server (or one that has not had a good backup for a day) makes one straight away. A failed
# run is repeated every hour until it works; the service then shows as unhealthy in
# `docker compose ps` once 26 hours pass without a good backup.
set -eu

# Given a command (`docker compose run --rm backup /scripts/backup.sh`), run that instead of the
# nightly loop: this script is the image's entrypoint, so it would otherwise swallow the command and
# start a second loop.
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

STATUS=/backups/last_success
DAY=86400
NIGHT=9000 # 02:30 UTC, in seconds since midnight

last_good() {
  cat "$STATUS" 2> /dev/null || echo 0
}

run_until_it_works() {
  until /scripts/backup.sh; do
    echo "backup: trying again in one hour"
    sleep 3600
  done
}

if [ $(($(date -u +%s) - $(last_good))) -gt $((DAY + 3600)) ]; then
  echo "backup: no good backup in the last day - making one now"
  run_until_it_works
fi

while true; do
  now=$(date -u +%s)
  wait=$(((NIGHT - now % DAY + DAY) % DAY))
  [ "$wait" -eq 0 ] && wait=$DAY
  echo "backup: next run in $wait seconds"
  sleep "$wait"
  run_until_it_works
done
