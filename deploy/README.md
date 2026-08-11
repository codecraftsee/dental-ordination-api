# Deployment runbook — pre-production (Hetzner)

Pre-prod runs the API behind Caddy with automatic HTTPS. Config lives only on
the server; your local `.env` is never read by a deploy.

```
        https://$API_HOST                  https://$ADMIN_HOST
                │                                   │
                └───────────► Caddy :443 ◄──────────┘
                      ┌───────────┴───────────┐
                reverse_proxy             file_server
                      │                        │
               uvicorn :8000              /opt/dental/www
                      │
            Supabase Postgres + Storage
```

Port 8000 is never published to the host — only Caddy can reach the API.

## Server layout

```
/opt/dental/
├── app/     git clone of this repo, branch `preprod`
├── .env     real secrets, chmod 600, never committed
└── www/     Angular bundle (rsync target)
```

## First-time setup

1. Run `bootstrap-server.sh` as root on the fresh box, then follow the manual
   steps it prints (SSH hardening, Hetzner firewall, repo clone, `.env`).
2. Create `/opt/dental/.env` from [`../.env.preprod.example`](../.env.preprod.example).
3. `cd /opt/dental/app && docker compose --env-file /opt/dental/.env up -d --build`

## Routine deploys

Cut a build from `develop`, then ship it:

```bash
git checkout preprod && git pull
git merge --no-ff develop -m "preprod: cut build $(date +%F)"
git push

export DENTAL_SERVER=deploy@<SERVER_IP>
./deploy/deploy-api.sh      # API
./deploy/deploy-web.sh      # Angular (needs a `preprod` config in angular.json)
```

Pushing to `preprod` also triggers `.github/workflows/deploy-preprod.yml`, which
runs the test suite and then waits for your approval before running this same
script. The manual route above stays available and is the escape hatch when
Actions is unavailable.

## Rolling back

Each deploy tags its image with the commit it was built from, and the five most
recent are kept on the server. Rolling back reuses one of them, so there is no
fetch, no `pip install` and no build:

```bash
export DENTAL_SERVER=deploy@<SERVER_IP>
./deploy/rollback-api.sh              # list what is on the server
./deploy/rollback-api.sh 8261283      # switch to that image
```

Two limits, both deliberate and repeated in the script's header: it does not
move the server's git clone, so the next deploy rebuilds from the branch and
undoes the rollback; and it does not touch the database, which matters because
`app/main.py` still runs DDL at startup.

## Local smoke test

Verify the whole stack on your Mac before touching the server. Create an
untracked `.env.docker` (already matched by `.gitignore`'s `.env` rules — check
before committing) with `APP_ENV=preprod`, your Supabase `DATABASE_URL`, and:

```
API_HOST=localhost
ADMIN_HOST=admin.localhost
ACME_EMAIL=you@example.com
WWW_DIR=./www-local
```

Then:

```bash
mkdir -p www-local
ENV_FILE=.env.docker docker compose --env-file .env.docker up -d --build
curl -k https://localhost/health
```

Caddy issues a local self-signed cert for `localhost` (hence `-k`); public
hostnames get real Let's Encrypt certs. Tear down with
`ENV_FILE=.env.docker docker compose --env-file .env.docker down`.

## Switching to a real domain

Two lines in `/opt/dental/.env`:

```diff
-API_HOST=api.5-161-42-7.sslip.io
+API_HOST=api.ourdomain.rs
-ADMIN_HOST=admin.5-161-42-7.sslip.io
+ADMIN_HOST=admin.ourdomain.rs
```

Also update `ALLOWED_ORIGINS` and `FRONTEND_URL` to the new admin host, point
two A records at the server, then `docker compose --env-file /opt/dental/.env up -d`.
Caddy requests the new certificates on startup.

## Troubleshooting

| Symptom | Check |
|---|---|
| Cert never issues | Port 80 open in the Hetzner firewall? DNS resolving to this server? |
| `/health` returns wrong `env` | `APP_ENV` in `/opt/dental/.env` |
| Frontend requests blocked by CORS | `ALLOWED_ORIGINS` must exactly match the admin origin, scheme included |
| Import progress bar jumps 0% → 100% | `flush_interval -1` missing from the Caddyfile proxy block |
| Container restarting | `docker compose --env-file /opt/dental/.env logs --tail=100 api` |
