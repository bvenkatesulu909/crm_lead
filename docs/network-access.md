# Opening the CRM to other devices on your network

By default the CRM answers only on this computer (`http://localhost:3000`). **Network mode** lets
phones and laptops on the **same Wi-Fi / network** open it too. Nothing goes to the cloud or the
internet; people on your network can see the login page but still need a CRM account.

## Turn it on (Windows CMD)

1. Find this computer's address: run `ipconfig` and read **IPv4 Address** of your Wi-Fi
   adapter (it looks like `192.168.x.x`).
2. In the project folder:

```
cd backend
.venv\Scripts\activate
python -m scripts.network_mode on <PC-address>
```

It tells Keycloak (the sign-in service) the new address, backs up and updates the settings
files, and restarts Keycloak. Then **restart the API** and start the web app for the network:

```
cd frontend
npm run dev:network
```

3. Open **http://<PC-address>:3000** on this computer or any device on the same network.
   Sign in with the same accounts as before.

## Windows firewall (run CMD **as administrator**, once)

Allow the two ports, **only from your own network** (`localsubnet`):

```
netsh advfirewall firewall add rule name="crm-lead web 3000" dir=in action=allow protocol=TCP localport=3000 remoteip=localsubnet profile=any
netsh advfirewall firewall add rule name="crm-lead login 9080" dir=in action=allow protocol=TCP localport=9080 remoteip=localsubnet profile=any
```

Remove them again with:

```
netsh advfirewall firewall delete rule name="crm-lead web 3000"
netsh advfirewall firewall delete rule name="crm-lead login 9080"
```

(`profile=any` is used because Windows often marks home Wi-Fi as "Public".) The API (port 8000),
the database and the other services stay private to this computer: the web app talks to them.

## Turn it off (back to this computer only)

```
cd backend
.venv\Scripts\activate
python -m scripts.network_mode off
```

Then restart the API and use `npm run dev` and `http://localhost:3000` again.
`python -m scripts.network_mode status` shows which mode is active.

## Good to know

- **The address must stay the same.** If your router gives the PC a new address, run
  `network_mode off`, then `on <new address>`. Ask the router to reserve the address for this PC
  to avoid it.
- **End-to-end tests (Playwright) need local mode** (`network_mode off`): they expect
  `localhost`.
- **The connection is plain HTTP.** That is fine inside a private network for testing, but
  passwords cross the network unencrypted. Don't use network mode on public Wi-Fi, and never
  forward these ports on your router to the internet.
- Invitation and password-reset e-mails (caught by Mailpit) contain links with the network
  address while network mode is on.
- Test users are fictional accounts with the shared development password from
  `infrastructure\.env`; anyone on your network who knows it can sign in. Keep network mode for
  demos and turn it off afterwards.

## How it works

The sign-in service signs every token with its own web address (the "issuer"), and the API, the
web app and Keycloak's list of allowed return addresses must all agree on it. So network mode
changes them together:

| Where | Setting |
|---|---|
| `infrastructure\.env` | `KEYCLOAK_PUBLIC_URL`, `KEYCLOAK_BIND=0.0.0.0` (docker-compose reads them) |
| `backend\.env` | `CRM_OIDC_ISSUER`, `CRM_WEB_APP_URL`, `CRM_CORS_ALLOWED_ORIGINS` |
| `frontend\.env.local` | `APP_BASE_URL`, `OIDC_ISSUER`, `NETWORK_HOST` (lets the dev server accept that address) |
| Keycloak client `crm-web` | extra redirect URI, web origin and post-logout address |

`off` restores the three files from `*.network-backup` copies and removes the extra addresses.
