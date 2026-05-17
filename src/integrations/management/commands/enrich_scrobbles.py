"""Backfill MusicBrainz IDs for stored scrobbles.

Usage::

    python manage.py enrich_scrobbles                 # process all pending
    python manage.py enrich_scrobbles --limit 2000    # cap this run
    python manage.py enrich_scrobbles --sleep 0.05    # faster (be polite)

Resolves each ListenBrainz Play that has no PlayMBID row yet against the
ListenBrainz metadata lookup API and records the MusicBrainz IDs (or a
miss). Safe to re-run — already-processed plays are skipped.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from integrations import musicbrainz


class Command(BaseCommand):
    """Resolve MusicBrainz IDs for unenriched ListenBrainz scrobbles."""

    help = "Backfill MusicBrainz IDs on stored scrobbles via ListenBrainz."

    def add_arguments(self, parser):
        """Register CLI options."""
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max plays to process this run (0 = until none remain).",
        )
        parser.add_argument(
            "--batch",
            type=int,
            default=500,
            help="Plays fetched per pass when --limit is 0 (default 500).",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.1,
            help="Seconds to wait between live API calls (default 0.1).",
        )

    def handle(self, *args, **options):  # noqa: ARG002
        """Run enrichment, optionally looping until nothing is pending."""
        limit = options["limit"]
        batch = options["batch"]
        sleep = options["sleep"]

        totals = {"scanned": 0, "created": 0, "matched": 0}

        if limit:
            result = musicbrainz.enrich_pending(limit=limit, sleep=sleep)
            for k in totals:
                totals[k] += result[k]
        else:
            while True:
                result = musicbrainz.enrich_pending(limit=batch, sleep=sleep)
                for k in totals:
                    totals[k] += result[k]
                if result["scanned"] == 0:
                    break
                self.stdout.write(
                    f"  ... {totals['created']} processed "
                    f"({totals['matched']} matched so far)",
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed {totals['created']} scrobble(s); "
                f"{totals['matched']} resolved to a MusicBrainz recording.",
            ),
        )
