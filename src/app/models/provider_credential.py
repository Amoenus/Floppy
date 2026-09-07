"""Database-backed metadata provider credentials.

Values are Fernet ciphertext produced by ``integrations.imports.helpers.encrypt``,
the same scheme every integration account model uses. Rotating ``SECRET``
invalidates stored credentials, so readers must treat a decrypt failure as "not
configured" rather than an error.
"""

from django.conf import settings
from django.db import models


class InstanceProviderCredential(models.Model):
    """An instance-wide provider credential set from Settings > Metadata."""

    provider = models.CharField(max_length=32)
    field = models.CharField(max_length=32)
    value = models.TextField(help_text="Encrypted credential value")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        """Model options."""

        unique_together = ("provider", "field")
        verbose_name = "instance provider credential"

    def __str__(self):
        """Readable representation without leaking the value."""
        return f"{self.provider}.{self.field}"


class UserProviderCredential(models.Model):
    """A personal provider credential that overrides the instance value."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="provider_credentials",
    )
    provider = models.CharField(max_length=32)
    field = models.CharField(max_length=32)
    value = models.TextField(help_text="Encrypted credential value")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Model options."""

        unique_together = ("user", "provider", "field")
        verbose_name = "user provider credential"

    def __str__(self):
        """Readable representation without leaking the value."""
        return f"{self.user_id}:{self.provider}.{self.field}"
