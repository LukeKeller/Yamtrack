# Hand-written migration mirroring 0043_add_boardgame_preferences.py
# Adds Record (vinyl) media-type preferences and re-validates last_search_type.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0061_add_record"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("users", "0052_alter_user_date_format"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="user",
            name="last_search_type_valid",
        ),
        migrations.AddField(
            model_name="user",
            name="record_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="user",
            name="record_layout",
            field=models.CharField(
                choices=[("grid", "Grid"), ("table", "Table")],
                default="grid",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="record_sort",
            field=models.CharField(
                choices=[
                    ("score", "Rating"),
                    ("title", "Title"),
                    ("progress", "Progress"),
                    ("start_date", "Start Date"),
                    ("end_date", "End Date"),
                ],
                default="score",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="record_status",
            field=models.CharField(
                choices=[
                    ("All", "All"),
                    ("Completed", "Completed"),
                    ("In progress", "In Progress"),
                    ("Planning", "Planning"),
                    ("Paused", "Paused"),
                    ("Dropped", "Dropped"),
                ],
                default="All",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="last_search_type",
            field=models.CharField(
                choices=[
                    ("tv", "TV Show"),
                    ("season", "TV Season"),
                    ("episode", "Episode"),
                    ("movie", "Movie"),
                    ("anime", "Anime"),
                    ("manga", "Manga"),
                    ("game", "Game"),
                    ("book", "Book"),
                    ("comic", "Comic"),
                    ("boardgame", "Boardgame"),
                    ("record", "Record"),
                ],
                default="tv",
                max_length=10,
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "last_search_type__in",
                        [
                            "tv",
                            "movie",
                            "anime",
                            "manga",
                            "game",
                            "book",
                            "comic",
                            "boardgame",
                            "record",
                        ],
                    ),
                ),
                name="last_search_type_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(("record_layout__in", ["grid", "table"])),
                name="record_layout_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "record_sort__in",
                        [
                            "score",
                            "title",
                            "progress",
                            "start_date",
                            "end_date",
                        ],
                    ),
                ),
                name="record_sort_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "record_status__in",
                        [
                            "All",
                            "Completed",
                            "In progress",
                            "Planning",
                            "Paused",
                            "Dropped",
                        ],
                    ),
                ),
                name="record_status_valid",
            ),
        ),
    ]
