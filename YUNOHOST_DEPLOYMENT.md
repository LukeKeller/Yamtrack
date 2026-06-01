# Deploying Stackwise on YunoHost

Stackwise ships as a **single, self-contained YunoHost package**. The
application code (`src/`) lives in this repo alongside the YunoHost packaging
files (`manifest.toml`, `scripts/`, `conf/`), and the install/upgrade scripts
copy that code into place. There is no separate packaging repo, no source
tarball pin, and no fork-bumping dance — what you install is exactly what's in
this repo at the ref you point YunoHost at.

- **YunoHost app id:** `stackwise`
- **Default install path:** `/stackwise`
- **Repo:** <https://github.com/LukeKeller/stackwise_ynh>
- **Services:** `stackwise`, `stackwise-celery`, `stackwise-celery-beat`

This guide covers a native YunoHost install and a Docker-Compose-from-source
path for fast iteration.

---

## Prerequisites

- A YunoHost server (≥ 12.1.39) with a domain or subdomain you control.
- SSH/admin access.
- A subdomain reserved for Stackwise — e.g., `stackwise.example.com` — added
  under **YunoHost → Domains**.
- API keys for the providers you want to use. At minimum: `TMDB_API`,
  `MAL_API`, `IGDB_ID` + `IGDB_SECRET`, `HARDCOVER_API`. See
  `src/config/settings.py` for the full list and their defaults.

---

## Path A: Native YunoHost install (recommended)

Install directly from the repo:

```bash
sudo yunohost app install https://github.com/LukeKeller/stackwise_ynh
```

The installer asks for:

| Question | Notes |
|---|---|
| `domain` | The (sub)domain you reserved. |
| `path` | Default `/stackwise`. Use `/` if you want it at the domain root. |
| `init_main_permission` | `all_users` lets every YunoHost account in. |
| `admin` | Pick the YunoHost user that becomes the Stackwise admin. |
| `enable_sso` | If `true`, YunoHost wires up Dex OIDC SSO. If you'd rather use Stackwise's local accounts, answer `false`. |

The package handles cert provisioning, nginx, systemd units (`stackwise`,
`stackwise-celery`, `stackwise-celery-beat`), and a non-Docker install of the
app. It provisions PostgreSQL and Redis via `apt` — both are required. After
install, browse to `https://<your-domain>/<path>` and log in.

### Upgrading

Because the app code is bundled in the package, upgrading just means pointing
YunoHost at a newer ref of the repo:

```bash
sudo yunohost app upgrade stackwise -u https://github.com/LukeKeller/stackwise_ynh
```

`scripts/upgrade` re-copies the bundled `src/` into place and runs migrations.
There is no separate source pin to bump.

If install or upgrade fails, check `/var/log/yunohost/operations/` and the
app's log under **YunoHost admin → Apps → Stackwise → Logs**.

### Migrating from an old `yamtrack_fork` install

The previous packaging used a different YunoHost id (`yamtrack_fork`, default
path `/yamtrack-fork`). Because YunoHost keys apps by id, moving to `stackwise`
is **a fresh install plus a PostgreSQL data migration**, not an in-place
upgrade — the two are distinct apps as far as YunoHost is concerned.

Outline:

1. `pg_dump` the old `yamtrack_fork` PostgreSQL database.
2. Install `stackwise` fresh (Path A above).
3. Stop the `stackwise*` services, restore the dump into the new database,
   run `manage.py migrate`, then start the services.
4. Once verified, `sudo yunohost app remove yamtrack_fork`.

---

## Path B: Docker Compose from source (fast iteration)

When you want to iterate on a branch quickly, build the image from source and
let YunoHost's nginx handle the public TLS endpoint.

### B.1. Reserve the subdomain in YunoHost

```bash
sudo yunohost domain add stackwise.example.com
sudo yunohost domain cert-install stackwise.example.com
```

(Use `yunohost domain push-config` if your DNS is YunoHost-managed.)

### B.2. Install Docker on the YunoHost host

YunoHost runs on Debian. The official Docker apt repo is fine:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

### B.3. Clone the repo on the server

```bash
sudo mkdir -p /opt/stackwise
sudo chown $USER:$USER /opt/stackwise
cd /opt/stackwise
git clone https://github.com/LukeKeller/stackwise_ynh.git .
```

(Check out whichever branch you want to test.)

### B.4. Build the image from source

Write a small `docker-compose.override.yml` to build from the working tree:

```yaml
services:
  yamtrack:
    image: stackwise:dev
    build:
      context: .
      args:
        VERSION: dev
    environment:
      - URLS=https://stackwise.example.com
      - SECRET=<generate-a-long-random-string>
      - TMDB_API=<your-key>
      - MAL_API=<your-key>
      - IGDB_ID=<your-id>
      - IGDB_SECRET=<your-secret>
      - HARDCOVER_API=Bearer <your-token>
      - DEBUG=False
    ports:
      - "127.0.0.1:8000:8000"
```

(The compose service key stays `yamtrack` — that's the internal service name
in the shipped `docker-compose.yml`, not user-facing branding.)

Bind to `127.0.0.1` so only YunoHost's nginx (next step) can reach it — the
container is not directly exposed.

Then:

```bash
sudo docker compose up -d --build
sudo docker compose logs -f yamtrack
```

Confirm `http://127.0.0.1:8000/health/` returns `200` from the host.

### B.5. Tell YunoHost's nginx to reverse-proxy the subdomain

Drop a config file at
`/etc/nginx/conf.d/stackwise.example.com.d/stackwise.conf`:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 180s;
    client_max_body_size 20M;
}
```

YunoHost's main vhost at `/etc/nginx/conf.d/stackwise.example.com.conf`
includes the `*.d/` directory automatically.

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### B.6. Firewall

YunoHost normally manages `iptables`/`nftables` itself; ports 80/443 are open
by default for any added domain. You should not need to open port 8000
publicly — keep it bound to `127.0.0.1`.

### B.7. Smoke test

Visit `https://stackwise.example.com`. You should land on the login page. Sign
up the first user (the first registration auto-promotes to admin in this
build).

Verify:

1. Log in.
2. Add a book and confirm metadata loads.
3. Visit **Settings → Integrations** to confirm the page renders.

### B.8. Updates

```bash
cd /opt/stackwise
git pull
sudo docker compose up -d --build
```

Migrations run automatically via `entrypoint.sh`.

### B.9. Tearing it down

```bash
cd /opt/stackwise
sudo docker compose down
sudo rm /etc/nginx/conf.d/stackwise.example.com.d/stackwise.conf
sudo systemctl reload nginx
sudo yunohost domain remove stackwise.example.com   # only if you also want the domain gone
```

---

## Caveats and gotchas

- **`URLS` env var matters.** Without it set to your public HTTPS URL, allauth
  and the OAuth callbacks (Trakt, Simkl, AniList) will generate wrong redirect
  URIs and you'll get CSRF / mismatch errors.
- **`SECRET` rotation invalidates encrypted tokens.** The Fernet key for
  stored OAuth tokens (`integrations/imports/helpers.py: fernet`) is derived
  from `SECRET_KEY`. If you rotate `SECRET`, every existing import schedule
  with a stored token breaks. Pick one early and back it up.
- **YunoHost SSO ↔ local accounts.** The package optionally wires Dex OIDC in
  via `django-allauth`. With Path B you skip the SSO wiring; users sign in with
  Stackwise's local accounts. To re-enable SSO under Path B you'd set
  `SOCIAL_PROVIDERS` and `SOCIALACCOUNT_PROVIDERS` env vars to match a Dex
  client — out of scope for this guide.
- **Webhook URLs need the public hostname.** For Jellyfin/Plex/Emby webhooks,
  the URLs shown in the Integrations settings page derive from `URLS`; if it's
  wrong, the URLs in the UI will be wrong and webhooks will silently fail.
- **AGPL.** If you publish a Docker image or an installable artifact built from
  this code to anyone else, AGPL-3.0 obliges you to publish the matching
  source. Self-hosting on your own YunoHost server doesn't trigger that
  obligation.
