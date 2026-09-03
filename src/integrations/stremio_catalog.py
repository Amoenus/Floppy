"""Local catalog projection for the Stremio addon."""

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, unquote

from app.models import TV, MediaTypes, Movie, Sources, Status
from lists.models import CustomList, CustomListItem

PAGE_SIZE = 100
IMDB_ID_PATTERN = re.compile(r"^tt[0-9]+$")


@dataclass(frozen=True)
class CatalogSpec:
    """Stable Stremio catalog configuration and its local source rule."""

    stremio_type: str
    catalog_id: str
    media_type: str
    preferred_list_name: str = ""
    display_name: str = ""
    statuses: tuple[str, ...] = field(default_factory=tuple)


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
    CatalogSpec(
        stremio_type="movie",
        catalog_id="floppy-history-movies",
        media_type=MediaTypes.MOVIE.value,
        display_name="History",
        statuses=(Status.COMPLETED.value,),
    ),
    CatalogSpec(
        stremio_type="series",
        catalog_id="floppy-history-series",
        media_type=MediaTypes.TV.value,
        display_name="History",
        statuses=(Status.COMPLETED.value,),
    ),
    CatalogSpec(
        stremio_type="movie",
        catalog_id="floppy-in-progress-movies",
        media_type=MediaTypes.MOVIE.value,
        display_name="In Progress",
        statuses=(Status.IN_PROGRESS.value,),
    ),
    CatalogSpec(
        stremio_type="series",
        catalog_id="floppy-in-progress-series",
        media_type=MediaTypes.TV.value,
        display_name="In Progress",
        statuses=(Status.IN_PROGRESS.value,),
    ),
    CatalogSpec(
        stremio_type="series",
        catalog_id="floppy-planning-series",
        media_type=MediaTypes.TV.value,
        display_name="Planning",
        statuses=(Status.PLANNING.value,),
    ),
)

TRACKED_MODELS = {
    MediaTypes.MOVIE.value: Movie,
    MediaTypes.TV.value: TV,
}


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


def catalog_display_name(user, spec):
    """Return the manifest name for a catalog, by source rule."""
    if spec.statuses:
        return spec.display_name

    source_list = select_source_list(user, spec)
    if source_list is not None:
        return source_list.name
    return spec.preferred_list_name


def manifest_catalogs(user):
    """Build manifest catalogs from the same source rules used for projection."""
    return [
        {
            "type": spec.stremio_type,
            "id": spec.catalog_id,
            "name": f"Floppy: {catalog_display_name(user, spec)}",
            "extra": [{"name": "skip", "isRequired": False}],
        }
        for spec in CATALOG_SPECS
    ]


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


def build_metas(items, spec, skip):
    """Return one page of publishable metas and the scanned unresolved count."""
    metas = []
    publishable_seen = 0
    unresolved_count = 0
    for item in items:
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


def list_source_items(user, spec):
    """Yield items from the catalog's source list, newest membership first."""
    source_list = select_source_list(user, spec)
    if source_list is None:
        return

    memberships = (
        CustomListItem.objects.filter(
            custom_list=source_list,
            item__media_type=spec.media_type,
        )
        .select_related("item")
        .order_by("-date_added", "-id")
    )
    for membership in memberships.iterator():
        yield membership.item


def tracked_ordering(model):
    """Order by recent activity when stored, else by row creation.

    TV exposes progressed_at as a property derived from its seasons, so it
    is not a sortable column the way it is on Movie.
    """
    concrete = {field.name for field in model._meta.get_fields()}
    if "progressed_at" in concrete:
        return ("-progressed_at", "-id")
    return ("-created_at", "-id")


def status_source_items(user, spec):
    """Yield tracked items matching the catalog's statuses, most recent first."""
    model = TRACKED_MODELS.get(spec.media_type)
    if model is None:
        return

    tracked = (
        model.objects.filter(user=user, status__in=spec.statuses)
        .select_related("item")
        .order_by(*tracked_ordering(model))
    )
    for entry in tracked.iterator():
        yield entry.item


def project_catalog(user, spec, skip):
    """Return one page of publishable metas and the scanned unresolved count."""
    if spec.statuses:
        items = status_source_items(user, spec)
    else:
        items = list_source_items(user, spec)

    return build_metas(items, spec, skip)
