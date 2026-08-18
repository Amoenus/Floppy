"""Backfill IMDB public aggregate ratings for movies, shows, and episodes."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from app.services import imdb_ratings


class Command(BaseCommand):
    """Sync IMDB's public aggregate ratings for tracked movies, shows, and episodes."""

    help = "Backfill imdb_rating/imdb_rating_count from IMDB's public datasets"

    def handle(self, *_args, **_options):
        """Run the IMDB ratings sync and report how many Items were updated."""
        self.stdout.write("Syncing movie/show ratings from IMDB datasets...")
        movies_and_shows_updated = imdb_ratings.sync_movie_and_show_ratings()
        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {movies_and_shows_updated} movie/show item(s)."
            ),
        )

        self.stdout.write("Syncing episode ratings from IMDB datasets...")
        episodes_updated = imdb_ratings.sync_episode_ratings()
        self.stdout.write(
            self.style.SUCCESS(f"Updated {episodes_updated} episode item(s)."),
        )
