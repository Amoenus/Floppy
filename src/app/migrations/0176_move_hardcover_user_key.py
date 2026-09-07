"""Move personal Hardcover tokens onto the generic provider credential store.

The stored value is Fernet ciphertext under the same key, so it moves verbatim
without a decrypt round-trip.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    """Copy User.hardcover_api_key into UserProviderCredential."""
    User = apps.get_model("users", "User")
    UserProviderCredential = apps.get_model("app", "UserProviderCredential")

    rows = [
        UserProviderCredential(
            user_id=user_id,
            provider="hardcover",
            field="api_key",
            value=value,
        )
        for user_id, value in User.objects.exclude(
            hardcover_api_key__isnull=True,
        )
        .exclude(hardcover_api_key="")
        .values_list("id", "hardcover_api_key")
    ]
    UserProviderCredential.objects.bulk_create(rows, ignore_conflicts=True)


def backwards(apps, schema_editor):
    """Copy the credentials back onto the user rows."""
    User = apps.get_model("users", "User")
    UserProviderCredential = apps.get_model("app", "UserProviderCredential")

    for user_id, value in UserProviderCredential.objects.filter(
        provider="hardcover",
        field="api_key",
    ).values_list("user_id", "value"):
        User.objects.filter(id=user_id).update(hardcover_api_key=value)


class Migration(migrations.Migration):
    """Move personal Hardcover tokens to the provider credential store."""

    dependencies = [
        ("app", "0175_instanceprovidercredential_userprovidercredential"),
        ("users", "0127_user_hardcover_api_key"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
