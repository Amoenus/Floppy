from django.db import migrations


def clear_sentinel_release_datetimes(apps, schema_editor):
    """Clear release_datetime values stuck at the year-1 sentinel.

    These were produced by extract_release_datetime() before it gained a
    lower-bound sanity check, and crash date-rendering template filters with
    OverflowError on servers running a negative UTC offset.
    """
    Item = apps.get_model("app", "Item")
    Item.objects.filter(release_datetime__year__lte=1).update(release_datetime=None)


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0170_remove_item_app_item_source_valid_and_more"),
    ]

    operations = [
        migrations.RunPython(
            clear_sentinel_release_datetimes,
            migrations.RunPython.noop,
        ),
    ]
