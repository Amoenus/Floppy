from django.db import migrations


def backfill_source_instance_id(apps, schema_editor):
    """Attribute existing Radarr/Sonarr collection states to their instance.

    Before this release, a user could only have one Radarr connection and one
    Sonarr connection, so every existing CollectionSourceState row with
    source="radarr"/"sonarr" implicitly belonged to that single instance.
    Without this backfill, those rows would keep source_instance_id=NULL and
    fall into the "no instance" unique-constraint bucket, which is only
    correct for plex/jellyfin rows.
    """
    CollectionSourceState = apps.get_model("integrations", "CollectionSourceState")
    RadarrInstance = apps.get_model("integrations", "RadarrInstance")
    SonarrInstance = apps.get_model("integrations", "SonarrInstance")

    for source, model in (("radarr", RadarrInstance), ("sonarr", SonarrInstance)):
        instance_by_user = dict(
            model.objects.values_list("user_id", "id"),
        )
        states = CollectionSourceState.objects.filter(
            source=source, source_instance_id__isnull=True
        )
        for state in states:
            instance_id = instance_by_user.get(state.user_id)
            if instance_id is not None:
                state.source_instance_id = instance_id
                state.save(update_fields=["source_instance_id"])


def noop_reverse(apps, schema_editor):
    """No-op reverse: dropping the instance id back to NULL loses no data."""


class Migration(migrations.Migration):
    dependencies = [
        ("integrations", "0030_radarrinstance_sonarrinstance_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_source_instance_id, noop_reverse),
    ]
