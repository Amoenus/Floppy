import json

from django.db import migrations

JELLYFIN_PULL_TASK_NAME = "Pull Jellyfin watch history"
JELLYFIN_PULL_INTERVAL_MINUTES = 240


def create_pull_schedules(apps, schema_editor):
    """Arm the recurring history pull for accounts that predate this feature.

    The previous migration defaulted every existing JellyfinAccount to
    pull_history_enabled=True, but only the connect/settings views create
    the matching PeriodicTask -- without this, existing users would see the
    toggle checked while no recurring pull actually runs until they
    reconnect or resave settings.
    """
    JellyfinAccount = apps.get_model("integrations", "JellyfinAccount")
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")

    accounts = JellyfinAccount.objects.filter(pull_history_enabled=True).exclude(
        base_url="",
    )
    if not accounts.exists():
        return

    interval, _ = IntervalSchedule.objects.get_or_create(
        every=JELLYFIN_PULL_INTERVAL_MINUTES,
        period="minutes",
    )

    for account in accounts:
        user_marker = f"'user_id': {account.user_id},"
        if PeriodicTask.objects.filter(
            task=JELLYFIN_PULL_TASK_NAME,
            kwargs__contains=user_marker,
        ).exists():
            continue

        PeriodicTask.objects.create(
            name=(
                f"{JELLYFIN_PULL_TASK_NAME} for "
                f"{account.jellyfin_username or account.user_id} "
                f"(every {JELLYFIN_PULL_INTERVAL_MINUTES} minutes)"
            ),
            task=JELLYFIN_PULL_TASK_NAME,
            interval=interval,
            kwargs=json.dumps({"user_id": account.user_id}),
            enabled=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("integrations", "0028_jellyfinaccount_last_pull_at_and_more"),
    ]

    operations = [
        migrations.RunPython(create_pull_schedules, reverse_code=migrations.RunPython.noop),
    ]
