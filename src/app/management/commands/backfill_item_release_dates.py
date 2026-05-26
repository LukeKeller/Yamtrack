"""Backfill ``Item.air_date`` for non-episode items.

Usage::

    python manage.py backfill_item_release_dates
    python manage.py backfill_item_release_dates --limit 500
    python manage.py backfill_item_release_dates --media-type tv
    python manage.py backfill_item_release_dates --dry-run

Item.air_date is the field the lists "Release Date" sort and the home
calendar rely on. Episode items have always been populated, but TV /
movie / book / game / etc. rows created before that data was wired in
have it blank. This command walks Items with ``air_date IS NULL`` and
fills them in from the provider via ``services.get_media_metadata``.

Each call uses the shared rate-limited provider session, so a backlog of
a few hundred items takes a minute or two. Episode rows are skipped
because they're populated through the season-refresh path and re-fetching
them here would be wasteful. Manual entries are also skipped — they
don't have a metadata source to look up.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from app.helpers import extract_release_date
from app.models import Item, MediaTypes, Sources
from app.providers import services

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Backfill premiere/release dates onto Item rows."""

    help = "Populate Item.air_date for non-episode items via provider metadata."

    def add_arguments(self, parser):
        """Register CLI options."""
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max items to process this run (0 = until none remain).",
        )
        parser.add_argument(
            "--media-type",
            default=None,
            help=(
                "Only backfill the given media_type (e.g., tv, movie, book). "
                "Defaults to every non-episode type."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be updated without writing.",
        )

    def handle(self, *args, **options):  # noqa: ARG002
        """Walk every Item missing an air_date and try to fill it in."""
        qs = (
            Item.objects.filter(air_date__isnull=True)
            .exclude(media_type=MediaTypes.EPISODE.value)
            .exclude(source=Sources.MANUAL.value)
            .order_by("pk")
        )
        if options["media_type"]:
            qs = qs.filter(media_type=options["media_type"])
        if options["limit"]:
            qs = qs[: options["limit"]]

        total = qs.count()
        if not total:
            self.stdout.write("No items need backfilling.")
            return

        self.stdout.write(f"Backfilling air_date on {total} item(s)...")
        updated = skipped = errors = 0

        for item in qs.iterator(chunk_size=100):
            try:
                metadata = services.get_media_metadata(
                    item.media_type,
                    item.media_id,
                    item.source,
                    [item.season_number] if item.season_number is not None else None,
                    item.episode_number,
                )
            except Exception as exc:  # noqa: BLE001
                errors += 1
                logger.warning("metadata fetch failed for %s: %s", item, exc)
                continue

            release_date = extract_release_date(metadata)
            if release_date is None:
                skipped += 1
                continue

            if options["dry_run"]:
                self.stdout.write(f"  would set {item} -> {release_date}")
                updated += 1
                continue

            # Use queryset .update so we don't fire model save() hooks
            # (Item doesn't have any, but staying side-effect-free keeps
            # this safe to re-run while the app is serving traffic).
            Item.objects.filter(pk=item.pk).update(air_date=release_date)
            updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. updated={updated} skipped={skipped} errors={errors}",
            ),
        )
