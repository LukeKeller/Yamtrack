from django.apps import AppConfig


class ReadingConfig(AppConfig):
    """Books workspace — hub view + URL prefix for library + KOReader sub-pages."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "reading"
