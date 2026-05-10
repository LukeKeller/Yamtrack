from django.db import migrations


def collapse_to_owned_or_want(apps, schema_editor):
    """Force every Record's status into the Owned/Want binary.

    Records introduced in earlier migrations could have inherited any of
    the shared Status values (In progress, Paused, Dropped, etc.) via
    imports or manual edits. The Record form now only exposes Owned
    (Completed) and Want (Planning), so anything outside those two values
    becomes invisible to the new UI. Map all such legacy values to
    Planning ("Want") as the safe default — owned vinyl that someone
    accidentally marked "In progress" stays visible without inflating
    the collection count.
    """
    Record = apps.get_model("app", "Record")
    Record.objects.exclude(status__in=["Completed", "Planning"]).update(
        status="Planning",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0063_play"),
    ]

    operations = [
        migrations.RunPython(
            collapse_to_owned_or_want,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
