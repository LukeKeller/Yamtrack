"""Library browser + upload views.

The browser at ``/library/`` is a grid of every file the current user has
uploaded, with per-row actions to manually link an unmatched file to a
tracked Book, rename it (which rotates the kosync auto-bind hash), or
delete it. The upload at ``/library/upload`` accepts mixed .epub / .zip
uploads — zips are walked recursively for epub members and non-epub
files are silently skipped (see [[project-library-opds-scope]]).

OPDS lives in ``opds.py`` so the auth model (HTTP Basic against
``User.token`` for the KOReader catalog browser) doesn't have to share a
file with the session-authenticated browser views.
"""

from __future__ import annotations

import contextlib
import logging
import tempfile
import zipfile
from pathlib import Path

from django.apps import apps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.core.files import File
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from app.providers import services
from app.providers.services import ProviderAPIError
from library.forms import LibraryUploadForm
from library.helpers import (
    canonical_filename_for,
    compute_koreader_filename_md5,
    parse_epub_metadata,
    save_cover_for,
)
from library.models import LibraryFile
from library.tasks import auto_match_library_file

logger = logging.getLogger(__name__)

EPUB_EXT = ".epub"
ZIP_EXT = ".zip"
EPUB_MIME = "application/epub+zip"


@require_GET
@login_required
def library_index(request):
    """Grid of the user's uploads with filter chips + per-row actions.

    The "Link to a tracked book" dropdown uses the shared
    ``ranked_book_choices`` helper so in-progress books float to the top
    — same ordering as the KOReader unmatched page. Previously this
    template just sorted alphabetically, which buried the current read
    behind hundreds of completed ones.
    """
    from reading.helpers import ranked_book_choices  # noqa: PLC0415

    filter_mode = request.GET.get("filter", "all")
    qs = LibraryFile.objects.filter(user=request.user).select_related("item")
    if filter_mode == "unmatched":
        qs = qs.filter(item__isnull=True)
    elif filter_mode == "matched":
        qs = qs.filter(item__isnull=False)

    book_choices = ranked_book_choices(request.user)

    return render(
        request,
        "library/index.html",
        {
            "files": list(qs),
            "filter_mode": filter_mode,
            "total_count": LibraryFile.objects.filter(user=request.user).count(),
            "unmatched_count": LibraryFile.objects.filter(
                user=request.user,
                item__isnull=True,
            ).count(),
            "book_choices": book_choices,
        },
    )


def _library_reading_history(library_file):
    """Compact KOReader reading summary for an uploaded file, or ``None``.

    Finds the KOReader mappings tied to this file — by the OPDS
    auto-bind hash (``document_hash == koreader_filename_md5``) and, when
    the file is provider-matched, by the bound ``Item`` — and aggregates
    their progress events into a single summary the detail page can
    render without an N+1. Returns ``None`` when there's no reading
    history yet (no mappings, or mappings with no events).

    Imports the stats helpers lazily so the (cheap) detail-page render
    for a file with no reading history doesn't pay the import cost.
    """
    from integrations.koreader_stats import (  # noqa: PLC0415
        aggregate_reading_time,
        compute_sessions,
    )

    mapping_model = apps.get_model("integrations", "KOReaderBookMapping")
    match = Q(document_hash=library_file.koreader_filename_md5)
    if library_file.item_id:
        match |= Q(item_id=library_file.item_id)
    mappings = list(
        mapping_model.objects.filter(match, user=library_file.user),
    )
    if not mappings:
        return None

    # Single-mapping common case filters at the query layer; the rare
    # multi-mapping case (OPDS hash plus an item bound by another route)
    # post-filters the per-user session list. Mirrors the book detail
    # page's ``_koreader_book_summary``.
    if len(mappings) == 1:
        sessions = compute_sessions(library_file.user, mapping=mappings[0])
    else:
        mapping_ids = {m.id for m in mappings}
        sessions = [
            s
            for s in compute_sessions(library_file.user)
            if s.mapping_id in mapping_ids
        ]
    if not sessions:
        return None

    total_minutes, session_count, _avg = aggregate_reading_time(sessions)
    latest = max(
        (m for m in mappings if m.last_progress_at is not None),
        key=lambda m: m.last_progress_at,
        default=None,
    )
    current_percentage = (
        round(latest.last_percentage * 100, 1) if latest is not None else None
    )
    return {
        "current_percentage": current_percentage,
        "total_minutes": total_minutes,
        "total_hours": total_minutes / 60,
        "session_count": session_count,
        "latest_mapping": latest,
        "last_progress_at": latest.last_progress_at if latest else None,
    }


@require_GET
@login_required
def library_detail(request, pk):
    """Details page for an uploaded book — matched or not.

    Every uploaded file gets a page here, even one that never resolved to
    a metadata provider. The page always renders from the epub OPF
    metadata stashed on the row (title/author/cover/language/ISBN) plus
    any KOReader reading history. When the file is provider-``MATCHED``
    it's enriched with the provider's synopsis/genres/page count and, if
    the user already tracks the book, their tracking state — with a
    "track this" CTA pointing at the canonical media details page
    otherwise.
    """
    from reading.helpers import ranked_book_choices  # noqa: PLC0415

    library_file = get_object_or_404(
        LibraryFile.objects.select_related("item"),
        pk=pk,
        user=request.user,
    )

    provider_metadata = None
    tracked_instance = None
    if library_file.item_id:
        item = library_file.item
        try:
            provider_metadata = services.get_media_metadata(
                item.media_type,
                item.media_id,
                item.source,
            )
        except ProviderAPIError:
            # A provider hiccup shouldn't 500 the page — fall back to the
            # epub OPF metadata we already have on the row.
            logger.warning(
                "Provider metadata fetch failed for library file %s (item %s)",
                pk,
                item.pk,
            )
        book_model = apps.get_model("app", "book")
        tracked_instance = (
            book_model.objects.filter(user=request.user, item=item)
            .select_related("item")
            .first()
        )

    return render(
        request,
        "library/detail.html",
        {
            "library_file": library_file,
            "provider_metadata": provider_metadata,
            "tracked_instance": tracked_instance,
            "reading_history": _library_reading_history(library_file),
            "book_choices": ranked_book_choices(request.user),
        },
    )


@login_required
def library_upload(request):
    """Upload page: GET shows the form, POST ingests files + zips."""
    if request.method == "POST":
        form = LibraryUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploads = form.cleaned_data["files"]
            summary = _ingest_uploads(request.user, uploads)
            _flash_upload_summary(request, summary)
            return redirect("library_index")
    else:
        form = LibraryUploadForm()

    return render(request, "library/upload.html", {"form": form})


def _library_post_redirect(request):
    """Resolve a safe redirect target after a library link/rename/delete POST.

    Honours an opt-in ``next`` form field whose value must be a same-host
    path under ``/reading/`` — so the unified inbox at
    ``/reading/unmatched`` can keep the user pinned to their filter
    after a bind. Falls back to the library browser.
    """
    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/reading/"):
        return redirect(next_url)
    return redirect("library_index")


@require_POST
@login_required
def library_link(request, pk):
    """Manually bind a LibraryFile to a Book ``Item``.

    Redirect target honours an opt-in ``next`` form field so binds from
    the unified /reading/unmatched inbox return there.
    """
    library_file = get_object_or_404(LibraryFile, pk=pk, user=request.user)
    item_id = (request.POST.get("item_id") or "").strip()

    if not item_id:
        library_file.item = None
        library_file.match_status = LibraryFile.MatchStatus.UNRESOLVED
        library_file.match_method = LibraryFile.MatchMethod.NONE
        library_file.matched_at = None
        library_file.save(
            update_fields=[
                "item",
                "match_status",
                "match_method",
                "matched_at",
                "updated_at",
            ],
        )
        messages.info(request, f"Unlinked {library_file.canonical_filename}.")
        return _library_post_redirect(request)

    item_model = apps.get_model("app", "Item")
    try:
        item = item_model.objects.get(pk=item_id, media_type="book")
    except (ObjectDoesNotExist, ValueError):
        messages.error(request, "Book not found in your library.")
        return _library_post_redirect(request)

    library_file.item = item
    library_file.match_status = LibraryFile.MatchStatus.MATCHED
    library_file.match_method = LibraryFile.MatchMethod.MANUAL
    library_file.matched_at = timezone.now()
    library_file.save(
        update_fields=[
            "item",
            "match_status",
            "match_method",
            "matched_at",
            "updated_at",
        ],
    )
    messages.success(
        request,
        f"Linked {library_file.canonical_filename} to {item.title}.",
    )
    return _library_post_redirect(request)


@require_POST
@login_required
def library_delete(request, pk):
    """Delete a LibraryFile + its on-disk payload."""
    library_file = get_object_or_404(LibraryFile, pk=pk, user=request.user)
    name = library_file.canonical_filename
    # FieldFile.delete() unlinks the on-disk file; instance.delete()
    # cleans the DB row. Order matters: file first so a failed unlink
    # doesn't orphan the DB record.
    try:
        library_file.file.delete(save=False)
    except Exception:
        logger.exception("Failed to remove on-disk file for LibraryFile %s", pk)
    if library_file.cover:
        try:
            library_file.cover.delete(save=False)
        except Exception:
            logger.exception("Failed to remove cover for LibraryFile %s", pk)
    library_file.delete()
    messages.info(request, f"Deleted {name}.")
    return redirect("library_index")


@require_POST
@login_required
def library_rename(request, pk):
    """Rename canonical_filename — rotates the kosync auto-bind hash."""
    library_file = get_object_or_404(LibraryFile, pk=pk, user=request.user)
    new_name = (request.POST.get("canonical_filename") or "").strip()
    if not new_name:
        messages.error(request, "Filename can't be empty.")
        return redirect("library_index")
    # Force the right extension so a rename can't accidentally break
    # KOReader's format detection.
    if not new_name.lower().endswith(EPUB_EXT):
        new_name = f"{Path(new_name).stem}{EPUB_EXT}"

    new_hash = compute_koreader_filename_md5(new_name)
    if (
        LibraryFile.objects.filter(
            user=request.user,
            koreader_filename_md5=new_hash,
        )
        .exclude(pk=library_file.pk)
        .exists()
    ):
        messages.error(
            request,
            f"Another file already uses '{new_name}' — pick a different name.",
        )
        return redirect("library_index")

    library_file.canonical_filename = new_name
    library_file.koreader_filename_md5 = new_hash
    library_file.save(
        update_fields=[
            "canonical_filename",
            "koreader_filename_md5",
            "updated_at",
        ],
    )
    messages.success(request, f"Renamed to {new_name}.")
    return redirect("library_index")


def _ingest_uploads(user, uploaded_files):
    """Demux uploads into epub ingest calls; return summary counts."""
    summary = {"imported": 0, "skipped_non_epub": 0, "duplicates": 0, "errors": []}
    for uploaded in uploaded_files:
        suffix = Path(uploaded.name).suffix.lower()
        if suffix == EPUB_EXT:
            _ingest_one_epub_from_django_file(user, uploaded, uploaded.name, summary)
        elif suffix == ZIP_EXT:
            _ingest_zip(user, uploaded, summary)
        else:
            summary["skipped_non_epub"] += 1
    return summary


def _ingest_zip(user, uploaded_zip, summary):
    """Walk a zip for .epub members; non-epub members are ignored."""
    # zipfile needs a seekable file; an InMemoryUploadedFile already is,
    # a TemporaryUploadedFile gives us .file (a real file object). Both
    # are fine to hand to ZipFile directly.
    try:
        with zipfile.ZipFile(uploaded_zip) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if not name.lower().endswith(EPUB_EXT):
                    summary["skipped_non_epub"] += 1
                    continue
                # Defensive: drop zip-slip names. We aren't extracting
                # by member-name path, but skip anything that looks
                # weird so logs stay clean.
                base = Path(name).name
                if not base or base.startswith("."):
                    summary["skipped_non_epub"] += 1
                    continue
                with zf.open(info) as member_fp:
                    _ingest_one_epub_from_stream(user, member_fp, base, summary)
    except zipfile.BadZipFile:
        summary["errors"].append(f"{uploaded_zip.name}: not a valid zip file")


def _ingest_one_epub_from_django_file(user, django_file, basename, summary):
    """Ingest a Django UploadedFile that is itself a single .epub."""
    django_file.seek(0)
    _ingest_one_epub_from_stream(user, django_file, basename, summary)


def _ingest_one_epub_from_stream(user, stream, basename, summary):
    """Persist one .epub stream; parse metadata; enqueue provider match.

    Streams the upload to a tempfile first so ebooklib can crack the
    OPF off a real path, then re-streams it into the LibraryFile via
    Django's FileField. Avoids loading the full file into memory twice
    and keeps the on-disk write atomic.

    New rows start ``UNRESOLVED``; once saved we enqueue
    ``auto_match_library_file`` to resolve them to a metadata provider
    (Hardcover when connected, else OpenLibrary). Runs inline under
    CELERY eager in tests.
    """
    with tempfile.NamedTemporaryFile(suffix=EPUB_EXT, delete=False) as tmp:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            tmp.write(chunk)
        tmp_path = Path(tmp.name)

    try:
        metadata = parse_epub_metadata(tmp_path)
        title = metadata["title"] or Path(basename).stem
        canonical = canonical_filename_for(title, EPUB_EXT)
        koreader_hash = compute_koreader_filename_md5(canonical)

        if LibraryFile.objects.filter(
            user=user,
            koreader_filename_md5=koreader_hash,
        ).exists():
            summary["duplicates"] += 1
            return

        library_file = LibraryFile(
            user=user,
            original_filename=basename[:255],
            canonical_filename=canonical,
            koreader_filename_md5=koreader_hash,
            mime_type=EPUB_MIME,
            size_bytes=tmp_path.stat().st_size,
            title=(metadata["title"] or title)[:500],
            author=metadata["author"][:500],
            language=metadata["language"][:20],
            isbn_13=metadata["isbn_13"][:13],
            isbn_10=metadata["isbn_10"][:10],
        )

        with tmp_path.open("rb") as fp:
            library_file.file.save(canonical, File(fp), save=False)

        if metadata["cover_bytes"]:
            save_cover_for(
                library_file,
                metadata["cover_bytes"],
                metadata["cover_ext"],
            )

        try:
            with transaction.atomic():
                library_file.save()
        except IntegrityError:
            # Race between the dedup check above and the unique
            # constraint — same user uploaded the same file twice in
            # the same form. Clean up the on-disk write and count it.
            try:
                library_file.file.delete(save=False)
            except Exception:
                logger.exception("Cleanup after duplicate insert failed")
            summary["duplicates"] += 1
            return

        auto_match_library_file.delay(library_file.id)
        summary["imported"] += 1
    finally:
        with contextlib.suppress(OSError):
            tmp_path.unlink()


def _flash_upload_summary(request, summary):
    """Translate ingest counts into one or more Django messages."""
    if summary["imported"]:
        messages.success(
            request,
            f"Imported {summary['imported']} epub"
            f"{'s' if summary['imported'] != 1 else ''}.",
        )
    if summary["duplicates"]:
        messages.info(
            request,
            f"Skipped {summary['duplicates']} duplicate"
            f"{'s' if summary['duplicates'] != 1 else ''} (already in your library).",
        )
    if summary["skipped_non_epub"]:
        messages.info(
            request,
            f"Ignored {summary['skipped_non_epub']} non-epub file"
            f"{'s' if summary['skipped_non_epub'] != 1 else ''}.",
        )
    for err in summary["errors"]:
        messages.error(request, err)
    if (
        not summary["imported"]
        and not summary["duplicates"]
        and not summary["skipped_non_epub"]
        and not summary["errors"]
    ):
        messages.warning(request, "No files were uploaded.")
