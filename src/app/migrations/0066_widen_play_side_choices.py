# Widen Play.side to accept all single-letter sides A..Z (some records
# are box sets / triple-LPs with sides beyond A/B).

from django.db import migrations, models


SIDE_CHOICES = [(letter, f"Side {letter}") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
SIDE_CHOICES.append(("full", "Full Listen"))

ALLOWED_SIDES = [letter for letter, _ in SIDE_CHOICES] + [""]


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0065_track"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="play",
            name="app_play_side_valid",
        ),
        migrations.AlterField(
            model_name="play",
            name="side",
            field=models.CharField(
                blank=True,
                choices=SIDE_CHOICES,
                default="",
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="play",
            constraint=models.CheckConstraint(
                condition=models.Q(("side__in", ALLOWED_SIDES)),
                name="app_play_side_valid",
            ),
        ),
    ]
