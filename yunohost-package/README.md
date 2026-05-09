# Yamtrack (LukeKeller fork) — YunoHost package

This is a **fork** of the official YunoHost-Apps/yamtrack_ynh package, modified to install Yamtrack from `https://github.com/LukeKeller/Yamtrack` instead of the upstream `FuzzyGrim/Yamtrack` repository. Everything else (install/upgrade scripts, OIDC/Dex wiring, conf templates) is identical to upstream — credit to the original maintainer.

Use this when you want to test feature work (e.g., the in-flight Hardcover sync) on a YunoHost server before it's merged or released upstream.

## Why a separate `_ynh` repo

YunoHost validates the URL passed to `yunohost app install` with the regex
`^https://[host]/[owner]/[repo]_ynh(/tree/[branch])?$` — the segment immediately
after the owner must end in `_ynh`. Our main fork is `LukeKeller/Yamtrack`, which
doesn't match, so URL installs against this repo are rejected. To get a working
URL install we publish these packaging files to a dedicated repo named
`LukeKeller/yamtrack_ynh`. The main fork keeps a copy under `yunohost-package/`
for visibility, and an orphan `yunohost-package` branch on the main fork holds
the same files at the root for the local-path install.

## Install on your VPS

### A. From a single URL (recommended)

Requires the dedicated `LukeKeller/yamtrack_ynh` repo to exist (see "Publishing"
below). On the VPS:

```bash
sudo yunohost app install https://github.com/LukeKeller/yamtrack_ynh
```

### B. From a local path (works without the dedicated repo)

```bash
ssh root@<your-vps>
git clone -b yunohost-package --single-branch \
  https://github.com/LukeKeller/Yamtrack.git /tmp/yamtrack-pkg
sudo yunohost app install /tmp/yamtrack-pkg
```

Or, if you'd rather have the whole Yamtrack source tree on hand:

```bash
git clone -b claude/claude-md-hardcover-plan-E6saG \
  https://github.com/LukeKeller/Yamtrack.git /tmp/yamtrack
sudo yunohost app install /tmp/yamtrack/yunohost-package
```

## Publishing the dedicated `_ynh` repo (one-time setup)

1. On github.com, create an **empty** public repo named exactly `yamtrack_ynh`
   under your account (no README/license/.gitignore — just the bare repo).
2. On your dev machine, push this directory's contents to it as `main`:

   ```bash
   # Pull just the packaging files (the orphan branch on Yamtrack)
   git clone -b yunohost-package --single-branch \
     https://github.com/LukeKeller/Yamtrack.git /tmp/yamtrack_ynh
   cd /tmp/yamtrack_ynh
   git push https://github.com/LukeKeller/yamtrack_ynh.git yunohost-package:main
   ```

After step 2 the URL install (method A above) works.

## Updating the source pin

`manifest.toml` pins `[resources.sources.main]` to a **specific commit** on `LukeKeller/Yamtrack`, with a matching SHA256. When you push new commits on the fork (e.g., as Hardcover sync development progresses) and want the YunoHost package to deploy that newer code, you must update both fields together.

```bash
cd yunohost-package
./bump-source.sh                       # uses HEAD of the current branch
./bump-source.sh <commit-or-branch>    # explicit ref
```

The script downloads the corresponding GitHub tarball, computes its SHA256, rewrites `manifest.toml`, and prints the diff.

## Re-publishing after a bump

After running `bump-source.sh` and committing the result:

```bash
# 1. Push the change on your dev branch
git add yunohost-package/manifest.toml
git commit -m "Bump yunohost source pin"
git push

# 2. Refresh the orphan branch on LukeKeller/Yamtrack
git subtree split --prefix=yunohost-package -b yunohost-package
git push -f origin yunohost-package

# 3. Refresh main on LukeKeller/yamtrack_ynh (set up the remote once)
git remote add ynh https://github.com/LukeKeller/yamtrack_ynh.git  # one-time
git push -f ynh yunohost-package:main
```

Then on the VPS:

```bash
# Method A
sudo yunohost app upgrade yamtrack -u https://github.com/LukeKeller/yamtrack_ynh

# Method B
cd /tmp/yamtrack-pkg && git pull
sudo yunohost app upgrade yamtrack -u /tmp/yamtrack-pkg
```

## What the package does

Same as upstream:
- Provisions a Python venv from `requirements.txt`, runs `manage.py migrate` + `collectstatic`.
- Sets up nginx + three systemd units (`yamtrack`, `yamtrack-celery`, `yamtrack-celery-beat`).
- Provisions a PostgreSQL database and a Redis logical DB.
- Optionally registers Yamtrack as an OIDC client in Dex (`enable_sso=true`) so YunoHost SSO can sign users in. With `enable_sso=false` it falls back to Yamtrack's local accounts.
- Creates a Yamtrack admin matching the YunoHost user passed to `--admin`.

See `doc/ADMIN.md` (or `doc/ADMIN_fr.md`) for runtime configuration knobs (`TRAKT_API`, `SIMKL_ID`, etc.).

## Caveats specific to running a fork build

- **`autoupdate.strategy` is removed** from `manifest.toml` because the fork doesn't tag GitHub releases. The YunoHost CI auto-updater would have nothing to track. If you start tagging releases on `LukeKeller/Yamtrack`, you can re-add `autoupdate.strategy = "latest_github_release"` and drop the per-commit pin.
- **You're responsible for keeping the source pin moving forward.** Upstream's package gets bumped automatically; this one does not.
- **Don't submit this fork upstream.** This file lives only in your fork, not in `YunoHost-Apps/yamtrack_ynh`. If you want to contribute back, open a PR against the upstream repo with only the genuinely-shared changes.
