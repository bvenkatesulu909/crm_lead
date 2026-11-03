#!/bin/bash
# Updates the running CRM to the code in this folder's checkout (ADR 0021, step OH2).
#
#   cd deploy/one-host && git pull && bin/update.sh
#
# Order, on purpose:
#   1. a fresh backup first (if that fails, nothing is changed);
#   2. build the new images (the running version keeps running meanwhile);
#   3. migrate the database as the schema owner (if that fails, nothing is restarted);
#   4. restart the API, worker, sign-in and proxy on the new images and wait until they are healthy.
#
# There is no automatic way back for the DATABASE: a migration is never edited once applied and is not
# undone. Going back = put the previous code back (git checkout <previous tag>), build it, and restore
# the backup of step 1 (see docs/deployment.md, "Going back"). That is why step 1 comes first.
set -euo pipefail
cd "$(dirname "$0")/.."
# On Windows (Git Bash) paths like /backups/... would be rewritten before docker sees them; on Linux this does nothing.
export MSYS_NO_PATHCONV=1

ENV_FILE="${ENV_FILE:-.env}"
dc() { docker compose --env-file "$ENV_FILE" "$@"; }

python3 bin/check_env.py "$ENV_FILE"

echo "1/4 backup"
dc run --rm backup /scripts/backup.sh

echo "2/4 build"
dc build

echo "3/4 migrate"
dc up -d postgres
dc run --rm migrate

echo "4/4 start"
dc up -d
for _ in $(seq 1 60); do
  unhealthy=$(dc ps --format '{{.Service}} {{.Health}}' | grep -E ' (starting|unhealthy)$' || true)
  [ -z "$unhealthy" ] && break
  sleep 5
done
dc ps

if [ -n "$unhealthy" ]; then
  echo "Not everything is healthy yet:"
  echo "$unhealthy"
  echo "Look at: docker compose --env-file .env logs --tail 50 <service>"
  echo "To go back: check out the previous code, run 'docker compose --env-file .env up -d --build'"
  echo "(the database stays at the new migration level; if the old code cannot run on it, restore"
  echo "the backup taken in step 1 - docs/deployment.md, 'Going back')."
  exit 1
fi
echo "Updated."
