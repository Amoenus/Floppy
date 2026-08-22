from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0162_historicalseason_rewatch_started_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApplicationSettings",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "image_caching_enabled",
                    models.BooleanField(default=False),
                ),
            ],
            options={
                "verbose_name": "application setting",
                "verbose_name_plural": "application settings",
            },
        ),
    ]
