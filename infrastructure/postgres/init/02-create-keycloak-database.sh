#!/bin/sh
# Creates the database Keycloak keeps its data in (users, sessions, realm settings), so users
# created through the CRM survive container restarts (ADR 0004).
#
# Runs automatically on the first start of an EMPTY data volume. For an existing volume, run it
# once by hand (see docs/auth.md, "Keycloak database"); it is safe to run more than once.
#
# The keycloak role owns only the keycloak database and has no access to crm or crm_test.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v kc="$KEYCLOAK_DB_USER" -v kc_password="$KEYCLOAK_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'kc', :'kc_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'kc') \gexec
SELECT format('CREATE DATABASE keycloak OWNER %I', :'kc')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'keycloak') \gexec
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE keycloak TO :"kc";
SQL

echo "crm-lead: keycloak database ready."
