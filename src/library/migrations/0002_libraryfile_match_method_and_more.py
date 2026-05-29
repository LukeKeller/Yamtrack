from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="libraryfile",
            name="match_status",
            field=models.CharField(
                choices=[
                    ("unresolved", "Unresolved"),
                    ("matched", "Matched"),
                    ("no_match", "No match"),
                ],
                db_index=True,
                default="unresolved",
                help_text="Whether the upload has been resolved to a metadata provider.",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="libraryfile",
            name="match_method",
            field=models.CharField(
                choices=[
                    ("none", "None"),
                    ("isbn", "ISBN"),
                    ("title_author", "Title + Author"),
                    ("manual", "Manual"),
                ],
                default="none",
                help_text="How the provider match was made (ISBN, title+author, manual).",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="libraryfile",
            name="matched_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
