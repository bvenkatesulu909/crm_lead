#!/bin/sh
# Runs once, the first time the PostgreSQL container starts with an empty data volume.
#
# Creates two login roles and two databases:
#   owner role  - owns the tables; used only by Alembic migrations.
#   app role    - used by the running API; may read/write rows but cannot create, alter
#                 or drop tables. Because it is not the table owner, PostgreSQL Row-Level
#                 Security (added in the tenancy phase) will apply to it.
#   crm         - development database.
#   crm_test    - database used by automated tests (tests may wipe it).
#
# Passwords come from environment variables (infrastructure/.env), never from this file.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner="$CRM_DB_OWNER_USER" -v owner_password="$CRM_DB_OWNER_PASSWORD" \
  -v app="$CRM_DB_APP_USER" -v app_password="$CRM_DB_APP_PASSWORD" <<'SQL'
CREATE ROLE :"owner" LOGIN PASSWORD :'owner_password';
CREATE ROLE :"app" LOGIN PASSWORD :'app_password';
CREATE DATABASE crm OWNER :"owner";
CREATE DATABASE crm_test OWNER :"owner";
SQL

for db in crm crm_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" \
    -v db="$db" -v owner="$CRM_DB_OWNER_USER" -v app="$CRM_DB_APP_USER" <<'SQL'
-- Nobody may connect unless granted explicitly.
REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"db" TO :"app";

-- The owner role owns the schema; the app role may only use objects in it.
ALTER SCHEMA public OWNER TO :"owner";
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app";

-- Every table/sequence the owner creates later (via migrations) is automatically
-- readable and writable by the app role - but never alterable or droppable.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app";
SQL
done

echo "crm-lead: roles and databases created."
