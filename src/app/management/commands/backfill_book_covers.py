"""Backfill ``Item.image`` for book items missing a cover.

Usage::

    python manage.py backfill_book_covers
    python manage.py backfill_book_covers --limit 500
    python manage.py backfill_book_covers --source openlibrary
    python manage.py backfill_book_covers --dry-run

``Item.image`` is stored once when the row is created, from whatever the
provider returned at the time. Many book rows ended up with the
placeholder (or an empty string) because OpenLibrary's edition record
carried no cover id — even when the work had one or a cover was reachable
by ISBN. The provider cover resolver now tries edition -> work -> ISBN,
but that only helps fresh lookups; existing rows keep their stale image.

This command re-fetches metadata for book Items whose image is empty or
the placeholder and writes back any real cover the improved resolver now
finds. It busts the 24h provider metadata cache per item first, so it
re-resolves fresh rather than reading back coverless metadata cached
before the resolver fix shipped. It uses the shared rate-limited provider
session, so a backlog of a few hundred books takes a minute or two.
Manual entries are skipped — they have no metadata source to look up.

Pass ``-v 2`` to list the items that still have no cover (genuinely
absent from the provider) so they're easy to spot.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db.models import Q

from app.models import Item, MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)

# Django verbosity level at/above which we list the still-coverless items.
VERBOSE = 2


class Command(BaseCommand):
    """Re-resolve covers for book Items that have none."""

    help = "Populate Item.image for book items missing a cover via provider metadata."

    def add_arguments(self, parser):
        """Register CLI options."""
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max items to process this run (0 = until none remain).",
        )
        parser.add_argument(
            "--source",
            default=None,
            help="Only backfill the given source (openlibrary or hardcover).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be updated without writing.",
        )

    def handle(self, *args, **options):  # noqa: ARG002
        """Walk book Items with no cover and try to fill one in."""
        qs = (
            Item.objects.filter(media_type=MediaTypes.BOOK.value)
            .filter(Q(image="") | Q(image=settings.IMG_NONE))
            .exclude(source=Sources.MANUAL.value)
            .order_by("pk")
        )
        if options["source"]:
            qs = qs.filter(source=options["source"])
        if options["limit"]:
            qs = qs[: options["limit"]]

        total = qs.count()
        if not total:
            self.stdout.write("No book items need a cover backfill.")
            return

        self.stdout.write(f"Backfilling covers on {total} book item(s)...")
        verbosity = options["verbosity"]
        updated = skipped = errors = 0

        for item in qs.iterator(chunk_size=100):
            # Bust the 24h provider metadata cache first, otherwise we just
            # read back the same coverless metadata that was cached before
            # this command (or the cover-resolver fix) existed and every
            # item "skips". A backfill has to re-resolve fresh.
            cache.delete(f"{item.source}_{item.media_type}_{item.media_id}")

            try:
                metadata = services.get_media_metadata(
                    item.media_type,
                    item.media_id,
                    item.source,
                )
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.warning("metadata fetch failed for %s: %s", item, exc)
                continue

            image = metadata.get("image") or ""
            if not image or image == settings.IMG_NONE:
                skipped += 1
                if verbosity >= VERBOSE:
                    self.stdout.write(f"  no cover for {item} ({item.source})")
                continue

            if options["dry_run"]:
                self.stdout.write(f"  would set {item} -> {image}")
                updated += 1
                continue

            # Queryset .update so we don't fire any save() side effects and
            # stay safe to re-run while the app is serving traffic.
            Item.objects.filter(pk=item.pk).update(image=image)
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. updated={updated} skipped={skipped} errors={errors}",
            ),
        )
