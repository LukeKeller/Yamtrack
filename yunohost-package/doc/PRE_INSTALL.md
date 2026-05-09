## SSO Integration (Single Sign-On)

For SSO integration with YunoHost, **install [Dex](https://apps.yunohost.org/app/dex) before installing Yamtrack** and enable the "SSO via Dex" option during installation.

Dex acts as an OIDC (OpenID Connect) provider backed by your YunoHost LDAP. When Dex is detected and SSO is enabled, your YunoHost users can log in to Yamtrack without creating a separate account.

If SSO is disabled or Dex is not installed, Yamtrack will work with its own local authentication system (username/password).
