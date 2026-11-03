# Hardening the one server (ADR 0021, step OH3)

**Status: written and rehearsed on a PC, never done on a real server.** There is no server yet. The
commands below are for a fresh **Ubuntu LTS** server and are the usual ones; read each before you run
it, and check the result with `bin/server-check.sh` (last section). Do this **before** real data goes in
and before you say "go live" (CLAUDE.md rule 6). The tick-list is in [deployment.md](deployment.md).

All commands here are **Linux** (bash) on the server. Your own computer stays on Windows CMD.

## What the compose files already do for you

- Only the proxy (Caddy) has open ports, 80 and 443. The database, sign-in service, API and worker are
  reachable only inside Docker's private network.
- Real HTTPS certificates are fetched and renewed automatically; every answer carries the security headers.
- The Keycloak administration console, the master realm, the API documentation and the metrics are not
  reachable from the internet.
- Secrets are random, long, different from each other and never in the repository.
- Containers run with memory limits, restart themselves, have health checks and rotated logs.

What follows is the part that belongs to the **machine**, which the compose files cannot do.

## Firewall

Docker can open ports on its own and **ufw does not filter ports that Docker publishes**. That is why the
compose file publishes only Caddy's 80 and 443. The firewall is the second wall; `server-check.sh` also
checks that Docker publishes nothing else.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

Keep your SSH window open until you have tested a second login: a wrong firewall rule can lock you out.
If your provider has a firewall panel too, allow the same three ports there.

## SSH

Use a key, not a password, and never log in as `root`.

1. Create your own user and give it `sudo` (`adduser you`, `usermod -aG sudo you`), copy your public key
   into `/home/you/.ssh/authorized_keys`, and **test logging in as that user in a second window**.
2. Then in `/etc/ssh/sshd_config.d/10-crm.conf`:

   ```text
   PasswordAuthentication no
   PermitRootLogin no
   ```

3. `sudo sshd -t && sudo systemctl reload ssh` (the test first: a typo would lock you out).

## Updates

```bash
sudo apt update && sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades    # answer Yes
```

Security updates then install by themselves. Some need a reboot (`/var/run/reboot-required`); reboot
in a quiet hour. Everything restarts by itself afterwards (`restart: unless-stopped`).

## Docker

Install Docker from Docker's own repository, as their guide says, and add your user to the `docker`
group only if you accept that this is as powerful as `root`. The CRM's images are rebuilt by
`bin/update.sh`; clean up old ones now and then with `docker image prune`.

## Time

Tokens and certificates depend on the clock. `timedatectl` must show `System clock synchronized: yes`
(Ubuntu does this by default; `sudo timedatectl set-ntp true` if not).

## Swap

A small server with no swap can kill the database when memory spikes. Add 2 GB once:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## Disk

Backups, database and logs all live on one disk. Watch it: `df -h /` should stay under 80 %. Logs are
rotated by Docker (5 files of 10 MB per service), backups older than 14 days are removed by the backup job,
and your provider's snapshot or volume resize is the answer if the database itself grows.

## The .env file

It holds every secret of the server. It must be readable by you only (`chmod 600 .env`; `make_env.py`
already does it), never in git, never in a chat. **Keep a copy in your password manager**: it is the one
file a backup does not contain, and a restored sign-in database keeps its old client secrets.

## DNS

Two names point at the server's address: `api.…` and `login.…`. If your domain host supports it, add a
**CAA** record that allows only Let's Encrypt to issue certificates for them (`0 issue "letsencrypt.org"`),
so nobody else can get one. Turn on two-step login at the domain host and the server provider: whoever
controls them controls the CRM.

## Checking it

```bash
cd deploy/one-host
sudo bin/server-check.sh
```

It prints PASS, WARN or FAIL for the firewall, SSH, updates, the `.env` file, the ports Docker
publishes, the state of the services, the age of the last good backup, disk, memory, swap and the clock. It
changes nothing and never prints a secret. It was written without a server to try it on: treat a
surprising line as a reason to look, not as proof. The backup is only proven by `bin/restore-test.sh`.

Run both after the first setup, after every update that touches the server, and about once a month.

## The rehearsal on a PC

`deploy/one-host/rehearsal/` runs the real files on your PC with a throwaway certificate authority, so the
proxy, HTTPS, sign-in and API can be tried together before any server exists. `rehearsal/smoke.sh` prints
PASS or FAIL for each check. It is **never** for a real server.
