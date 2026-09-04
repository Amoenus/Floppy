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
        "source_url": item.source_url,
        "genres": item.genres,
        # Stored counterparts of live-payload keys the detail shell reads; without
        # them a synced item loses its rating chip and book series line (#1077).
        "score": item.provider_rating,
        "score_count": item.provider_rating_count,
        "series_name": item.series_name,
        "series_position": item.series_position,
        "max_progress": item.book_max_progress,
        "cast": [],
        "crew": [],
        "studios_full": [],
    }
