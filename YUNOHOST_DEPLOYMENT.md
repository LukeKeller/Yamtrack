# Deploying Yamtrack on YunoHost

This guide covers two paths:

- **Path A — Official YunoHost package.** Fastest way to confirm Yamtrack runs on your server. Installs upstream's latest packaged release (`0.25.2~ynh1` at time of writing). Does NOT include your Hardcover-sync work.
- **Path B — Docker Compose from source.** Builds the image from this fork and proxies it through YunoHost's nginx. Use this once you want to verify the Hardcover-sync branch end-to-end.

Pick A first to confirm your domain, certs, and nginx are all happy. Switch to B once the baseline works.

---

## Prerequisites (both paths)

- A YunoHost server (≥ 12.1.39) with a domain or subdomain you control.
- SSH/admin access.
- A subdomain reserved for Yamtrack — e.g., `yamtrack.example.com` — added under **YunoHost → Domains**.
- API keys for the providers you want to test against. At minimum: `TMDB_API`, `MAL_API`, `IGDB_ID` + `IGDB_SECRET`, `HARDCOVER_API`. See `src/config/settings.py` for the full list and their defaults.

---

## Path A: Install the official YunoHost package

The package lives at <https://github.com/YunoHost-Apps/yamtrack_ynh>.

```bash
sudo yunohost app install https://github.com/YunoHost-Apps/yamtrack_ynh
```

The installer asks for:

| Question | Notes |
|---|---|
| `domain` | The (sub)domain you reserved. |
| `path` | Default `/yamtrack`. Use `/` if you want it at the domain root. |
| `init_main_permission` | `all_users` lets every YunoHost account in. |
| `admin` | Pick the YunoHost user that becomes the Yamtrack admin. |
| `enable_sso` | If `true`, YunoHost wires up Dex OIDC SSO. If you'd rather use Yamtrack's local accounts, answer `false`. |

The package handles cert provisioning, nginx, systemd units, and a non-Docker install of the app. After install, browse to `https://<your-domain>/<path>` and log in.

To upgrade later (testing branch):

```bash
sudo yunohost app upgrade yamtrack \
  -u https://github.com/YunoHost-Apps/yamtrack_ynh/tree/testing
```

If install fails, check `/var/log/yunohost/operations/` and the app's log under **YunoHost admin → Apps → Yamtrack → Logs**.

---

## Path B: Run this fork via Docker Compose behind YunoHost nginx

When you want to verify the Hardcover-sync branch (or any other code on this fork) on YunoHost, you build the image from source and let YunoHost handle the public TLS endpoint.

### B.1. Reserve the subdomain in YunoHost

```bash
sudo yunohost domain add yamtrack.example.com
sudo yunohost domain cert-install yamtrack.example.com
```

(Use `yunohost domain push-config` if your DNS is YunoHost-managed.)

### B.2. Install Docker on the YunoHost host

YunoHost runs on Debian. The official Docker apt repo is fine:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

### B.3. Clone this fork on the server

```bash
sudo mkdir -p /opt/yamtrack
sudo chown $USER:$USER /opt/yamtrack
cd /opt/yamtrack
git clone -b claude/claude-md-hardcover-plan-E6saG \
  https://github.com/LukeKeller/Yamtrack.git .
```

(Substitute the branch you actually want to test.)

### B.4. Build the image from source

The shipped `docker-compose.yml` uses `ghcr.io/fuzzygrim/yamtrack`. Override that to build from the working tree by writing a small `docker-compose.override.yml`:

```yaml
services:
  yamtrack:
    image: yamtrack:dev
    build:
      context: .
      args:
        VERSION: dev
    environment:
      - URLS=https://yamtrack.example.com
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

Bind to `127.0.0.1` so only YunoHost's nginx (next step) can reach it — the container is not directly exposed.

Then:

```bash
sudo docker compose up -d --build
sudo docker compose logs -f yamtrack
```

Confirm `http://127.0.0.1:8000/health/` returns `200` from the host.

### B.5. Tell YunoHost's nginx to reverse-proxy the subdomain

Drop a config file at `/etc/nginx/conf.d/yamtrack.example.com.d/yamtrack.conf`:

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

YunoHost's main vhost at `/etc/nginx/conf.d/yamtrack.example.com.conf` includes the `*.d/` directory automatically.

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### B.6. Open the firewall (only if not behind YunoHost's default)

YunoHost normally manages `iptables`/`nftables` itself; ports 80/443 are open by default for any added domain. You should not need to open port 8000 publicly — keep it bound to `127.0.0.1`.

### B.7. Smoke test

Visit `https://yamtrack.example.com`. You should land on the login page. Sign up the first user (the first registration auto-promotes to admin in this build; double-check via `docker compose exec yamtrack python manage.py shell`).

Verify:

1. Log in.
2. Add a book — search for one that exists on Hardcover, confirm metadata loads (this exercises `app/providers/hardcover.py` end-to-end).
3. Visit **Profile → Integrations** to confirm the page renders.
4. If you've shipped the Hardcover sync UI yet, visit `/integrations/hardcover/` and connect a Hardcover account.

### B.8. Updates

```bash
cd /opt/yamtrack
git pull
sudo docker compose up -d --build
```

Migrations run automatically via `entrypoint.sh`.

### B.9. Tearing it down

```bash
cd /opt/yamtrack
sudo docker compose down
sudo rm /etc/nginx/conf.d/yamtrack.example.com.d/yamtrack.conf
sudo systemctl reload nginx
sudo yunohost domain remove yamtrack.example.com   # only if you also want the domain gone
```

---

## Caveats and gotchas

- **`URLS` env var matters.** Without it set to your public HTTPS URL, allauth and the OAuth callbacks (Trakt, Simkl, AniList) will generate wrong redirect URIs and you'll get CSRF / mismatch errors. The README is explicit about this.
- **`SECRET` rotation invalidates encrypted tokens.** The Fernet key for stored OAuth tokens (`integrations/imports/helpers.py: fernet`) is derived from `SECRET_KEY`. If you rotate `SECRET`, every existing import schedule with a stored token breaks. Pick one early and back it up.
- **YunoHost SSO ↔ Yamtrack accounts.** The official package optionally wires Dex OIDC into Yamtrack via `django-allauth`. If you go Path B, you skip the SSO wiring; users sign in with Yamtrack's local accounts. To re-enable SSO under Path B you'd set `SOCIAL_PROVIDERS` and `SOCIALACCOUNT_PROVIDERS` env vars to match a Dex client — out of scope for this guide.
- **Webhook URLs need the public hostname.** For Jellyfin/Plex/Emby webhooks, the URLs shown in the Integrations settings page derive from `URLS`; if it's wrong, the URLs in the UI will be wrong and webhooks will silently fail.
- **AGPL.** If you publish a Docker image or an installable artifact built from this fork to anyone else, AGPL-3.0 obliges you to publish the matching source. Self-hosting on your own YunoHost server doesn't trigger that obligation.

---

## Which path for which goal?

| Goal | Use |
|---|---|
| Confirm "Yamtrack runs on my YunoHost box at all" | Path A |
| Test SSO/OIDC integration | Path A (the package does it for you) |
| Verify the Hardcover sync code on this branch | Path B |
| Iterate on a feature branch with `git pull && rebuild` | Path B |
| Run for friends/family long-term | Path A, then `yunohost app upgrade` when the package updates |
