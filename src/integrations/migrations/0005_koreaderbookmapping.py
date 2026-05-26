"""KOReader sync mapping: per-user (file hash → book Item) row."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0069_book_last_hardcover_sync_at_and_more"),
        (
            "integrations",
            "0004_hardcoverbookmapping_hardcoverintegration",
        ),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="KOReaderBookMapping",
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
                    "document_hash",
                    models.CharField(
                        help_text="32-char hex MD5 KOReader computes per ebook file.",
                        max_length=32,
                    ),
                ),
                (
                    "last_progress",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Opaque KOReader position string (epubcfi or xpointer).",
                    ),
                ),
                ("last_percentage", models.FloatField(default=0.0)),
                (
                    "last_device",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                (
                    "last_device_id",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("last_progress_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="koreader_mappings",
                        to="app.item",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="koreader_mappings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-last_progress_at", "-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="koreaderbookmapping",
            constraint=models.UniqueConstraint(
                fields=("user", "document_hash"),
                name="koreader_unique_user_document",
            ),
        ),
        migrations.AddIndex(
            model_name="koreaderbookmapping",
            index=models.Index(
                fields=["user", "document_hash"],
                name="integration_user_id_38c015_idx",
            ),
        ),
    ]
