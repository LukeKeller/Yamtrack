from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0058_user_timezone"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="auto_mark_prior_episodes",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When marking an episode as watched, also mark any "
                    "earlier un-tracked episodes in the same season."
                ),
            ),
        ),
    ]
