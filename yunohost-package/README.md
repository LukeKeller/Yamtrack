# Yamtrack (LukeKeller fork) — YunoHost package

This is a **fork** of the official YunoHost-Apps/yamtrack_ynh package, modified to install Yamtrack from `https://github.com/LukeKeller/Yamtrack` instead of the upstream `FuzzyGrim/Yamtrack` repository. Everything else (install/upgrade scripts, OIDC/Dex wiring, conf templates) is identical to upstream — credit to the original maintainer.

Use this when you want to test feature work (e.g., the in-flight Hardcover sync) on a YunoHost server before it's merged or released upstream.

## Install

There are two ways to install. Pick whichever matches how you got the files onto your VPS.

### A. From a single URL (orphan `yunohost-package` branch)

```bash
sudo yunohost app install https://github.com/LukeKeller/Yamtrack/tree/yunohost-package
```

That branch contains only these packaging files at its root, which is what `yunohost app install <url>` expects.

### B. From a local path (cloning the full Yamtrack fork)

```bash
ssh root@<your-vps>
git clone -b claude/claude-md-hardcover-plan-E6saG \
  https://github.com/LukeKeller/Yamtrack.git /tmp/yamtrack
sudo yunohost app install /tmp/yamtrack/yunohost-package
```

Use this when you want to inspect or edit the package before installing — the directory is right there.

## Updating the source pin

`manifest.toml` pins `[resources.sources.main]` to a **specific commit** on `LukeKeller/Yamtrack`, with a matching SHA256. When you push new commits on the fork (e.g., as Hardcover sync development progresses) and want the YunoHost package to deploy that newer code, you must update both fields together.

Run the helper:

```bash
cd yunohost-package
./bump-source.sh                       # uses HEAD of the current branch
./bump-source.sh <commit-or-branch>    # explicit ref
```

The script downloads the corresponding GitHub tarball, computes its SHA256, rewrites `manifest.toml`, and prints the diff. Commit the result and (if you're using install method A) re-publish the orphan `yunohost-package` branch.

## Upgrade / reinstall after a bump

```bash
# method A:
sudo yunohost app upgrade yamtrack \
  -u https://github.com/LukeKeller/Yamtrack/tree/yunohost-package

# method B:
cd /tmp/yamtrack && git pull
sudo yunohost app upgrade yamtrack -u /tmp/yamtrack/yunohost-package
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
