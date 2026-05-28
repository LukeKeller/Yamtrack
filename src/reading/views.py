"""Reading hub — landing surface + unified unmatched inbox.

The hub is a read-only aggregator: it fans out existing querysets from
the ``library`` and ``integrations`` apps and presents them in one
place so users don't have to scroll through ``Settings → Integrations``
to find the OPDS catalog URL, the KOReader sync widgets, or the
Hardcover connection state.

The unmatched inbox combines the two "this thing → tracked Book"
queues — library files awaiting a manual link and KOReader document
hashes awaiting their first bind — onto one page with a filter chip,
so a user with both kinds of unmatched items doesn't have to flip
between two pages to clear them out.

Per-feature pages (library browser, KOReader cadence/sessions/devices/
unmatched, library uploader) keep their own views — this module only
adds the index hub and the inbox. The new URL prefix lives in
``reading/urls.py``.
"""

from __future__ import annotations

import datetime

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from app.models import Status
from integrations.koreader_stats import (
    CADENCE_WINDOW_DAYS,
    aggregate_reading_time,
    compute_daily_cadence,
    compute_sessions,
)
from integrations.models import (
    HardcoverIntegration,
    KOReaderBookMapping,
    KOReaderProgressEvent,
)
from library.models import LibraryFile

# How many days of cadence we light up on the hub. The full heatmap lives at
# /reading/koreader/cadence; the hub only shows the last week so the page
# stays scannable.
HUB_CADENCE_DAYS = 7
# Per-rail row caps so the hub stays one screen on a mid-size laptop.
CURRENTLY_READING_LIMIT = 6
RECENT_SESSIONS_LIMIT = 8
STUCK_BOOKS_LIMIT = 6
STUCK_DAYS = 30


@require_GET
@login_required
def reading_index(request):
    """Render the /reading/ hub.

    Pulls from three sources without touching them: ``LibraryFile`` for
    upload counts, ``KOReaderBookMapping`` + ``KOReaderProgressEvent``
    for reading state, and ``HardcoverIntegration`` for sync status.
    The Book model is queried twice: once for the "currently reading"
    rail (status=In progress, ranked by ``progressed_at``) and once
    overlaid with KOReader mappings so the rail can show "0.2h read on
    gocolor7_2" without an N+1.
    """
    book_model = apps.get_model("app", "book")

    library_total = LibraryFile.objects.filter(user=request.user).count()
    library_unmatched = LibraryFile.objects.filter(
        user=request.user,
        item__isnull=True,
    ).count()

    koreader_unmatched_count = KOReaderBookMapping.objects.filter(
        user=request.user,
        item__isnull=True,
    ).count()
    koreader_synced_count = KOReaderBookMapping.objects.filter(
        user=request.user,
        item__isnull=False,
    ).count()
    koreader_device_count = (
        KOReaderProgressEvent.objects.filter(user=request.user)
        .values("device", "device_id")
        .distinct()
        .count()
    )

    hardcover_integration = HardcoverIntegration.objects.filter(
        user=request.user,
    ).first()

    # --- Currently reading rail -------------------------------------------
    currently_reading = list(
        book_model.objects.filter(
            user=request.user,
            status=Status.IN_PROGRESS.value,
        )
        .select_related("item")
        .order_by("-progressed_at", "-created_at")[:CURRENTLY_READING_LIMIT],
    )
    # Overlay KOReader mappings (last sync %, device, when) so the rail can
    # render the "0.2% · gocolor7_2 · 10h ago" line without a per-row query.
    item_ids = [b.item_id for b in currently_reading]
    if item_ids:
        mappings_by_item = {
            m.item_id: m
            for m in KOReaderBookMapping.objects.filter(
                user=request.user,
                item_id__in=item_ids,
            ).order_by("item_id", "-last_progress_at")
        }
        for book in currently_reading:
            book.koreader_mapping = mappings_by_item.get(book.item_id)
    else:
        for book in currently_reading:
            book.koreader_mapping = None

    # --- Cadence sparkline (last 7 days) ----------------------------------
    today = timezone.localdate()
    cadence_start = today - datetime.timedelta(days=HUB_CADENCE_DAYS - 1)
    week_cadence = list(
        compute_daily_cadence(request.user, since=cadence_start, until=today),
    )
    cadence_max = max((row["percent_read"] for row in week_cadence), default=0)
    if cadence_max > 0:
        for row in week_cadence:
            row["bar_height_pct"] = round(row["percent_read"] / cadence_max * 100)
    else:
        for row in week_cadence:
            row["bar_height_pct"] = 0
    # Headline minute count for the cadence card — full window so the user
    # gets a single "you read N minutes this week" number above the spark.
    window_sessions = [
        s
        for s in compute_sessions(request.user)
        if cadence_start <= s.start.date() <= today
    ]
    week_minutes, week_session_count, _avg = aggregate_reading_time(window_sessions)

    # --- Recent sessions (cross-book, latest N) ---------------------------
    all_sessions = compute_sessions(request.user)
    recent_sessions = all_sessions[:RECENT_SESSIONS_LIMIT]
    if recent_sessions:
        mapping_ids = {s.mapping_id for s in recent_sessions}
        recent_mappings = {
            m.id: m
            for m in KOReaderBookMapping.objects.filter(
                id__in=mapping_ids,
                user=request.user,
            ).select_related("item")
        }
        recent_rows = [
            {
                "session": s,
                "item": (
                    recent_mappings[s.mapping_id].item
                    if s.mapping_id in recent_mappings
                    else None
                ),
            }
            for s in recent_sessions
        ]
    else:
        recent_rows = []

    # --- Stuck books rail -------------------------------------------------
    # In-progress books whose last activity (progressed_at) is older than
    # STUCK_DAYS. Mirrors the "Did you finish?" nudge in IDEAS.md, scoped
    # to books only. Quick triage targets for Paused / Dropped / Completed.
    stuck_cutoff = timezone.now() - datetime.timedelta(days=STUCK_DAYS)
    stuck_books = list(
        book_model.objects.filter(
            user=request.user,
            status=Status.IN_PROGRESS.value,
            progressed_at__lt=stuck_cutoff,
        )
        .select_related("item")
        .order_by("progressed_at")[:STUCK_BOOKS_LIMIT],
    )

    return render(
        request,
        "reading/index.html",
        {
            "library_total": library_total,
            "library_unmatched": library_unmatched,
            "koreader_unmatched_count": koreader_unmatched_count,
            "koreader_synced_count": koreader_synced_count,
            "koreader_device_count": koreader_device_count,
            "hardcover_integration": hardcover_integration,
            "currently_reading": currently_reading,
            "week_cadence": week_cadence,
            "week_minutes": week_minutes,
            "week_hours": week_minutes / 60,
            "week_session_count": week_session_count,
            "recent_rows": recent_rows,
            "stuck_books": stuck_books,
            "hub_cadence_days": HUB_CADENCE_DAYS,
            "cadence_window_days": CADENCE_WINDOW_DAYS,
        },
    )


@require_GET
@login_required
def reading_unmatched(request):
    """Unified inbox for unmatched library files and KOReader hashes.

    Two sources land here, behind a single filter chip so the user can
    clear them out in one place:

    * ``library`` — uploaded epub files without an ``item`` binding.
      Each row shows the cover (if extracted), title/author (if pulled
      from the epub OPF), and the same shared match_book_form used by
      the KOReader unmatched page.
    * ``koreader`` — kosync document hashes without a ``mapping.item``.
      Each row also runs the existing ``find_match_for_hash`` filename
      heuristic so a row preselects to its best guess.

    Both source views (``/reading/library/?filter=unmatched`` and
    ``/reading/koreader/unmatched``) stay reachable and keep their
    flow-specific quirks (rename file, "Awaiting link" badge); this
    inbox is the at-a-glance triage surface.
    """
    from integrations.koreader_filename import find_match_for_hash  # noqa: PLC0415
    from reading.helpers import ranked_book_choices  # noqa: PLC0415

    source_filter = request.GET.get("source", "all")
    if source_filter not in {"all", "library", "koreader"}:
        source_filter = "all"

    bound_item_ids = set(
        KOReaderBookMapping.objects.filter(
            user=request.user,
            item__isnull=False,
        ).values_list("item_id", flat=True),
    )
    book_choices = ranked_book_choices(
        request.user,
        deprioritize_item_ids=bound_item_ids,
    )

    # POST handlers honour an opt-in ``next`` form field whose value
    # must be a same-host path under ``/reading/``. Passing the full
    # request path (including ``?source=...``) keeps the user pinned to
    # their current filter chip after a bind.
    next_url = request.get_full_path()

    library_rows: list[dict[str, object]] = []
    if source_filter in {"all", "library"}:
        library_rows = [
            {"library_file": lf, "hidden_fields": {"next": next_url}}
            for lf in LibraryFile.objects.filter(
                user=request.user,
                item__isnull=True,
            ).order_by("-updated_at")
        ]

    koreader_rows: list[dict[str, object]] = []
    if source_filter in {"all", "koreader"}:
        koreader_rows = [
            {
                "mapping": mapping,
                "filename_match_item": find_match_for_hash(
                    request.user,
                    mapping.document_hash,
                ),
                "hidden_fields": {
                    "document_hash": mapping.document_hash,
                    "next": next_url,
                },
            }
            for mapping in KOReaderBookMapping.objects.filter(
                user=request.user,
                item__isnull=True,
            ).order_by("-last_progress_at")
        ]

    return render(
        request,
        "reading/unmatched.html",
        {
            "source_filter": source_filter,
            "library_rows": library_rows,
            "koreader_rows": koreader_rows,
            "library_total": LibraryFile.objects.filter(
                user=request.user,
                item__isnull=True,
            ).count(),
            "koreader_total": KOReaderBookMapping.objects.filter(
                user=request.user,
                item__isnull=True,
            ).count(),
            "book_choices": book_choices,
        },
    )
