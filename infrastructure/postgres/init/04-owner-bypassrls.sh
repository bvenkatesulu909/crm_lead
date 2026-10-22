#!/bin/sh
# Owner bootstrap for RLS P1 (ADR 0009): migrations and test fixtures run as crm_owner and need
# to bypass row-level security. The runtime API/worker role crm_app must NEVER have BYPASSRLS.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "${POSTGRES_DB:-postgres}" <<'SQL'
ALTER ROLE crm_owner BYPASSRLS;
SQL

echo "crm_owner has BYPASSRLS (migration/test setup only); crm_app remains restricted."
