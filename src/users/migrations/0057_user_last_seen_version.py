from django.db import migrations, models


def backfill_last_seen_version(apps, schema_editor):
    """Set existing users to the version just before this migration ships.

    Without backfill, every existing user would see every historical release
    note on the first load after upgrade. Setting their pointer to ``ynh66``
    means they only see the ``ynh67`` modal — the change that introduced this
    feature — and every subsequent bump.
    """
    User = apps.get_model("users", "User")
    User.objects.filter(last_seen_version="").update(
        last_seen_version="0.25.2~ynh66",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0056_user_density"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="last_seen_version",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Latest fork version whose What's New modal this user has dismissed.",
                max_length=64,
            ),
        ),
        migrations.RunPython(backfill_last_seen_version, migrations.RunPython.noop),
    ]
