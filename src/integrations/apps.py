from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """Integrations app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"

    def ready(self):
        """Register signal receivers (outbound Hardcover push)."""
        from integrations import signals  # noqa: F401, PLC0415
