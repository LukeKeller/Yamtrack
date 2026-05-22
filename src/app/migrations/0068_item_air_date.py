# Adds Item.air_date so episode (and other dated) items can be sorted/filtered
# without re-fetching provider metadata each render.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0067_alter_track_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="air_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
