# Runbook — migrate blog-vps from `yamtrack_fork` to `stackwise`

One-time cutover. Because the YunoHost **id changes** (`yamtrack_fork` → `stackwise`), YunoHost treats this as a *different app*: there is no in-place upgrade. This is a fresh install of `stackwise` plus a Postgres data copy. It's safe because we deliberately kept all **internal** identifiers as `yamtrack` — the database schema and table names are identical, so the old data restores into the new app unchanged.

> **blog-vps gotcha (known):** SSH stdout on this box is unreliable and can corrupt long command output. For anything whose result you need to read, redirect to a file and `scp` it back rather than trusting the terminal. Run destructive steps one at a time and verify each.

## What to copy — and what NOT to

You know both apps' DB passwords, so copying is easy. But:

- **Do NOT point `stackwise` at `yamtrack_fork`'s database, and do NOT copy the `DB_*` / `REDIS_URL` / `URLS` / `BASE_URL` lines from the old `.env`.** Those are install-specific. Sharing the DB is a trap: removing `yamtrack_fork` later runs its remove script, which **drops that database** — taking `stackwise`'s data with it. Two live instances also run two Celery beat schedulers (duplicate notifications/digests) and can race on migrations. Give `stackwise` its own DB and **copy the data in** (logical `pg_dump | psql`, step 3). Raw Postgres file copy isn't a per-database operation, so dump/restore is the mechanism regardless.
- **DO carry over `SECRET`.** Integration OAuth tokens (Trakt/Simkl/AniList) are Fernet-encrypted with a key derived from `SECRET`. A fresh install generates a new `SECRET`, so copied tokens won't decrypt. Either reuse the old `SECRET` (below) or re-authenticate the integrations afterward.
- **DO carry over the provider/integration API keys** (TMDB/MAL/IGDB/BGG and the config-panel ones: Trakt/Simkl/AniList/Steam).
- **`.env` caveat:** don't just `cp` the whole old `.env` over `stackwise`'s. YunoHost *regenerates* the managed parts of `.env` (`SECRET`, `DB_*`, `URLS`, OIDC, …) on every install/upgrade from **app settings** + the template (`yamtrack_setup_env` in `scripts/_common.sh`). The durable way to carry a value is to set the corresponding **app setting**, then let YunoHost write the `.env` — a hand-edit of `.env` survives until the next upgrade and then gets overwritten.

## 0. Pre-flight

```bash
# On blog-vps. Confirm the old app id and its current path.
yunohost app list | grep -iE 'yamtrack|stackwise'
yunohost app info yamtrack_fork
# Full safety backup of the old app (DB + files + conf).
yunohost backup create --apps yamtrack_fork --name pre-stackwise-migration
yunohost backup list
```

## 1. Dump the old database

The old app's Postgres DB/user/password are derived from its id (`yamtrack_fork`). Read the DB password from its app settings, then dump.

```bash
old_db=$(yunohost app setting yamtrack_fork db_name)   # usually 'yamtrack_fork'
old_pwd=$(yunohost app setting yamtrack_fork db_pwd)
sudo -u postgres pg_dump --no-owner --no-privileges "$old_db" > /root/yamtrack_fork.sql
ls -la /root/yamtrack_fork.sql   # sanity: non-zero size
```

Also note the old `data_dir` (uploaded media / covers), if any:

```bash
yunohost app setting yamtrack_fork data_dir   # e.g. /home/yunohost.app/yamtrack_fork
```

## 2. Install the new `stackwise` app

Match the old app's SSO setting rather than guessing it:

```bash
old_sso=$(yunohost app setting yamtrack_fork enable_sso)   # 1 or 0
sudo yunohost app install https://github.com/LukeKeller/stackwise_ynh \
  --args "domain=<your-domain>&path=/stackwise&admin=luke&enable_sso=$old_sso"
```

This creates a fresh `stackwise` Postgres DB and runs migrations on an empty schema. Confirm it comes up at `/stackwise` before proceeding. (`/stackwise` is distinct from the old app's path, so both run side by side.)

## 3. Copy the data into the new app

```bash
new_db=$(yunohost app setting stackwise db_name)       # 'stackwise'
new_user=$(yunohost app setting stackwise db_user)     # 'stackwise'

# Stop the new app's services so nothing writes during the restore.
yunohost service stop stackwise stackwise-celery stackwise-celery-beat

# Reset the new DB to empty, then load the old data.
sudo -u postgres psql -c "DROP DATABASE \"$new_db\";"
sudo -u postgres psql -c "CREATE DATABASE \"$new_db\" OWNER \"$new_user\";"
sudo -u postgres psql "$new_db" < /root/yamtrack_fork.sql
# Ensure ownership of restored objects is the new role.
sudo -u postgres psql "$new_db" -c "REASSIGN OWNED BY \"$old_db\" TO \"$new_user\";" 2>/dev/null || true
```

Copy uploaded media/covers from the old `data_dir` to the new one (preserve ownership):

```bash
old_data=$(yunohost app setting yamtrack_fork data_dir)
new_data=$(yunohost app setting stackwise data_dir)
rsync -a "$old_data"/ "$new_data"/
chown -R stackwise:stackwise "$new_data"
```

## 3b. Carry over SECRET + integration keys (via app settings)

Set these as `stackwise` **app settings** so YunoHost writes them into `.env` and keeps them across future upgrades. `SECRET` is what makes the copied OAuth tokens decryptable.

```bash
# SECRET — required for Fernet-encrypted Trakt/Simkl/AniList tokens to decrypt.
yunohost app setting stackwise secret -v "$(yunohost app setting yamtrack_fork secret)"

# Config-panel integration keys (only the ones you actually set on the old app).
for k in trakt_api trakt_api_secret simkl_id simkl_secret anilist_id anilist_secret steam_api_key; do
    v=$(yunohost app setting yamtrack_fork "$k" 2>/dev/null || true)
    [ -n "$v" ] && yunohost app setting stackwise "$k" -v "$v"
done
```

Provider keys that live in `.env` but aren't config-panel settings (TMDB/MAL/IGDB/BGG): copy just those lines from the old `.env`, or re-enter them. Do **not** copy `DB_*`, `REDIS_URL`, `URLS`, or `BASE_URL` — `stackwise` has its own.

Re-run the env regeneration so the new settings land in `.env` (a no-op upgrade does this, or just proceed — step 4's restart picks them up after you trigger a config refresh; simplest is `yunohost app upgrade stackwise` once more, or edit `.env` directly knowing it's authoritative until the next upgrade).

## 4. Migrate + restart

```bash
install_dir=$(yunohost app setting stackwise install_dir)
sudo -u stackwise "$install_dir/venv/bin/python" "$install_dir/src/manage.py" migrate --noinput
sudo -u stackwise "$install_dir/venv/bin/python" "$install_dir/src/manage.py" collectstatic --noinput
yunohost service start stackwise stackwise-celery stackwise-celery-beat
```

## 5. Re-point external integrations (the routing change)

Anything that pointed at the old `/yamtrack-fork` path must move to `/stackwise`:

- **Webhooks** (Jellyfin / Plex / Emby) — update the receiver URL to `https://<domain>/stackwise/webhook` (and `/stackwise/api/scrobble`, `/stackwise/api/koreader`, `/stackwise/library/opds` if used). The per-user API token is unchanged.
- **OIDC/Dex** — the install re-registers the callback as `https://<domain>/stackwise/accounts/oidc/yunohost/login/callback/`. If you have a manual Dex static client, update its redirect URI.
- **Calendar (.ics) subscriptions** and any bookmarks — re-issue from the new URL.
- **Reverse-proxy / DNS** — if you fronted `/yamtrack-fork` anywhere upstream, repoint to `/stackwise`.

## 6. Reapply the upload fix (known blog-vps issue)

The 413/502-on-large-upload fix (`client_max_body_size 200M` + the seccomp `@chown` systemd drop-in for epub/zip uploads) was applied manually to the old install. Verify it's present on `stackwise`; reapply if missing. **Follow-up:** bake `client_max_body_size 200M` into `conf/nginx.conf` in the package so future installs/upgrades carry it automatically.

## 7. Verify, then remove the old app

```bash
# Log in at https://<domain>/stackwise — confirm library, history, scores,
# lists, and a large file upload (epub/zip) all work.
yunohost app remove yamtrack_fork
```

Keep the `pre-stackwise-migration` backup and `/root/yamtrack_fork.sql` until you've used the new instance for a few days.
