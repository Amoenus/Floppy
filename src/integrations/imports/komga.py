"""Komga importer for book and comic reading progress."""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from http import HTTPStatus

import requests
from django.conf import settings
from django.utils import timezone

import app
from app.models import Item, MediaTypes, Sources, Status
from app.services.synced_status import keep_held_status
from integrations import connection_health
from integrations.imports.helpers import (
    ConnectionAuthError,
    MediaImportError,
    decrypt_or_raise,
)
from integrations.imports.koreader import KoreaderImporter
from integrations.imports.mylar import comic_issue_item
from integrations.models import KomgaAccount, KomgaBookLink
from integrations.safe_fetch import SelfHostedUrlError, send_to_self_hosted

logger = logging.getLogger(__name__)

ENTRY_SOURCE = "komga"
PAGE_SIZE = 100
EPUB_MEDIA_TYPE = "application/epub+zip"
# Komga and Floppy clocks can differ a little; re-read a short overlap.
SYNC_OVERLAP = timedelta(minutes=5)
# Comic Vine issue urls end in "4000-<issue id>" (4050 is a volume).
COMICVINE_ISSUE_LINK = re.compile(r"comicvine\.gamespot\.com/.*?4000-(\d+)")
AUTHOR_ROLES = frozenset({"", "author", "writer"})


class KomgaClient:
    """Thin API client for the Komga REST API."""

    def __init__(self, base_url: str, api_key: str):
        """Store the server URL and API key."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _get(self, path: str, **params):
        try:
            response = send_to_self_hosted(
                requests.get,
                f"{self.base_url}{path}",
                headers={"X-API-Key": self.api_key},
                params=params,
                timeout=20,
            )
        except SelfHostedUrlError as error:
            msg = f"Could not reach Komga: {error}"
            raise MediaImportError(msg) from error
        except requests.RequestException as error:
            msg = f"Could not reach Komga ({type(error).__name__})"
            raise MediaImportError(msg) from error
        if response.status_code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            msg = "Komga API key is invalid or unauthorized"
            raise ConnectionAuthError(msg)
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            msg = f"Komga request failed ({response.status_code}) for {path}"
            raise MediaImportError(msg)
        try:
            return response.json()
        except ValueError as error:
            msg = f"Komga returned an unreadable response for {path}"
            raise MediaImportError(msg) from error

    def healthcheck(self):
        """Verify the server is reachable and the key is accepted."""
        return self._get("/api/v2/users/me")

    def recently_read_books(self):
        """Yield books with reading progress, most recently read first."""
        page = 0
        while True:
            payload = self._get(
                "/api/v1/books",
                read_status=["IN_PROGRESS", "READ"],
                sort="readProgress.readDate,desc",
                page=page,
                size=PAGE_SIZE,
            )
            yield from payload.get("content") or []
            if payload.get("last", True):
                return
            page += 1


def importer(identifier, user, mode):
    """Import Komga reading progress for a user."""
    return KomgaImporter(user).import_data()


def _parse_datetime(value):
    """Return an aware datetime from a Komga timestamp, or None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else timezone.make_aware(parsed)


def _clean_isbn(value):
    """Return an ISBN without hyphens or spaces, uppercased."""
    return re.sub(r"[^0-9Xx]", "", str(value or "")).upper()


class KomgaImporter(KoreaderImporter):
    """Import reading progress from Komga.

    Books are matched with the same title/author matching KOReader uses, so
    only the client, the comic matching and the progress write are Komga's.
    """

    def __init__(self, user):
        """Initialize importer and validate account access."""
        self.user = user
        try:
            self.account = user.komga_account
        except KomgaAccount.DoesNotExist as error:
            msg = "Connect Komga before importing"
            raise MediaImportError(msg) from error

        try:
            api_key = decrypt_or_raise(self.account.api_key)
        except MediaImportError as error:
            # An unreadable stored key needs a reconnect as much as a rejected one.
            connection_health.record_failure(self.account, error, auth=True)
            raise

        self.client = KomgaClient(self.account.base_url, api_key)
        self.warnings = []
        self.enable_provider_enrichment = not settings.TESTING

    def import_data(self):
        """Import every book with reading progress newer than the last sync."""
        started_at = timezone.now()
        self.account.refresh_from_db()
        cutoff = (
            self.account.last_sync_at - SYNC_OVERLAP
            if self.account.last_sync_at
            else None
        )
        counts = defaultdict(int)
        self._library_items = self._build_library_index()
        links = {
            link.komga_book_id: link
            for link in KomgaBookLink.objects.filter(user=self.user).select_related(
                "item",
            )
        }

        try:
            for book in self.client.recently_read_books():
                progress = book.get("readProgress") or {}
                read_at = _parse_datetime(
                    progress.get("readDate") or progress.get("lastModified"),
                )
                if cutoff and read_at and read_at < cutoff:
                    break
                self._import_book(book, links, counts)
        except MediaImportError as error:
            connection_health.record_failure(
                self.account,
                error,
                auth=isinstance(error, ConnectionAuthError),
            )
            raise

        self.account.last_sync_at = started_at
        connection_health.record_success(self.account, extra_fields=["last_sync_at"])
        return dict(counts), "\n".join(dict.fromkeys(self.warnings))

    def _import_book(self, book, links, counts):
        """Write one Komga book's progress, counting the outcome."""
        progress = book.get("readProgress") or {}
        completed = bool(progress.get("completed"))
        page = int(progress.get("page") or 0)
        if not completed and page <= 0:
            return

        metadata = book.get("metadata") or {}
        title = metadata.get("title") or book.get("name") or ""
        is_book = (book.get("media") or {}).get("mediaType") == EPUB_MEDIA_TYPE
        media_type = MediaTypes.BOOK if is_book else MediaTypes.COMIC_ISSUE

        book_id = str(book.get("id") or "")
        link = links.get(book_id)
        item = link.item if link else self._resolve_book_item(book, is_book)
        if item is None:
            self.warnings.append(f"Could not match Komga book {title or book_id}")
            counts["skipped"] += 1
            return
        if link is None and book_id:
            links[book_id] = KomgaBookLink.objects.update_or_create(
                user=self.user,
                komga_book_id=book_id,
                defaults={"item": item},
            )[0]

        result = self._write_progress(item, media_type, book, completed, page)
        if result is None:
            counts["skipped"] += 1
            return
        counts[media_type.value] += 1
        counts["created" if result else "updated"] += 1

    def _resolve_book_item(self, book, is_book):
        """Return the Floppy item a Komga book maps to, or None."""
        metadata = book.get("metadata") or {}
        title = metadata.get("title") or book.get("name") or ""
        if is_book:
            authors = [
                author["name"]
                for author in metadata.get("authors") or []
                if author.get("name")
                and str(author.get("role") or "").lower() in AUTHOR_ROLES
            ]
            isbn = _clean_isbn(metadata.get("isbn"))
            if isbn:
                for item in self._library_items:
                    if isbn in {_clean_isbn(value) for value in item.isbn or []}:
                        return item
            return self._resolve_item(title, authors)

        series = book.get("seriesTitle") or ""
        number = metadata.get("number") or book.get("number")
        label = f"{series} #{number}" if series and number else title or series
        for link in metadata.get("links") or []:
            match = COMICVINE_ISSUE_LINK.search(str(link.get("url") or ""))
            if match:
                return comic_issue_item(match.group(1), label, None)
        if not self.account.create_missing or not label:
            return None
        return Item.objects.create(
            media_id=Item.generate_manual_id(),
            source=Sources.MANUAL.value,
            media_type=MediaTypes.COMIC_ISSUE.value,
            library_media_type=MediaTypes.COMIC_ISSUE.value,
            title=label,
            image="",
        )

    def _write_progress(self, item, media_type, book, completed, page):
        """Save the reading progress; return True if created, False if updated.

        Returns None when nothing changed.
        """
        model = (
            app.models.Book
            if media_type == MediaTypes.BOOK
            else app.models.ComicIssue
        )
        progress = book.get("readProgress") or {}
        read_at = _parse_datetime(progress.get("readDate")) or timezone.now()
        pages_total = int((book.get("media") or {}).get("pagesCount") or 0)

        existing = (
            model.objects.filter(user=self.user, item=item)
            .only("progress", "status", "start_date", "end_date")
            .first()
        )
        start_date = (
            (existing.start_date if existing else None)
            or _parse_datetime(progress.get("created"))
            or read_at
        )
        defaults = {
            "progress": max(pages_total, page) if completed else page,
            "status": Status.COMPLETED.value if completed else Status.IN_PROGRESS.value,
            "start_date": start_date,
            "end_date": (
                ((existing.end_date if existing else None) or read_at)
                if completed
                else None
            ),
        }
        defaults = keep_held_status(existing, defaults, read_at)

        if existing and all(
            getattr(existing, field) == value for field, value in defaults.items()
        ):
            return None
        model.objects.update_or_create(
            user=self.user,
            item=item,
            defaults=defaults,
            create_defaults={**defaults, "entry_source": ENTRY_SOURCE},
        )
        return existing is None
