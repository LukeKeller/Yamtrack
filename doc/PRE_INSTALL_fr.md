## Intégration SSO (Authentification unique)

Pour l'intégration SSO avec YunoHost, **installez [Dex](https://apps.yunohost.org/app/dex) avant d'installer Yamtrack** et activez l'option « SSO via Dex » lors de l'installation.

Dex agit comme un fournisseur OIDC (OpenID Connect) basé sur le LDAP de votre YunoHost. Lorsque Dex est détecté et que le SSO est activé, vos utilisateurs YunoHost peuvent se connecter à Yamtrack sans créer de compte séparé.

Si le SSO est désactivé ou que Dex n'est pas installé, Yamtrack fonctionnera avec son propre système d'authentification locale (nom d'utilisateur/mot de passe).
