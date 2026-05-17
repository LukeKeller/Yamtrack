import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Create the PlayMBID table."""

    initial = True

    dependencies = [
        ("app", "0065_track"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlayMBID",
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
                (
                    "recording_mbid",
                    models.CharField(blank=True, default="", max_length=36),
                ),
                (
                    "release_mbid",
                    models.CharField(blank=True, default="", max_length=36),
                ),
                (
                    "artist_mbid",
                    models.CharField(blank=True, default="", max_length=36),
                ),
                ("checked_at", models.DateTimeField(auto_now=True)),
                (
                    "play",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mbid",
                        to="app.play",
                    ),
                ),
            ],
        ),
    ]
