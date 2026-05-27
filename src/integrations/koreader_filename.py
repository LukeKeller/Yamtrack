"""Filename-mode auto-matching for KOReader kosync.

KOReader's kosync plugin can be configured to hash either the file's
*partial bytes* or its *filename*. This module assumes filename mode
— the wire ``document`` hash is ``md5(basename)``. That lets us
auto-bind incoming hashes to tracked books at sync-time *without*
ever seeing the file: we just precompute ``md5(<title>.epub)`` for
each Book in the user's library and look the incoming hash up.

The match is **exact** — KOReader sends the OS basename verbatim
(no case folding, no path), so ``Foo.epub`` and ``foo.epub`` produce
different document hashes. The helper generates a small set of
plausible filename variants per Item (different extensions, a
lower-cased variant) but it can't catch every renaming convention
out there. When auto-match misses, the user can either:

* Rename their KOReader file to one of the expected filenames, then
  let the next sync auto-bind it; or
* Pick the book manually on ``/koreader/unmatched`` (existing flow).

Heuristic: we keep candidate generation deliberately small. Three
md5s per Book x a few hundred Books = fast and bounded. The full
candidate set per user fits in a single dict; no DB index needed
beyond the existing ``(user, document_hash)`` uniqueness on
``KOReaderBookMapping``.
"""

from __future__ import annotations

import hashlib

from django.apps import apps

from app.models import MediaTypes

# Extensions KOReader recognises that we generate filename variants
# for. Order matters for the "expected filename" hint in the UI —
# .epub comes first because it's by far the most common.
_KNOWN_EXTENSIONS = (".epub", ".pdf", ".cbz", ".cbr", ".mobi", ".azw3", ".fb2")


def _md5_hex(value):
    """Return the lowercase hex md5 of ``value`` (str or bytes)."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


def candidate_filenames(item):
    """Return plausible KOReader filenames for ``item``.

    Generates ``<title>.<ext>`` and ``<title-lowercased>.<ext>`` for
    each known extension. Returns a list with duplicates removed and
    order preserved — the first entry is the "primary" guess we
    surface in the UI as the rename hint.

    Returns an empty list when the item has no title (defensive — every
    Item should have one, but a corrupt import row shouldn't crash
    the kosync hot path).
    """
    title = (item.title or "").strip()
    if not title:
        return []

    stems = [title]
    if title.lower() != title:
        stems.append(title.lower())

    candidates = []
    seen = set()
    for stem in stems:
        for ext in _KNOWN_EXTENSIONS:
            name = f"{stem}{ext}"
            if name not in seen:
                seen.add(name)
                candidates.append(name)
    return candidates


def candidate_hashes(item):
    """Return ``{hash_hex: filename}`` for all candidate filenames."""
    return {_md5_hex(name): name for name in candidate_filenames(item)}


def primary_expected_filename(item):
    """Return the ``<title>.epub`` rename hint we display in the UI."""
    candidates = candidate_filenames(item)
    return candidates[0] if candidates else None


def find_match_for_hash(user, document_hash):
    """Find the user's Book whose filename-hash matches ``document_hash``.

    Walks every Book the user has tracked, computes the small set of
    candidate hashes per Item, and returns the first Item that hits.
    Returns ``None`` when nothing matches.

    O(N) over the user's library — fine for the kosync hot path
    because N is typically <500 and each per-Item md5 set is ~10
    entries. If a heavier user ever cares about latency we can move
    to a per-user precomputed dict cached in Redis; today this is
    overkill.
    """
    if not document_hash:
        return None

    book_model = apps.get_model("app", MediaTypes.BOOK.value)
    qs = book_model.objects.filter(user=user).select_related("item")
    for book in qs:
        if document_hash in candidate_hashes(book.item):
            return book.item
    return None
