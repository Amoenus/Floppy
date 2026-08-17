from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0125_mark_additional_plex_qa_accounts'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='pinned_watch_providers',
            field=models.JSONField(blank=True, default=list, help_text="Watch-provider names pinned/favorited by the user, promoted out of 'More'"),
        ),
    ]
