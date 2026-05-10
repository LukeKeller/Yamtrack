from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0064_record_status_owned_or_want"),
    ]

    operations = [
        migrations.CreateModel(
            name="Track",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("position", models.CharField(max_length=10)),
                ("side", models.CharField(blank=True, default="", max_length=2)),
                (
                    "track_number",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                ("title", models.TextField()),
                ("artist", models.TextField(blank=True, default="")),
                (
                    "duration_seconds",
                    models.PositiveIntegerField(blank=True, null=True),
                ),
                (
                    "record_item",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE,
                        related_name="tracks",
                        to="app.item",
                    ),
                ),
            ],
            options={
                "ordering": ["side", "track_number", "pk"],
            },
        ),
        migrations.AddConstraint(
            model_name="track",
            constraint=models.UniqueConstraint(
                fields=("record_item", "position"),
                name="track_unique_position_per_record",
            ),
        ),
        migrations.AddField(
            model_name="play",
            name="track",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.SET_NULL,
                to="app.track",
            ),
        ),
    ]
