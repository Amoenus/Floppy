"""Fallback metadata builders for provider-unavailable views."""


def stored_metadata_fallback(item):
    """Build minimal metadata from a stored Item when the provider is unavailable."""
    return {
        "media_id": item.media_id,
        "source": item.source,
        "media_type": item.media_type,
        "title": item.title,
        "original_title": item.original_title,
        "localized_title": item.localized_title,
        "image": item.image,
        "synopsis": item.synopsis,
        "genres": item.genres,
        "cast": [],
        "crew": [],
        "studios_full": [],
    }
