import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Create the WebhookEvent rolling activity log."""

    dependencies = [
        ("integrations", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WebhookEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("jellyfin", "Jellyfin"),
                            ("plex", "Plex"),
                            ("emby", "Emby"),
                        ],
                        max_length=20,
                    ),
                ),
                ("ok", models.BooleanField(default=False)),
                ("status_code", models.PositiveSmallIntegerField(default=0)),
                ("title", models.CharField(blank=True, default="", max_length=255)),
                ("error", models.TextField(blank=True, default="")),
                ("payload_sample", models.TextField(blank=True, default="")),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="webhook_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(
                        fields=["user", "-created_at"],
                        name="whevent_user_created_idx",
                    ),
                ],
            },
        ),
    ]
