#!/bin/sh
# Runs once, the first time the PostgreSQL container starts with an EMPTY data volume (ADR 0021).
#
# Creates what the production CRM needs and nothing else (no test database, no development data):
#   crm_owner  - owns the tables; used only by the one-shot migration job.
#   crm_app    - used by the API and the worker; may read and write rows but cannot create, alter
#                or drop tables. Because it does not own the tables, row-level security applies to
#                it, and it must NEVER have BYPASSRLS.
#   crm_backup - used by the nightly backup: reads every row (it must, row-level security is forced)
#                and changes nothing; it cannot create databases or roles.
#   crm        - the CRM database (pgvector enabled).
#   keycloak   - the sign-in database, owned by its own role.
#
# Every password comes from the environment (the server's .env), never from this file.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner="crm_owner" -v owner_password="$CRM_DB_OWNER_PASSWORD" \
  -v app="crm_app" -v app_password="$CRM_DB_APP_PASSWORD" \
  -v kc="keycloak" -v kc_password="$KEYCLOAK_DB_PASSWORD" \
  -v backup="crm_backup" -v backup_password="$CRM_DB_BACKUP_PASSWORD" <<'SQL'
CREATE ROLE :"owner" LOGIN PASSWORD :'owner_password';
CREATE ROLE :"app" LOGIN PASSWORD :'app_password';
CREATE ROLE :"kc" LOGIN PASSWORD :'kc_password';
CREATE ROLE :"backup" LOGIN PASSWORD :'backup_password';
CREATE DATABASE crm OWNER :"owner";
CREATE DATABASE keycloak OWNER :"kc";
-- Migrations run as the owner and have to see every row; the API never does.
ALTER ROLE :"owner" BYPASSRLS;
-- pg_dump has to see every row; the built-in role below gives it read access and nothing more.
ALTER ROLE :"backup" BYPASSRLS;
GRANT pg_read_all_data TO :"backup";
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname crm \
  -v owner="crm_owner" -v app="crm_app" -v backup="crm_backup" <<'SQL'
-- Nobody may connect unless granted explicitly.
REVOKE ALL ON DATABASE crm FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE crm TO :"app";
GRANT CONNECT ON DATABASE crm TO :"backup";

-- The owner role owns the schema; the app role may only use objects in it.
ALTER SCHEMA public OWNER TO :"owner";
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app";

-- Every table and sequence the owner creates later (the migrations) is automatically readable and
-- writable by the app role - but never alterable or droppable by it.
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO :"app";
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname keycloak \
  -v kc="keycloak" -v backup="crm_backup" <<'SQL'
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE keycloak TO :"kc";
GRANT CONNECT ON DATABASE keycloak TO :"backup";
SQL

echo "crm-lead: roles and the databases crm and keycloak created."
