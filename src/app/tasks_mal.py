"""Celery tasks for MyAnimeList-backed metadata."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="Sync MAL ratings from API")
def sync_mal_ratings_from_api():
    """Sync persisted MyAnimeList ratings for tracked anime items."""
    from app.services import mal_ratings

    updated = mal_ratings.sync_mal_ratings()
    return {"updated": updated}
