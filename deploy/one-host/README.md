# The CRM on one server (ADR 0021)

**Status: running as STAGING on a real server since 2026-11-06** (Google Cloud, Mumbai; see
`docs/deployment.md`, "First real server"). It is not live: only the owner can open the web app, and
CLAUDE.md rule 6 still holds - nothing is open to real customers until you say "go live" and the
hardening checklist in `docs/deployment.md` is ticked.

One Linux server runs everything except the web app (Netlify), your documents (an S3 bucket) and
your mail (an SMTP provider):

```
 Browser ──► Netlify (web app)                       Browser ──► login.yourcompany.in
              │ server-side calls                                       │
              ▼                                                         ▼
        api.yourcompany.in ───────────►  caddy (ports 80 + 443, automatic HTTPS)
                                              │                         │
                                            api ◄── worker           keycloak
                                              └────► postgres (+pgvector) ◄┘   (no port open)
```

## What you do (the "V only" part) and what I do

| You | Me |
|---|---|
| Rent a Linux server (Ubuntu LTS, **2 vCPU, 4 GB RAM, 40 GB disk** at least) and a domain | Everything in this folder, tested on a PC |
| Point two names at the server's IP address: `api.…` and `login.…` | Commands for you to run |
| Create two **private** buckets (documents, backups) and an SMTP account | I never log in to your server and never see your secrets |
| Create the backup key pair on your own computer (`age-keygen`) | |

The server commands below are **Linux** (bash), because the server is Linux. Commands for your
Windows PC stay CMD, as everywhere else in this project.

## The steps on the server

1. Install Docker (the provider's guide or Docker's own), open only ports 22, 80 and 443 in the
   firewall, log in with an SSH key (not a password).
2. Get the code and go to this folder: `git clone … && cd crm_lead/deploy/one-host`
3. Write the settings (fresh random secrets; the file is readable by you only):

   ```bash
   python3 bin/make_env.py --api-host api.yourcompany.in --login-host login.yourcompany.in \
       --web-url https://crm.yourcompany.in --acme-email you@yourcompany.in \
       --mail-from no-reply@yourcompany.in
   ```

4. Open `.env` in an editor and replace every `CHANGE_ME` with the value from your provider
   (documents bucket, mail account, backup bucket, the **public** backup key that starts with `age1`;
   see "Backups" below for how to make that key on your own computer).
5. Check it: `python3 bin/check_env.py .env` - it lists what is still wrong, by name, never a secret.
6. Start: `docker compose --env-file .env up -d --build`
   (`migrate` brings the database to the latest version first; the API and worker start after it).
7. Look: `docker compose ps` - every service `running`/`healthy`, `migrate` exited with code 0.
8. Put the values into Netlify (Site configuration → Environment variables): see
   `docs/deployment.md`. `CRM_WEB_CLIENT_SECRET` in `.env` is Netlify's `OIDC_CLIENT_SECRET`.
9. Create the first administrator by hand (the realm has no users) - `docs/deployment.md`, step D2.5.
   For that you need the Keycloak administration console, which is closed to the internet; see
   "Administration console" below.

## Documents bucket: files straight from the browser (ADR 0025)

The web app (Netlify) refuses requests of 6 MB or more, so uploads and downloads go between the
browser and the documents bucket directly, through links the API signs for one file and a few
minutes. The bucket stays **private**; it needs two settings, made once from your own PC
(Windows CMD, with the Google Cloud command line signed in to your project):

1. Copy `storage\cors.example.json` to a file of your own and put your web app's address in it
   (for example `https://crm.yourcompany.in`). Only that address may send or fetch files.
2. Apply both files (`lifecycle.json` deletes unfinished uploads in `pending/` after a day):

   ```
   gcloud storage buckets update gs://YOUR-DOCUMENTS-BUCKET --cors-file=my-cors.json
   gcloud storage buckets update gs://YOUR-DOCUMENTS-BUCKET --lifecycle-file=deploy\one-host\storage\lifecycle.json
   ```

3. Check: `gcloud storage buckets describe gs://YOUR-DOCUMENTS-BUCKET --format="json(cors_config,lifecycle_config,public_access_prevention)"`
   shows your address, the `pending/` rule and `"public_access_prevention": "enforced"`.
4. Optional, in Netlify: `FILE_STORE_ORIGIN` = `https://storage.googleapis.com` (the store in the
   browser security policy, report-only for now).

## Administration console

`https://login.…/admin` answers 403 for everybody unless `ADMIN_ALLOWED_IPS` in `.env` lists your
address. To use it: put your own public IP address there (search "what is my IP"), run
`docker compose --env-file .env up -d caddy`, do your work, then set it back to `127.0.0.1` and run the
same command again. List only your own address, only for as long as you need it.

## Backups

Every night at 02:30 UTC the `backup` service dumps both databases (`crm` and `keycloak`) with a
read-only database role, checks that each dump can be read, keeps it on the server for 14 days and
copies an **encrypted** version to your backup bucket. A new server makes its first backup at once. If a
night is missed for more than 26 hours, `docker compose ps` shows the service as `unhealthy`.

**The key pair (once, on your own Windows computer, not on the server).** The server only gets the
*public* half, so even someone who steals the server cannot read the copies in the bucket.

1. Download `age` for Windows from https://github.com/FiloSottile/age/releases (the `windows-amd64` zip).
2. In CMD, in the folder where you unzipped it:

   ```bat
   age-keygen.exe -o backup-key.txt
   ```

   It prints `Public key: age1...`. Put that line's value into `.env` as `BACKUP_AGE_PUBLIC_KEY`.
3. Keep `backup-key.txt` safe and **offline** (a password manager plus a printed copy in a safe place).
   **Without it the encrypted backups can never be opened. Never put it on the server.**

**The bucket.** Use a *second* private bucket, and make its key able to add files but not delete them
(most providers let you restrict an application key). Set the provider's lifecycle rule to expire copies
after, say, 30 days.

**Make a backup now** (for example before something risky):

```bash
docker compose --env-file .env run --rm backup /scripts/backup.sh
```

## Is the backup any good? (the restore test)

A backup you have never restored is a hope. Run this after the first backup and about once a month:

```bash
bin/restore-test.sh
```

It restores the newest dump of each database into a scratch database, compares it with the live one
(migration level, number of tables and policies, row-level security on every tenant table, pgvector, the
sign-in realm), prints `RESTORE TEST PASSED` or `FAILED`, and always removes the scratch database. Tick
"restore tested" in the hardening checklist only when it says PASSED.

## Restoring after a disaster (the server is gone)

1. Rent a new server and set it up as in "The steps on the server", but start only the database:
   `docker compose --env-file .env up -d postgres`. **Use the old `.env` if you kept a copy** (keep one in
   your password manager - it is the one file a backup does not contain): then every secret still matches.
   With a brand-new `.env` it also works, but the restored sign-in database still holds the OLD client
   secrets, so afterwards reset `crm-web` and `crm-user-admin` in the Keycloak console (Clients →
   Credentials) to the values in the new `.env`, or Netlify and the API cannot sign people in.
2. From your own computer, download the newest `crm/...dump.age` and `keycloak/...dump.age` from the
   backup bucket, and decrypt them with your private key (CMD):

   ```bat
   age.exe -d -i backup-key.txt -o crm.dump crm-....dump.age
   age.exe -d -i backup-key.txt -o keycloak.dump keycloak-....dump.age
   ```

3. Copy `crm.dump` and `keycloak.dump` to the server (`scp`), then restore into the empty databases:

   ```bash
   docker compose --env-file .env exec -T postgres pg_restore -U postgres -d crm --clean --if-exists --no-owner < crm.dump
   docker compose --env-file .env exec -T postgres pg_restore -U postgres -d keycloak --clean --if-exists --no-owner < keycloak.dump
   ```

4. Start everything: `docker compose --env-file .env up -d --build`. Delete the plain `.dump` files from
   the server and from your computer when you are done.

## Updating

```bash
git pull && bin/update.sh
```

It checks `.env`, makes a backup, builds the new images, migrates the database, restarts the services and
waits until they are healthy. If the backup, the build or the migration fails, **nothing is restarted** and
the old version keeps running.

## Going back

There is no automatic way back for the *database*: a migration is never edited once applied and is never
undone. If a new version is bad: `git checkout <the previous tag>`, `docker compose --env-file .env up -d --build`
for the old code, and, only if the old code cannot run on the new database, restore the backup that
`update.sh` took in its first step (the steps above).

## Hardening the server, and trying it all on a PC first

- **`docs/one-host-hardening.md`** - firewall, SSH keys, automatic updates, swap, disk, time, the
  `.env` file, DNS; and `sudo bin/server-check.sh`, which looks at the machine and prints PASS / WARN /
  FAIL (it changes nothing and prints no secret). Do this before real data goes in.
- **`rehearsal/`** - the same files started on your PC with a throwaway certificate authority, so the
  proxy, HTTPS, sign-in and API can be tried together before any server exists:

  ```bash
  docker compose --env-file REHEARSAL.env -f docker-compose.yml -f rehearsal/docker-compose.rehearsal.yml up -d --build
  ENV_FILE=REHEARSAL.env rehearsal/smoke.sh
  ```

  `smoke.sh` prints PASS or FAIL for each check. The rehearsal files say NEVER in their first lines:
  they are not for a real server.

## What is deliberately not here

- Monitoring on the server (Prometheus/Grafana need memory a small server lacks). Use a free
  external uptime check on `https://api.yourcompany.in/api/v1/health`.

## Files

| File | What it is |
|---|---|
| `docker-compose.yml` | The services; project name `crm-lead-onehost` (never the development stack's) |
| `Caddyfile` | HTTPS, security headers, the two names, metrics hidden, admin console closed |
| `postgres/init/` | First start only: roles, the `crm` and `keycloak` databases, pgvector |
| `.env.example` | The template; the real `.env` is git-ignored |
| `bin/make_env.py` | Writes `.env` with fresh random secrets |
| `bin/check_env.py` | Refuses a placeholder, weak, repeated or development value |
| `tls.caddy` | The proxy's certificate settings: empty in production (real Let's Encrypt certificates) |
| `backup/Dockerfile` | The backup service's image (PostgreSQL 16 client, `age`, the AWS command line) |
| `backup/backup-loop.sh` | The service's main process: one backup every night at 02:30 UTC, or the command it is given |
| `backup/backup.sh` | One backup: dump, check, encrypt for your public key, upload, size check |
| `bin/restore-test.sh` | Restores the newest backup into a scratch database and compares it |
| `bin/update.sh` | Backup, build, migrate, restart, wait until healthy |
| `bucket/cors.example.json` | The documents bucket's CORS rule (ADR 0025): only the web app's address may send or fetch files |
| `bucket/lifecycle.json` | Deletes unfinished uploads in `pending/` after one day |
| `bin/server-check.sh` | Looks at the machine (firewall, SSH, updates, ports, backups, disk); changes nothing |
| `rehearsal/docker-compose.rehearsal.yml` | **Never for a real server.** Starts the whole stack on a PC |
| `rehearsal/tls.caddy` | **Never for a real server.** A throwaway certificate authority for the rehearsal |
| `rehearsal/smoke.sh` | **Never for a real server.** 22 checks through the proxy over HTTPS |
