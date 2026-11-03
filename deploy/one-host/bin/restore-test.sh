#!/bin/bash
# Proves that the newest local backup can really be restored (ADR 0021, step OH2).
#
#   cd deploy/one-host && bin/restore-test.sh
#
# A backup you have never restored is a hope, not a backup. This restores the newest dump of each
# database into a SCRATCH database, compares it with the live one, prints PASS or FAIL, and always
# removes the scratch database again. The live databases are only read. Run it after the first backup
# and then about once a month, and tick "restore tested" in the hardening checklist only when it says PASS.
#
# What is compared (live database vs. the restored copy):
#   * the migration level (alembic_version), the number of tables and of row-level-security policies
#   * every table with a tenant_id still has row-level security ENABLED and FORCED
#   * pgvector is installed, and the sign-in database still holds its realm
# The row counts of the main tables are printed for you to look at (a dump from last night is allowed to
# be a little behind the live data).
set -euo pipefail
cd "$(dirname "$0")/.."
# On Windows (Git Bash) paths like /backups/... would be rewritten before docker sees them; on Linux this does nothing.
export MSYS_NO_PATHCONV=1

ENV_FILE="${ENV_FILE:-.env}"
dc() { docker compose --env-file "$ENV_FILE" "$@"; }
psql_live() { dc exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -At "$@"; }

scratch_crm="restore_check_crm_$(date -u +%s)"
scratch_kc="restore_check_kc_$(date -u +%s)"
failures=0

cleanup() {
  dc exec -T postgres dropdb -U postgres --if-exists "$scratch_crm" > /dev/null 2>&1 || true
  dc exec -T postgres dropdb -U postgres --if-exists "$scratch_kc" > /dev/null 2>&1 || true
}
trap cleanup EXIT

check() { # check "what" "live value" "restored value"
  if [ "$2" = "$3" ]; then
    echo "  PASS  $1 ($2)"
  else
    echo "  FAIL  $1: live=$2 restored=$3"
    failures=$((failures + 1))
  fi
}

latest() { # the newest local dump of a database
  dc exec -T backup sh -c "ls -1t /backups/local/$1-*.dump 2>/dev/null | head -1" | tr -d '\r'
}

restore() { # restore "dump file" "scratch database"
  dc exec -T postgres createdb -U postgres "$2"
  dc exec -T backup cat "$1" | dc exec -T postgres pg_restore -U postgres -d "$2" --no-owner --exit-on-error
}

for db in crm keycloak; do
  file=$(latest "$db")
  if [ -z "$file" ]; then
    echo "FAIL  no local backup of $db yet - run: docker compose --env-file .env run --rm backup /scripts/backup.sh"
    exit 1
  fi
  echo "Restoring $file"
done

crm_file=$(latest crm)
kc_file=$(latest keycloak)
restore "$crm_file" "$scratch_crm"
restore "$kc_file" "$scratch_kc"

echo "The CRM database:"
sql_version="select version_num from alembic_version"
sql_tables="select count(*) from pg_tables where schemaname = 'public'"
sql_policies="select count(*) from pg_policies"
sql_unsafe="select count(*) from pg_class c join pg_attribute a on a.attrelid = c.oid and a.attname = 'tenant_id' and not a.attisdropped where c.relkind = 'r' and c.relnamespace = 'public'::regnamespace and not (c.relrowsecurity and c.relforcerowsecurity)"
sql_vector="select count(*) from pg_extension where extname = 'vector'"
check "migration level" "$(psql_live -d crm -c "$sql_version")" "$(psql_live -d "$scratch_crm" -c "$sql_version")"
check "tables" "$(psql_live -d crm -c "$sql_tables")" "$(psql_live -d "$scratch_crm" -c "$sql_tables")"
check "row-level-security policies" "$(psql_live -d crm -c "$sql_policies")" "$(psql_live -d "$scratch_crm" -c "$sql_policies")"
check "tenant tables without enabled+forced row-level security" "0" "$(psql_live -d "$scratch_crm" -c "$sql_unsafe")"
check "pgvector installed" "1" "$(psql_live -d "$scratch_crm" -c "$sql_vector")"

echo "The sign-in database:"
sql_realms="select count(*) from realm"
check "realms" "$(psql_live -d keycloak -c "$sql_realms")" "$(psql_live -d "$scratch_kc" -c "$sql_realms")"

echo "Rows, live -> restored (for you to look at):"
for table in tenants users leads accounts contacts audit_log; do
  live=$(psql_live -d crm -c "select count(*) from $table" 2> /dev/null || echo "-")
  back=$(psql_live -d "$scratch_crm" -c "select count(*) from $table" 2> /dev/null || echo "-")
  echo "  $table: $live -> $back"
done

echo
if [ "$failures" -eq 0 ]; then
  echo "RESTORE TEST PASSED - the backup $crm_file can be restored."
else
  echo "RESTORE TEST FAILED - $failures check(s) above. Do not rely on this backup."
  exit 1
fi
