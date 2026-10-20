# pgvector setup and backup runbook (R0, ADR 0010)

Commands are for **Windows CMD**, run from `E:\crm-lead`.

## 1. Back up before changing the image

```bat
cd E:\crm-lead\infrastructure
```

```bat
docker compose exec -T postgres sh -lc "pg_dump -U \"$POSTGRES_USER\" -Fc -f /tmp/crm-before-pgvector.dump crm"
```

```bat
docker compose cp postgres:/tmp/crm-before-pgvector.dump .\backups\crm-before-pgvector.dump
```

The `backups` folder is git-ignored. Keep the dump until the new image has passed the checks.

## 2. One-off command for an EXISTING data volume

Init scripts only run on an empty volume. After switching to the pgvector image, create the
extension once as the superuser:

```bat
docker compose exec -T postgres sh -lc "psql -U \"$POSTGRES_USER\" -d crm -c 'CREATE EXTENSION IF NOT EXISTS vector;'"
```

```bat
docker compose exec -T postgres sh -lc "psql -U \"$POSTGRES_USER\" -d crm_test -c 'CREATE EXTENSION IF NOT EXISTS vector;'"
```

New volumes get this automatically from `postgres/init/03-enable-pgvector.sh`.

## 3. Verify

```bat
docker compose exec -T postgres sh -lc "psql -U \"$POSTGRES_USER\" -d crm -tAc \"select extversion from pg_extension where extname='vector'\""
```

Expected output: the pgvector version (for this project: `0.8.7`). Repeat with `-d crm_test`.

## 4. Restore if something goes wrong

Stop the API and worker first, then (destructive - only when needed):

```bat
docker compose exec -T postgres sh -lc "pg_restore -U \"$POSTGRES_USER\" -d crm --clean --if-exists /tmp/crm-before-pgvector.dump"
```

Copy the dump back into the container first if it is only on the host:

```bat
docker compose cp .\backups\crm-before-pgvector.dump postgres:/tmp/crm-before-pgvector.dump
```

## 5. Tests and CI

- The backend tests need the extension in `crm_test` (done above).
- CI still uses `postgres:16`; when R0 is complete it must use the same pgvector image so tests
  can create `vector` columns.
