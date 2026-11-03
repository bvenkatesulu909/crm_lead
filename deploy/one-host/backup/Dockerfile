# The nightly backup job of the one-server deployment (ADR 0021, step OH2).
#
# Built on the same PostgreSQL 16 / Alpine as the database, so pg_dump and pg_restore match the
# server. Adds `age` (public-key encryption: the server can encrypt but never decrypt) and the AWS
# command line (any S3-compatible bucket). Runs as the unprivileged "postgres" user.
FROM postgres:16-alpine

RUN apk add --no-cache age aws-cli \
    && mkdir -p /backups /scripts \
    && chown postgres:postgres /backups

COPY backup.sh backup-loop.sh /scripts/
RUN chmod 0555 /scripts/backup.sh /scripts/backup-loop.sh

USER postgres
VOLUME ["/backups"]
# The base image's entrypoint starts a database; this one starts the backup loop instead.
ENTRYPOINT ["/scripts/backup-loop.sh"]
