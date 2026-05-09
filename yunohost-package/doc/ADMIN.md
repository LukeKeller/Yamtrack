## Enabling or disabling SSO

You can change the SSO setting at any time:

```bash
# Enable SSO
sudo yunohost app setting yamtrack enable_sso -v 1
sudo yunohost app upgrade yamtrack

# Disable SSO
sudo yunohost app setting yamtrack enable_sso -v 0
sudo yunohost app upgrade yamtrack
```

## Admin account

During installation, an admin account is created with the YunoHost admin username and a random password. You can retrieve this password with:

```bash
sudo yunohost app setting yamtrack admin_password
```

To change it:

```bash
# Become root first, then run changepassword interactively
sudo su
cd /var/www/yamtrack/src
sudo -u yamtrack /var/www/yamtrack/venv/bin/python manage.py changepassword <username>
```

## Media import integrations

Yamtrack can import media from external services (Trakt, Simkl, AniList, Steam). These require API credentials.

### Via the YunoHost UI (recommended)

Open **YunoHost admin → Applications → Yamtrack → Media Import Integrations**. The panel lets you fill in the credentials for Trakt, Simkl, AniList and Steam, and restarts the services automatically.

### Via the terminal

Alternatively, edit `/var/www/yamtrack/.env` as root:

```bash
sudo nano /var/www/yamtrack/.env
```

Append your variables at the end of the file, then restart the services:

```bash
sudo systemctl restart yamtrack yamtrack-celery yamtrack-celery-beat
```

See the [upstream documentation](https://github.com/FuzzyGrim/Yamtrack/wiki/Media-Import-Configuration) for the full list of supported variables (e.g. `TRAKT_API`, `TRAKT_API_SECRET`, `SIMKL_ID`, `SIMKL_SECRET`, `ANILIST_ID`, `ANILIST_SECRET`, `STEAM_API_KEY`).

User-added variables are **preserved across upgrades**. Variables managed by the package (database, SSO, etc.) are always regenerated from the YunoHost settings and should not be edited manually.
