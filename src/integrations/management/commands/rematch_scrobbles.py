"""Re-run the scrobble matcher over already-stored unmatched Plays.

Usage::

    python manage.py rematch_scrobbles            # backfill everything
    python manage.py rematch_scrobbles --dry-run  # report only
    python manage.py rematch_scrobbles --user me  # one user

Only ListenBrainz Plays with no linked Item are considered, so this is
safe to re-run and won't disturb manual vinyl spins or already-matched
scrobbles. When the improved matcher resolves a row it sets ``item``
(and ``track``/``side`` when a tracklist row matched).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from app.models import Play, PlaySource
from integrations import scrobble

BATCH = 500


class Command(BaseCommand):
    """Backfill Item/Track links on unmatched ListenBrainz scrobbles."""

    help = "Re-match unmatched ListenBrainz scrobbles against records/tracks."

    def add_arguments(self, parser):
        """Register CLI options."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many would match without writing changes.",
        )
        parser.add_argument(
            "--user",
            default=None,
            help="Only process this username (default: all users).",
        )

    def handle(self, *args, **options):  # noqa: ARG002
        """Scan unmatched scrobbles and link the ones that now resolve."""
        dry_run = options["dry_run"]
        username = options["user"]

        qs = Play.objects.filter(
            source=PlaySource.LISTENBRAINZ.value,
            item__isnull=True,
        )
        if username:
            qs = qs.filter(user__username=username)

        total = qs.count()
        self.stdout.write(f"Scanning {total} unmatched scrobble(s)...")

        matched = 0
        pending = []
        for play in qs.iterator(chunk_size=BATCH):
            item, track = scrobble.match_play(
                play.artist,
                play.title,
                play.album,
            )
            if not item:
                continue
            matched += 1
            play.item = item
            play.track = track
            if track and track.side:
                play.side = track.side
            pending.append(play)

            if not dry_run and len(pending) >= BATCH:
                with transaction.atomic():
                    Play.objects.bulk_update(
                        pending,
                        ["item", "track", "side"],
                    )
                pending = []

        if pending and not dry_run:
            with transaction.atomic():
                Play.objects.bulk_update(pending, ["item", "track", "side"])

        verb = "would link" if dry_run else "linked"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {matched} / {total} previously-unmatched scrobble(s).",
            ),
        )
