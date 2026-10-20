#!/bin/sh
# Enables the pgvector extension (ADR 0010).
#
# Runs once, on the FIRST start of an empty data volume, as the PostgreSQL superuser:
# CREATE EXTENSION is a superuser action and our migration/app roles are deliberately not
# superusers.
#
# Existing volumes do NOT re-run this file. For them use the one-off command in
# docs/rag-runbook.md (the extension is created by hand once).
set -eu

for db in crm crm_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" \
    -c "CREATE EXTENSION IF NOT EXISTS vector;"
done

echo "crm-lead: pgvector extension enabled in crm and crm_test."
