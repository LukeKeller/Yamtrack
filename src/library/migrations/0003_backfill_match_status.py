# Backfill match_status / match_method / matched_at for existing LibraryFile rows.

from django.db import migrations


def backfill_match_status(apps, schema_editor):
    """Set match fields based on the legacy ``item`` linkage.

    Pre-feature, an upload was "matched" iff its ``item`` FK was set (a
    manual link, in practice). Mirror that: linked rows become
    MATCHED / MANUAL stamped at ``updated_at``; unlinked rows stay
    UNRESOLVED so the auto-match task can resolve them later.
    """
    library_file = apps.get_model("library", "LibraryFile")

    library_file.objects.filter(item__isnull=False).update(
        match_status="matched",
        match_method="manual",
    )
    # matched_at = updated_at, per-row (auto_now only fires on .save(),
    # not on the bulk .update() above, so set it explicitly here).
    for row in library_file.objects.filter(item__isnull=False).iterator():
        library_file.objects.filter(pk=row.pk).update(matched_at=row.updated_at)

    library_file.objects.filter(item__isnull=True).update(
        match_status="unresolved",
        match_method="none",
    )


def reverse_noop(apps, schema_editor):
    """No-op reverse: the columns are dropped by the schema migration."""


class Migration(migrations.Migration):
    """Data migration backfilling provider-match fields."""

    dependencies = [
        ("library", "0002_libraryfile_match_method_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_match_status, reverse_noop),
    ]
