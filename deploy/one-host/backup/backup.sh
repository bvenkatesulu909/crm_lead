#!/bin/sh
# One backup run (ADR 0021, step OH2): dump both databases, check the dumps, keep them on the
# server for 14 days, and copy an ENCRYPTED version to a second bucket.
#
#   crm       - the CRM data
#   keycloak  - the sign-in data (users and their credentials)
#
# Safe to run by hand at any time:   docker compose run --rm backup /scripts/backup.sh
#
# Rules this script keeps:
#   * Files are private (umask 077). A dump holds every customer's data.
#   * The copy that leaves the server is encrypted with the owner's PUBLIC key (age). The server can
#     encrypt but never decrypt it: the private key stays on the owner's computer.
#   * A dump is trusted only after pg_restore can read its table of contents, and an upload only after
#     the bucket reports the same size.
#   * Nothing here ever deletes from the bucket (the backup key should not be allowed to). Old
#     local files are removed after 14 days; the provider's lifecycle rule expires old bucket copies.
#   * No secret is printed. A failure stops the script, leaves "last_success" untouched, and exits 1.
set -eu
umask 077

DIR=/backups/local
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
MONTH=$(date -u +%Y/%m)
mkdir -p "$DIR"

SCHEME=https
[ "${BACKUP_S3_SECURE:-true}" = "false" ] && SCHEME=http

AWS_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY"
AWS_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_KEY"
AWS_DEFAULT_REGION="${BACKUP_S3_REGION:-us-east-1}"
# AWS CLI 2.23+ adds a new checksum by default that Google Cloud Storage refuses
# (SignatureDoesNotMatch); "only when required" works with every S3-compatible store.
AWS_REQUEST_CHECKSUM_CALCULATION=when_required
AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION AWS_REQUEST_CHECKSUM_CALCULATION AWS_RESPONSE_CHECKSUM_VALIDATION

s3() {
  aws --endpoint-url "$SCHEME://$BACKUP_S3_ENDPOINT" "$@"
}

fail() {
  echo "backup: FAILED at $1 - the last good backup is unchanged" >&2
  exit 1
}

for db in crm keycloak; do
  file="$DIR/$db-$STAMP.dump"
  pg_dump -d "$db" -Fc -f "$file" || fail "dumping $db"
  pg_restore --list "$file" > /dev/null || fail "reading the $db dump"

  # Encrypted for the owner's public key; the plain dump stays on the server only.
  age -r "$BACKUP_AGE_PUBLIC_KEY" -o "$file.age" "$file" || fail "encrypting $db"
  size=$(wc -c < "$file.age" | tr -d ' ')

  key="$db/$MONTH/$db-$STAMP.dump.age"
  s3 s3 cp --only-show-errors "$file.age" "s3://$BACKUP_S3_BUCKET/$key" || fail "uploading $db"
  remote=$(s3 s3api head-object --bucket "$BACKUP_S3_BUCKET" --key "$key" \
    --query ContentLength --output text) || fail "checking the upload of $db"
  [ "$remote" = "$size" ] || fail "the uploaded $db copy has the wrong size"
  rm -f "$file.age"

  echo "backup: $db ok ($(wc -c < "$file" | tr -d ' ') bytes dumped, $size bytes uploaded encrypted)"
done

# Old local copies go after 14 days (the bucket is handled by the provider's lifecycle rule), and so
# does an encrypted leftover of a run that failed half way (after a day).
find /backups/local \( -name '*.dump' -mtime +14 -o -name '*.age' -mtime +1 \) -delete

# Only now is this a good backup: the health check and the update script look at this file.
date -u +%s > /backups/last_success
echo "backup: done $STAMP"
