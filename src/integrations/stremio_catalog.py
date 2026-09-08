"""Local catalog projection for the Stremio addon."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote

from app.models import MediaTypes, Sources
from lists.models import CustomList, CustomListItem

PAGE_SIZE = 100
IMDB_ID_PATTERN = re.compile(r"^tt[0-9]+$")


@dataclass(frozen=True)
class CatalogSpec:
    """Stable Stremio catalog configuration and its local source rule."""

    stremio_type: str
    catalog_id: str
    media_type: str
    preferred_list_name: str


CATALOG_SPECS = (
    CatalogSpec(
        stremio_type="movie",
        catalog_id="floppy-watchlist-movies",
        media_type=MediaTypes.MOVIE.value,
        preferred_list_name="Movies",
    ),
    CatalogSpec(
        stremio_type="series",
        catalog_id="floppy-watchlist-series",
        media_type=MediaTypes.TV.value,
        preferred_list_name="Series",
    ),
)


def resolve_addon_credential(token):
    """Return (user, grant) for an add-on URL token, or (None, None).

    Accepts a catalog grant first, then falls back to the legacy account token
    so existing installs keep working. The fallback is the deprecation path,
    not the design: an account token in a URL grants full API access.
    """
    from integrations.models import CatalogGrant
    from users.models import User

    if not token:
        return (None, None)

    grant = CatalogGrant.objects.select_related("user").filter(token=token).first()
    if grant is not None:
        if not grant.is_valid():
            return (None, None)
        return (grant.user, grant)

    user = User.objects.filter(token=token).first()
    return (user, None) if user is not None else (None, None)


def touch_grant(grant, *, interval_minutes=60):
    """Record grant use, at most once an hour.

    Stremio polls catalogs continuously; writing a row per request would make
    this the busiest table in the install for no added information.
    """
    from django.utils import timezone

    now = timezone.now()
    if grant.last_used_at and (now - grant.last_used_at).total_seconds() < (
        interval_minutes * 60
    ):
        return
    type(grant).objects.filter(pk=grant.pk).update(last_used_at=now)
    grant.last_used_at = now


def manifest_catalogs_for_grant(user, grant):
    """Build manifest catalogs limited to what the grant covers."""
    catalogs = manifest_catalogs(user)
    if grant is None:
        return catalogs
    return [entry for entry in catalogs if grant.allows_catalog(entry["id"])]


def get_catalog_spec(stremio_type, catalog_id):
    """Return the matching supported catalog, if any."""
    return next(
        (
            spec
            for spec in CATALOG_SPECS
            if (spec.stremio_type, spec.catalog_id)
            == (stremio_type, catalog_id)
        ),
        None,
    )


def select_source_list(user, spec):
    """Select the oldest owned preferred list, then the oldest owned Watchlist."""
    owned_lists = CustomList.objects.filter(owner=user)
    source_list = (
        owned_lists.filter(name__iexact=spec.preferred_list_name)
        .order_by("id")
        .first()
    )
    if source_list is not None:
        return source_list

    return owned_lists.filter(name__iexact="Watchlist").order_by("id").first()


def manifest_catalogs(user):
    """Build manifest catalogs from the same source rules used for projection."""
    catalogs = []
    for spec in CATALOG_SPECS:
        source_list = select_source_list(user, spec)
        source_name = (
            source_list.name if source_list is not None else spec.preferred_list_name
        )
        catalogs.append(
            {
                "type": spec.stremio_type,
                "id": spec.catalog_id,
                "name": f"Floppy: {source_name}",
                "extra": [{"name": "skip", "isRequired": False}],
            }
        )
    return catalogs


def parse_skip(extra):
    """Parse the optional Stremio extra segment and return a non-negative skip."""
    if not extra:
        return 0

    try:
        pairs = parse_qsl(
            unquote(extra),
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as error:
        message = "Malformed catalog extra arguments"
        raise ValueError(message) from error

    if len(pairs) != 1 or pairs[0][0] != "skip":
        message = "Only one skip argument is supported"
        raise ValueError(message)

    value = pairs[0][1]
    if not value.isdecimal():
        message = "skip must be a non-negative integer"
        raise ValueError(message)

    try:
        return int(value)
    except ValueError as error:
        message = "skip must be a non-negative integer"
        raise ValueError(message) from error


def local_imdb_id(item):
    """Resolve an item's IMDb id without network, cache, or database writes."""
    if item.source == Sources.IMDB.value:
        media_id = str(item.media_id)
        if IMDB_ID_PATTERN.fullmatch(media_id):
            return media_id

    imdb_id = str((item.provider_external_ids or {}).get("imdb_id") or "")
    if IMDB_ID_PATTERN.fullmatch(imdb_id):
        return imdb_id

    return None


def catalog_readiness(user):
    """Return per-catalog publishable/unresolved counts for the settings page.

    project_catalog() already counts the items it has to drop for want of an
    IMDb ID, but only logs it. Surfacing the same number tells users whether a
    thin catalog is a Floppy problem they need to wait out or a list they need
    to fill (issue #1066).
    """
    readiness = []
    for spec in CATALOG_SPECS:
        source_list = select_source_list(user, spec)
        if source_list is None:
            continue

        memberships = (
            CustomListItem.objects.filter(
                custom_list=source_list,
                item__media_type=spec.media_type,
            )
            .select_related("item")
            .only(
                "item__source",
                "item__media_id",
                "item__provider_external_ids",
            )
        )

        total = 0
        publishable = 0
        for membership in memberships.iterator():
            total += 1
            if local_imdb_id(membership.item) is not None:
                publishable += 1

        if total:
            readiness.append(
                {
                    "noun": "movies" if spec.stremio_type == "movie" else "series",
                    "list_name": source_list.name,
                    "total": total,
                    "publishable": publishable,
                    "unresolved": total - publishable,
                },
            )
    return readiness


def project_catalog(user, spec, skip):
    """Return one page of publishable metas and the scanned unresolved count."""
    source_list = select_source_list(user, spec)
    if source_list is None:
        return [], 0

    memberships = (
        CustomListItem.objects.filter(
            custom_list=source_list,
            item__media_type=spec.media_type,
        )
        .select_related("item")
        .order_by("-date_added", "-id")
    )

    metas = []
    publishable_seen = 0
    unresolved_count = 0
    for membership in memberships.iterator():
        item = membership.item
        imdb_id = local_imdb_id(item)
        if imdb_id is None:
            unresolved_count += 1
            continue

        if publishable_seen < skip:
            publishable_seen += 1
            continue

        meta = {"id": imdb_id, "type": spec.stremio_type, "name": item.title}
        if item.image:
            meta["poster"] = item.image
        metas.append(meta)
        if len(metas) == PAGE_SIZE:
            break

    return metas, unresolved_count


def project_meta(user, stremio_type, imdb_id):
    """Return the publishable meta for one item the user actually tracks.

    Scoped to the user's own library on purpose. This endpoint is reachable by
    anyone holding the install URL, so answering for arbitrary ids would turn a
    catalog grant into an open metadata proxy over the whole item table.

    Provider fields stay as Floppy holds them; nothing is fetched here, so a
    metadata provider's terms are not extended by publishing this.
    """
    media_types = [
        spec.media_type for spec in CATALOG_SPECS if spec.stremio_type == stremio_type
    ]
    if not media_types:
        return None

    owned_list_ids = CustomList.objects.filter(owner=user).values_list("id", flat=True)
    membership = (
        CustomListItem.objects.filter(
            custom_list_id__in=list(owned_list_ids),
            item__media_type__in=media_types,
        )
        .select_related("item")
        .order_by("-date_added", "-id")
    )

    for entry in membership.iterator():
        item = entry.item
        if local_imdb_id(item) != imdb_id:
            continue

        meta = {
            "id": imdb_id,
            "type": stremio_type,
            "name": item.title,
        }
        if item.image:
            meta["poster"] = item.image
            meta["background"] = item.image
        if getattr(item, "synopsis", None):
            meta["description"] = item.synopsis
        return meta

    return None
