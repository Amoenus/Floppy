"""Settings > Metadata: manage provider credentials from the UI."""

import os

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from app import preflight
from app.providers import credentials

MASK_VISIBLE_CHARS = 4

def _mask(value):
    """Return a preview that proves a value is stored without revealing it."""
    if not value:
        return ""
    if len(value) <= MASK_VISIBLE_CHARS:
        return "•" * len(value)
    return f"{'•' * 8}{value[-MASK_VISIBLE_CHARS:]}"


def _field_view(spec, field, user):
    """Return the template view-model for one credential field."""
    source = credentials.source_of(spec.slug, field.name, user)
    env = credentials.env_value(field)
    stored = credentials.instance_value(spec.slug, field.name)
    return {
        "name": field.name,
        "label": field.label,
        "secret": field.secret,
        "required": field.required,
        "placeholder": field.placeholder,
        "setting": field.setting,
        "source": source,
        "locked": bool(env),
        "preview": _mask(env or stored),
        "has_instance_value": bool(stored),
        "personal": field.name in {f.name for f in spec.personal_fields()},
        "has_personal_value": bool(credentials.user_value(spec, field, user)),
    }


def _provider_view(spec, user):
    """Return the template view-model for one provider row."""
    fields = [_field_view(spec, field, user) for field in spec.fields]
    sources = {field["source"] for field in fields if field["source"]}
    if credentials.has_user_value(spec.slug, user):
        status = credentials.SOURCE_USER
    elif credentials.SOURCE_ENV in sources:
        status = credentials.SOURCE_ENV
    elif credentials.SOURCE_DB in sources:
        status = credentials.SOURCE_DB
    elif credentials.SOURCE_DEFAULT in sources:
        status = credentials.SOURCE_DEFAULT
    else:
        status = ""
    return {
        "slug": spec.slug,
        "label": spec.label,
        "logo_slug": spec.logo_slug or spec.slug,
        "description": spec.description,
        "docs_url": spec.docs_url,
        "user_scope": spec.user_scope,
        "configured": credentials.is_configured(spec.slug, user),
        "status": status,
        "fields": fields,
        "personal_fields": [field for field in fields if field["personal"]],
        "locked": all(field["locked"] for field in fields),
        "has_instance_value": any(field["has_instance_value"] for field in fields),
    }


def _promote_command(username):
    """Return the promote command for the environment Floppy is running in.

    Reuses app.preflight.in_container so a Podman install is not handed
    Docker-only advice, and the container name follows the same
    HOST_CONTAINERNAME convention the SQLite recovery page uses.
    """
    if preflight.in_container():
        container = os.environ.get("HOST_CONTAINERNAME", "floppy")
        return f"docker exec -it {container} python manage.py promote_superuser {username}"
    return f"python src/manage.py promote_superuser {username}"


@require_GET
def metadata_settings(request):
    """Render the metadata provider credentials page."""
    user = request.user
    # Every provider takes a personal key now, so "who can set it" no longer
    # separates anything; grouping by what the provider does is what is left.
    can_edit_instance = user.is_superuser
    groups = []
    for group in credentials.GROUP_ORDER:
        providers = sorted(
            (
                _provider_view(spec, user)
                for spec in credentials.REGISTRY.values()
                if spec.group == group
            ),
            key=lambda provider: provider["label"].casefold(),
        )
        if providers:
            groups.append(
                {
                    "key": group,
                    "label": credentials.GROUP_LABELS[group],
                    "description": credentials.GROUP_DESCRIPTIONS[group],
                    "providers": providers,
                },
            )

    context = {
        "credential_groups": groups,
        "can_edit_instance": can_edit_instance,
    }
    if not can_edit_instance:
        # Floppy's setup never flags anyone, so the owner of a fresh install is
        # usually not a superuser and has no way to discover that.
        context["instance_has_superuser"] = (
            get_user_model().objects.filter(is_superuser=True).exists()
        )
        context["in_container"] = preflight.in_container()
        context["promote_command"] = _promote_command(user.username)
    return render(request, "users/metadata.html", context)


def _spec_or_none(slug):
    """Return the registry entry for a slug, or None."""
    return credentials.get_spec(slug)


@require_POST
def save_provider_credential(request, slug):
    """Store instance-wide credentials for a provider."""
    if not request.user.is_superuser:
        return HttpResponse(status=403)

    spec = _spec_or_none(slug)
    if spec is None:
        return HttpResponse(status=404)

    values = {
        field.name: request.POST.get(field.name, "").strip() for field in spec.fields
    }
    # A locked field is rendered read-only, so never let a post overwrite it.
    for field in spec.fields:
        if credentials.env_value(field):
            values.pop(field.name, None)

    if spec.validator is not None and any(values.values()):
        error = spec.validator(values)
        if error:
            messages.error(request, f"{spec.label}: {error}")
            return redirect("metadata_settings")

    credentials.set_instance(slug, values, actor=request.user)
    messages.success(request, f"{spec.label} credentials saved.")
    return redirect("metadata_settings")


@require_POST
def clear_provider_credential(request, slug):
    """Remove the instance-wide credentials for a provider."""
    if not request.user.is_superuser:
        return HttpResponse(status=403)

    spec = _spec_or_none(slug)
    if spec is None:
        return HttpResponse(status=404)

    credentials.clear_instance(slug)
    messages.success(request, f"{spec.label} credentials removed.")
    return redirect("metadata_settings")


@require_POST
def save_personal_credential(request, slug):
    """Store the current user's personal credentials for a provider."""
    spec = _spec_or_none(slug)
    if spec is None or not spec.user_scope:
        return HttpResponse(status=404)

    values = {
        field.name: request.POST.get(field.name, "").strip()
        for field in spec.personal_fields()
    }
    if spec.validator is not None and any(values.values()):
        error = spec.validator(values)
        if error:
            messages.error(request, f"{spec.label}: {error}")
            return redirect("metadata_settings")

    credentials.set_user(slug, request.user, values)
    if any(values.values()):
        messages.success(request, f"Your {spec.label} key was saved.")
    else:
        messages.success(request, f"Your {spec.label} key was removed.")
    return redirect("metadata_settings")
