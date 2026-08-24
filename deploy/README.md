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
```

Pushing to `preprod` also triggers `.github/workflows/deploy-preprod.yml`, which
runs the test suite and then waits for your approval before running this same
script. The manual route above stays available and is the escape hatch when
Actions is unavailable.

The frontend ships from its own repository. `deploy-web.sh` used to live here,
which meant the Angular deploy logic sat next to code that could not build it;
it now lives at `deploy/deploy-web.sh` in `dental-ordination`, where the same
script is both the manual escape hatch and what that repo's
`deploy-preprod.yml` runs.

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

## Hostnames

Pre-prod is served from `smiletimeclinic.rs`, registered at Loopia:

| | |
|---|---|
| API | `https://preprod.api.smiletimeclinic.rs` |
| Admin | `https://preprod.admin.smiletimeclinic.rs` |

Both are A records pointing at the pre-prod server. The `preprod.` prefix is
there so production can take `api.` and `admin.` on the same domain later
without a second registration.

Changing a hostname is four lines in `/opt/dental/.env` — `API_HOST`,
`ADMIN_HOST`, `ALLOWED_ORIGINS` and `FRONTEND_URL` — followed by
`docker compose --env-file /opt/dental/.env up -d`. Caddy requests the new
certificates on startup, so **point DNS at the server first**: the HTTP-01
challenge resolves the hostname itself, and restarting ahead of DNS spends
Let's Encrypt attempts on a guaranteed failure.

Two things do not live in this file and have to move with it: the Angular
bundle bakes the API hostname in at build time (`environment.preprod.ts` in the
`dental-ordination` repo, then a redeploy), and `deploy-preprod.yml`'s
`environment.url` is a hardcoded link. Until the frontend is rebuilt the admin
app calls a hostname Caddy no longer serves, so cut over and redeploy the
frontend in one sitting.

A box with no DNS at all can still run the stack: use sslip.io, which resolves
the IPv4 encoded in the hostname (`5.161.42.7` -> `api.5-161-42-7.sslip.io`).
That is how pre-prod ran before the domain arrived.

## Troubleshooting

| Symptom | Check |
|---|---|
| Cert never issues | Port 80 open in the Hetzner firewall? DNS resolving to this server? |
| `/health` returns wrong `env` | `APP_ENV` in `/opt/dental/.env` |
| Frontend requests blocked by CORS | `ALLOWED_ORIGINS` must exactly match the admin origin, scheme included |
| Import progress bar jumps 0% → 100% | `flush_interval -1` missing from the Caddyfile proxy block |
| Container restarting | `docker compose --env-file /opt/dental/.env logs --tail=100 api` |
