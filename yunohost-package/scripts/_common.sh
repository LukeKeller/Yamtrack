#!/bin/bash

#=================================================
# COMMON VARIABLES AND CUSTOM HELPERS
#=================================================

timezone=$(timedatectl show --value --property=Timezone)

# Build a CA certificate bundle that includes the system CAs
# plus the YunoHost self-signed CA (needed for OIDC/Dex on self-signed domains)
yamtrack_setup_certs() {
    mkdir -p "$install_dir/certs"
    cp /etc/ssl/certs/ca-certificates.crt "$install_dir/certs/ca-bundle.crt"
    # Extract the CA cert from the domain's TLS chain (handles self-signed setups
    # where the ca.pem symlink may not match the actual issuing CA)
    openssl s_client -connect "$domain:443" -servername "$domain" -showcerts \
        < /dev/null 2>/dev/null \
        | awk '/BEGIN CERTIFICATE/{n++} n==2' \
        >> "$install_dir/certs/ca-bundle.crt" 2>/dev/null || true
    chown -R "$app:$app" "$install_dir/certs"
}

# Variables managed by this package (regenerated on every upgrade)
# Any other variable found in .env will be preserved across upgrades
YAMTRACK_MANAGED_ENV_VARS='SECRET|DEBUG|ALLOWED_HOSTS|CSRF|URLS|DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD|REDIS_URL|TZ|ACCOUNT_LOGOUT_REDIRECT_URL|REQUESTS_CA_BUNDLE|BASE_URL|REGISTRATION|SOCIAL_PROVIDERS|SOCIALACCOUNT_PROVIDERS|SOCIALACCOUNT_ONLY|REDIRECT_LOGIN_TO_SSO'

# Uppercase names of config panel questions bound to .env. Kept as empty
# placeholders in the .env template so that ynh_read_var_in_file never returns
# YNH_NULL (which would make YunoHost refuse to display the config panel).
# Values set by the user (via UI or manual edit) are preserved across upgrades.
YAMTRACK_CONFIG_PANEL_ENV_VARS='TRAKT_API|TRAKT_API_SECRET|SIMKL_ID|SIMKL_SECRET|ANILIST_ID|ANILIST_SECRET|STEAM_API_KEY'

# Write the .env config file and append OIDC + BASE_URL settings
# This avoids issues with ynh_config_add sed substitution on JSON values
yamtrack_setup_env() {
    local env_file="$install_dir/.env"
    local user_vars=""
    declare -A config_panel_values=()

    if [[ -f "$env_file" ]]; then
        # Preserve config panel values (they live as placeholders in the
        # template; we re-inject them in-place after regeneration)
        local upper val
        for upper in ${YAMTRACK_CONFIG_PANEL_ENV_VARS//|/ }; do
            val=$(ynh_read_var_in_file --file="$env_file" --key="$upper" 2>/dev/null || echo YNH_NULL)
            if [[ "$val" != "YNH_NULL" ]]; then
                config_panel_values[$upper]="$val"
            fi
        done

        # Preserve any other user-added env vars (not managed, not config panel)
        user_vars=$(grep -E '^[[:space:]]*#?[[:space:]]*[A-Z_][A-Z0-9_]*=' "$env_file" \
            | grep -vE "^[[:space:]]*#?[[:space:]]*(${YAMTRACK_MANAGED_ENV_VARS}|${YAMTRACK_CONFIG_PANEL_ENV_VARS})=" \
            || true)
    fi

    # Deploy the base .env template
    ynh_config_add --template=".env" --destination="$env_file"

    # Restore preserved config panel values into the template placeholders
    for upper in "${!config_panel_values[@]}"; do
        ynh_write_var_in_file --file="$env_file" --key="$upper" --value="${config_panel_values[$upper]}"
    done

    # Handle BASE_URL: empty if root path, otherwise the subpath
    local base_url=""
    if [[ "$path" != "/" ]]; then
        base_url="$path"
    fi
    echo "BASE_URL=$base_url" >> "$env_file"

    # Registration: allow when OIDC is active (SSOwat + Dex/LDAP protect access),
    # disable when using local auth only
    if [[ "$socialaccount_only" == "True" ]]; then
        echo "REGISTRATION=True" >> "$env_file"
    else
        echo "REGISTRATION=False" >> "$env_file"
    fi

    # Append OIDC/SSO settings (values from app settings, written directly to avoid sed issues with JSON)
    echo "SOCIAL_PROVIDERS=$social_providers" >> "$env_file"
    echo "SOCIALACCOUNT_PROVIDERS=$socialaccount_providers" >> "$env_file"
    echo "SOCIALACCOUNT_ONLY=$socialaccount_only" >> "$env_file"
    echo "REDIRECT_LOGIN_TO_SSO=$redirect_login_to_sso" >> "$env_file"

    # Re-inject user-added variables preserved from previous config
    if [[ -n "$user_vars" ]]; then
        echo "" >> "$env_file"
        echo "# User-added variables (preserved across upgrades)" >> "$env_file"
        echo "$user_vars" >> "$env_file"
    fi

    chmod 400 "$env_file"
    chown "$app:$app" "$env_file"

    # Update checksum to include the appended lines, so YunoHost
    # doesn't warn about "manually modified" file on next upgrade/restore
    ynh_store_file_checksum "$env_file"
}

# Register Yamtrack as an OIDC client in Dex (if installed and SSO enabled)
yamtrack_register_dex() {
    local enable_sso
    enable_sso=$(ynh_app_setting_get --key=enable_sso)

    # If SSO is disabled by user, use local auth
    if [[ "${enable_sso}" == "0" ]]; then
        social_providers=""
        socialaccount_providers="{}"
        socialaccount_only="False"
        redirect_login_to_sso="False"
        ynh_app_setting_set --key=social_providers --value="$social_providers"
        ynh_app_setting_set --key=socialaccount_providers --value="$socialaccount_providers"
        ynh_app_setting_set --key=socialaccount_only --value="$socialaccount_only"
        ynh_app_setting_set --key=redirect_login_to_sso --value="$redirect_login_to_sso"
        return
    fi

    local dex_domain
    local dex_path
    local dex_install_dir

    # Read Dex app settings (temporarily switch app context)
    local saved_app="$app"
    app="dex"
    dex_domain=$(ynh_app_setting_get --key=domain 2>/dev/null || true)
    dex_path=$(ynh_app_setting_get --key=path 2>/dev/null || true)
    dex_install_dir=$(ynh_app_setting_get --key=install_dir 2>/dev/null || true)
    app="$saved_app"

    if [[ -z "$dex_domain" ]]; then
        # Dex not installed, use local auth
        social_providers=""
        socialaccount_providers="{}"
        socialaccount_only="False"
        redirect_login_to_sso="False"
    else
        # Generate OIDC secret if not already set
        if [[ -z "${oidc_secret:-}" ]]; then
            oidc_secret=$(ynh_string_random --length=32)
        fi

        # Register as OIDC client in Dex
        local oidc_callback="${domain}${path}/accounts/oidc/yunohost/login/callback/"
        if [[ -n "$dex_install_dir" ]] && [[ -f "$dex_install_dir/add_config.sh" ]]; then
            bash "$dex_install_dir/add_config.sh" "$app" "$app" "$oidc_callback" "$oidc_secret"
            ynh_systemctl --service="dex" --action="restart" 2>/dev/null || true
        fi

        social_providers="allauth.socialaccount.providers.openid_connect"
        socialaccount_providers="{\"openid_connect\":{\"APPS\":[{\"provider_id\":\"yunohost\",\"name\":\"YunoHost\",\"client_id\":\"${app}\",\"secret\":\"${oidc_secret}\",\"settings\":{\"server_url\":\"https://${dex_domain}${dex_path}\"}}]}}"
        socialaccount_only="True"
        redirect_login_to_sso="True"
    fi

    # Save settings
    ynh_app_setting_set --key=oidc_secret --value="${oidc_secret:-}"
    ynh_app_setting_set --key=dex_domain --value="${dex_domain:-}"
    ynh_app_setting_set --key=dex_path --value="${dex_path:-}"
    ynh_app_setting_set --key=social_providers --value="$social_providers"
    ynh_app_setting_set --key=socialaccount_providers --value="$socialaccount_providers"
    ynh_app_setting_set --key=socialaccount_only --value="$socialaccount_only"
    ynh_app_setting_set --key=redirect_login_to_sso --value="$redirect_login_to_sso"
}
