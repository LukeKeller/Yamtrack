"""Reading hub shared helpers.

Centralises logic that's reused by the three "book identity" flows
(library file matching, KOReader hash matching, and — once inbound
Hardcover sync lands — Hardcover unmatched-mapping resolution). Before
this module existed, the koreader_unmatched view carried the only copy
of the "rank books by status" logic and the library_index template just
showed an alphabetical list, which was a regression when a user with
hundreds of tracked books needed to scroll to find their current read.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from django.apps import apps

from app.models import Status

if TYPE_CHECKING:
    from collections.abc import Iterable


def ranked_book_choices(
    user,
    *,
    deprioritize_item_ids: Iterable[int] | None = None,
) -> list[dict[str, object]]:
    """Return ``[{"id": int, "title": str}, ...]`` ranked for a picker.

    Ranking (lower is higher in the dropdown):

    0. In-progress books NOT in ``deprioritize_item_ids`` — these are
       the "you are reading this right now" candidates, the most
       likely answer the user wants.
    1. In-progress books that ARE in ``deprioritize_item_ids`` — still
       in-progress, but already claimed by some other binding. Useful
       in the rare case where a user has two mappings for the same
       book (e.g. two epub editions).
    2. Everything else, alphabetical by title.

    Within each tier, books are sorted by most-recent ``progressed_at``
    (newest first), then title. Stable ordering on a refresh.

    The caller passes a User instance. ``deprioritize_item_ids`` is an
    iterable of Item IDs to push into tier 1 (typically the IDs already
    bound to a mapping; pass empty/None to skip).
    """
    book_model = apps.get_model("app", "book")
    bound = set(deprioritize_item_ids or [])

    rows = list(
        book_model.objects.filter(user=user)
        .select_related("item")
        .values("item_id", "item__title", "status", "progressed_at"),
    )

    def _rank(row: dict[str, object]) -> tuple:
        in_progress = row["status"] == Status.IN_PROGRESS.value
        already_bound = row["item_id"] in bound
        if in_progress and not already_bound:
            tier = 0
        elif in_progress:
            tier = 1
        else:
            tier = 2
        progressed = row["progressed_at"] or datetime.datetime.min.replace(
            tzinfo=datetime.UTC,
        )
        return (tier, -progressed.timestamp(), (row["item__title"] or "").lower())

    rows.sort(key=_rank)

    # De-duplicate by item_id (same Item could appear if a future schema
    # change adds a join that produces dupes; current schema can't, but
    # the guard is cheap insurance).
    seen: set[int] = set()
    choices: list[dict[str, object]] = []
    for row in rows:
        item_id = row["item_id"]
        if item_id in seen:
            continue
        seen.add(item_id)
        choices.append({"id": item_id, "title": row["item__title"]})
    return choices
