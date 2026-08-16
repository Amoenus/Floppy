import json
import logging
import zipfile
from collections import defaultdict
from datetime import UTC, datetime
from io import BytesIO

from billiard.exceptions import SoftTimeLimitExceeded
from django.apps import apps

import app
import app.providers
from app.models import ItemTag, MediaTypes, Sources, Status, Tag
from app.providers.services import ProviderAPIError
from integrations import import_progress
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError

logger = logging.getLogger(__name__)

# Priority order (highest first) used to resolve a single status when a game
# sits on more than one of Grouvee's status shelves at once.
SHELF_STATUS_PRIORITY = (
    ("Playing", Status.IN_PROGRESS.value),
    ("Played", Status.COMPLETED.value),
    ("Backlog", Status.PLANNING.value),
    ("Wish List", Status.PLANNING.value),
)

# Shelves already captured by SHELF_STATUS_PRIORITY's status resolution -
# tagging them too would be redundant. Every other shelf (Wish List, and any
# user-created/platform shelf) is applied as a tag so that distinction isn't
# lost once shelves collapse down to a single status.
STATUS_ONLY_SHELVES = frozenset({"Playing", "Played", "Backlog"})

# Cap on the archive's total uncompressed size, to bound memory use for a
# maliciously crafted zip. A real Grouvee export is a few MB at most.
MAX_UNCOMPRESSED_ZIP_BYTES = 50 * 1024 * 1024


def importer(file, user, mode):
    """Import media from a Grouvee JSON export, or a zip containing one."""
    grouvee_importer = GrouveeImporter(file, user, mode)
    return grouvee_importer.import_data()


class GrouveeImporter:
    """Class to handle importing user data from a Grouvee export."""

    def __init__(self, file, user, mode):
        """Initialize the importer with file, user, and mode.

        Args:
            file: Uploaded JSON or zip file
            user: Django user object to import data for
            mode (str): Import mode ("new" or "overwrite")
        """
        self.file = file
        self.user = user
        self.mode = mode
        self.warnings = []

        self.existing_media = helpers.get_existing_media(user)
        self.to_delete = defaultdict(lambda: defaultdict(set))
        self.bulk_media = defaultdict(list)

        logger.info(
            "Initialized Grouvee importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import all games from a Grouvee JSON export, or a zip containing one."""
        raw = self.file.read()
        if raw[:4] == b"PK\x03\x04":
            raw = self._extract_json_from_zip(raw)

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            msg = "Invalid file format. Please upload a Grouvee JSON or zip export."
            raise MediaImportError(msg) from e

        entries = data.get("collection", [])
        unmatched_titles = []
        total = len(entries)

        for i, entry in enumerate(entries, start=1):
            import_progress.report(i, total, "Grouvee")
            try:
                self._process_entry(entry, unmatched_titles)
            except SoftTimeLimitExceeded:
                # Large exports (thousands of games, each an IGDB lookup) can
                # run long enough to trip the task's soft time limit. Stop
                # here rather than losing every game already processed - the
                # entries collected so far still get saved below, and "new"
                # mode dedup means a re-run picks up where this left off.
                logger.warning(
                    "Grouvee import for %s hit the time limit at entry %s/%s",
                    self.user.username,
                    i,
                    total,
                )
                self.warnings.append(
                    "Import stopped partway through because it was taking too "
                    "long. Run the import again to pick up the remaining games.",
                )
                break
            except Exception as error:
                error_msg = f"Error processing entry: {entry.get('name')}"
                raise MediaImportUnexpectedError(error_msg) from error

        if unmatched_titles:
            title_list = helpers.join_with_commas_and(unmatched_titles)
            self.warnings.append(
                f"{title_list}: No IGDB ID in the Grouvee export - none imported",
            )

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }

        deduplicated_messages = "\n".join(dict.fromkeys(self.warnings))
        return imported_counts, deduplicated_messages if self.warnings else None

    def _extract_json_from_zip(self, raw):
        """Return the export JSON's bytes from a Grouvee export zip.

        Grouvee's export is a zip of ``grouvee_export.json`` and
        ``collection.csv``. The JSON carries a strict superset of the CSV's
        data, so it's the only member this reads.
        """
        try:
            archive = zipfile.ZipFile(BytesIO(raw))
        except zipfile.BadZipFile as e:
            msg = "The uploaded file is not a valid zip archive."
            raise MediaImportError(msg) from e

        total_size = sum(info.file_size for info in archive.infolist())
        if total_size > MAX_UNCOMPRESSED_ZIP_BYTES:
            msg = "The Grouvee export archive is too large to import."
            raise MediaImportError(msg)

        json_names = [n for n in archive.namelist() if n.lower().endswith(".json")]
        name = next(
            (n for n in json_names if n.lower().endswith("grouvee_export.json")),
            next(iter(json_names), None),
        )
        if name is None:
            msg = "The zip file doesn't contain a Grouvee JSON export."
            raise MediaImportError(msg)

        return archive.read(name)

    def _process_entry(self, entry, unmatched_titles):
        """Process a single game entry from the collection."""
        igdb_id = entry.get("igdb_id")
        if not igdb_id:
            unmatched_titles.append(entry.get("name", "Unknown"))
            return

        media_id = str(igdb_id)

        try:
            metadata = app.providers.services.get_media_metadata(
                MediaTypes.GAME.value,
                media_id,
                Sources.IGDB.value,
            )
        except ProviderAPIError as error:
            self.warnings.append(f"{entry.get('name')}: {error}")
            return

        item, _ = app.models.Item.objects.update_or_create(
            media_id=media_id,
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            defaults={
                "title": metadata["title"],
                "image": metadata["image"],
            },
        )
        self._apply_shelf_tags(item, entry)

        if not helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            MediaTypes.GAME.value,
            Sources.IGDB.value,
            media_id,
            self.mode,
        ):
            return

        instance = self._create_media_instance(item, entry)
        self.bulk_media[MediaTypes.GAME.value].append(instance)

    def _apply_shelf_tags(self, item, entry):
        """Tag the item with any shelf not already reflected in its status.

        Wish List and user-created/platform shelves (e.g. "Steam") don't map
        to a Status, so without this they'd leave no trace after import.
        """
        for shelf_name in entry.get("shelves", {}):
            if shelf_name in STATUS_ONLY_SHELVES:
                continue
            tag = Tag.objects.filter(user=self.user, name__iexact=shelf_name).first()
            if tag is None:
                tag = Tag.objects.create(user=self.user, name=shelf_name)
            ItemTag.objects.get_or_create(tag=tag, item=item)

    def _determine_status(self, entry):
        """Determine media status from Grouvee's shelves, by priority."""
        shelves = entry.get("shelves", {})
        for shelf_name, status in SHELF_STATUS_PRIORITY:
            if shelf_name in shelves:
                return status
        return Status.PLANNING.value

    def _parse_date(self, date_str):
        """Parse a Grouvee date string, treating the literal "None" as missing."""
        if not date_str or date_str == "None":
            return None
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)

    def _date_range(self, entry):
        """Return earliest start date and latest end date across play sessions."""
        starts = []
        ends = []
        for play in entry.get("dates", []):
            started = self._parse_date(play.get("date_started"))
            if started:
                starts.append(started)
            finished = self._parse_date(play.get("date_finished"))
            if finished:
                ends.append(finished)
        return (min(starts) if starts else None, max(ends) if ends else None)

    def _total_progress_minutes(self, entry):
        """Sum playtime in seconds across dated play sessions, converted to minutes.

        Steam's automatic playtime tracking can log ``seconds_played`` with no
        ``date_started``/``date_finished`` at all - background telemetry, not
        a play session the user consciously logged - so those are excluded.
        """
        total_seconds = sum(
            play.get("seconds_played") or 0
            for play in entry.get("dates", [])
            if self._parse_date(play.get("date_started"))
            or self._parse_date(play.get("date_finished"))
        )
        return total_seconds // 60

    def _build_notes(self, entry):
        """Combine per-session notes with the review, most useful content first.

        ``dates[].notes`` are short, specific annotations (e.g. why a session
        was dropped) rather than a timestamped activity log, so they're
        prepended to the review without any log-style formatting.
        """
        session_notes = [
            note.strip()
            for play in entry.get("dates", [])
            if (note := (play.get("notes") or "").strip())
        ]
        review = (entry.get("review") or "").strip()
        return "\n\n".join([*session_notes, review]) if review or session_notes else ""

    def _create_media_instance(self, item, entry):
        """Create a Game media instance with all parameters."""
        start_date, end_date = self._date_range(entry)
        rating = entry.get("rating")

        model = apps.get_model(app_label="app", model_name=MediaTypes.GAME.value)
        return model(
            item=item,
            user=self.user,
            score=rating * 2 if rating is not None else None,
            progress=self._total_progress_minutes(entry),
            status=self._determine_status(entry),
            start_date=start_date,
            end_date=end_date,
            notes=self._build_notes(entry),
        )
