#!/bin/sh
# Enables the pgvector extension in the CRM database (ADR 0010, ADR 0021).
#
# Runs once, right after 01-roles-and-databases.sh, as the database administrator: creating an
# extension is an administrator action and the owner and app roles are deliberately not
# administrators. Without it the knowledge-search migration cannot run.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname crm \
  -c "CREATE EXTENSION IF NOT EXISTS vector;"

echo "crm-lead: pgvector extension enabled in the crm database."
