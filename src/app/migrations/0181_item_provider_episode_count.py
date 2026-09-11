from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0180_item_metadata_refreshed_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="item",
            name="provider_episode_count",
            field=models.PositiveIntegerField(
                blank=True,
                help_text="Total episode count reported by the metadata provider",
                null=True,
            ),
        ),
    ]
