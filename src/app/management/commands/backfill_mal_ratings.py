"""Backfill MyAnimeList aggregate ratings for tracked anime."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from app.services import mal_ratings


class Command(BaseCommand):
    """Sync MyAnimeList ratings for tracked anime items."""

    help = "Backfill mal_rating/mal_rating_count from the MyAnimeList API"

    def handle(self, *_args, **_options):
        """Run the MAL rating sync and report the number of updated items."""
        self.stdout.write("Syncing anime ratings from MyAnimeList...")
        updated = mal_ratings.sync_mal_ratings()
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} anime item(s)."))
