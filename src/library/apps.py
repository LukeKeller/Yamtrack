from django.apps import AppConfig


class LibraryConfig(AppConfig):
    """User-uploaded ebook library + OPDS server."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "library"
