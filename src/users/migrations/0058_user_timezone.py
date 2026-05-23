from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0057_user_last_seen_version"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="timezone",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "IANA timezone name (e.g. America/New_York). Empty falls "
                    "back to the server's TIME_ZONE setting."
                ),
                max_length=64,
            ),
        ),
    ]
