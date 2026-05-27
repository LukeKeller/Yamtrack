"""Library upload helpers — epub parsing, book matching, filename rules.

Three concerns live here, all called from the upload view and OPDS feed:

* ``parse_epub_metadata`` cracks an .epub OPF and returns title / author /
  language / ISBN / cover bytes. Failures are non-fatal — an upload that
  has no parseable OPF still gets stored with the original filename and
  the user can edit metadata in the library browser.
* ``find_matching_book`` does the auto-link: an upload whose normalised
  title equals exactly one of the user's tracked Books gets bound to
  that Book's Item, so kosync auto-bind works immediately on next sync.
  Conservative on purpose — multiple-match → unmatched, surfaced for
  manual linking in the browser.
* ``canonical_filename_for`` / ``compute_koreader_filename_md5`` enforce
  the "what KOReader saves the file as" contract. ``<title>.<ext>`` with
  filesystem-unsafe characters stripped; md5 of that string is the
  kosync auto-bind key.

ISBN-based matching is intentionally absent from MVP — Yamtrack's
``Item.media_id`` for OpenLibrary/Hardcover books isn't an ISBN, so
auto-matching by ISBN would require a provider round-trip per upload
(rate-limit risk on bulk imports). The ISBN is still extracted from the
OPF and stored on ``LibraryFile`` so a future re-match command can use
it; for now the title-uniqueness match catches the common case.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from django.apps import apps
from django.core.files.base import ContentFile
from django.utils.text import slugify
from ebooklib import ITEM_COVER, ITEM_IMAGE, epub
from unidecode import unidecode

from app.models import MediaTypes

logger = logging.getLogger(__name__)

# Characters disallowed by both Windows and KOReader-on-eink filesystems.
# Not exhaustive — just enough so a title with a colon doesn't blow up the
# OPDS download or the on-disk path.
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Strings users commonly stick at the start of a title; strip for matching
# but keep verbatim in the visible title field.
_TITLE_LEADING_ARTICLES = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
# Trailing edition / series suffix we strip for matching.
_TITLE_TRAILING_NOISE = re.compile(
    r"\s*(?:\(.*?\)|\[.*?\]|:.*|--?\s*\d+(?:st|nd|rd|th)?\s+edition?.*)$",
    re.IGNORECASE,
)

DEFAULT_EXTENSION = ".epub"
MAX_TITLE_LEN = 200
ISBN_13_LEN = 13
ISBN_10_LEN = 10


def _md5_hex(value):
    """Return the lowercase hex md5 of ``value`` (str or bytes)."""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


def _clean_filename_stem(text):
    """Strip filesystem-unsafe chars but preserve human-readable spacing."""
    cleaned = _UNSAFE_FILENAME_CHARS.sub("", text or "").strip().strip(".")
    return cleaned[:MAX_TITLE_LEN] or "untitled"


def canonical_filename_for(title, extension):
    """Build the basename KOReader will save under.

    Used both to write the user-facing OPDS filename and to compute the
    kosync auto-bind key (md5 of this string). Stable across re-uploads
    of the same metadata so a re-upload still binds to existing kosync
    mappings.
    """
    ext = (extension or DEFAULT_EXTENSION).lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    stem = _clean_filename_stem(title or "untitled")
    return f"{stem}{ext}"


def compute_koreader_filename_md5(canonical_filename):
    """md5 of the canonical filename — the kosync auto-bind key."""
    return _md5_hex(canonical_filename)


def _normalise_title(title):
    """Lower-case, transliterate, strip articles & trailing noise."""
    if not title:
        return ""
    text = unidecode(title).lower().strip()
    text = _TITLE_TRAILING_NOISE.sub("", text)
    text = _TITLE_LEADING_ARTICLES.sub("", text)
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalise_isbn(value):
    """Return digits-only ISBN (or X-suffixed ISBN-10), or '' if no digits."""
    if not value:
        return ""
    return re.sub(r"[^0-9Xx]", "", value).upper()


def parse_epub_metadata(file_path):
    """Extract title/author/language/ISBN/cover bytes from an .epub.

    Returns a dict with every key always present so callers don't have to
    defensively ``.get``. On any parse error we log and return the empty
    shape — the upload still succeeds, the user can fill metadata in by
    hand from the library browser.
    """
    empty = {
        "title": "",
        "author": "",
        "language": "",
        "isbn_13": "",
        "isbn_10": "",
        "cover_bytes": None,
        "cover_mime": "",
        "cover_ext": "",
    }
    try:
        book = epub.read_epub(str(file_path), options={"ignore_ncx": True})
    except Exception:
        logger.exception("Failed to read epub at %s", file_path)
        return empty

    def _first(field):
        values = book.get_metadata("DC", field)
        if not values:
            return ""
        value, _attrs = values[0]
        return (value or "").strip()

    title = _first("title")
    author = _first("creator")
    language = _first("language")

    isbn_13, isbn_10 = _extract_isbns(book)
    cover_bytes, cover_mime, cover_ext = _extract_cover(book)

    return {
        "title": title,
        "author": author,
        "language": language,
        "isbn_13": isbn_13,
        "isbn_10": isbn_10,
        "cover_bytes": cover_bytes,
        "cover_mime": cover_mime,
        "cover_ext": cover_ext,
    }


def _extract_isbns(book):
    """Return (isbn_13, isbn_10) parsed from epub DC identifiers."""
    isbn_13 = ""
    isbn_10 = ""
    for value, _attrs in book.get_metadata("DC", "identifier") or []:
        raw = _normalise_isbn(value)
        if len(raw) == ISBN_13_LEN and raw.isdigit():
            isbn_13 = raw
        elif len(raw) == ISBN_10_LEN and not isbn_10:
            isbn_10 = raw
    return isbn_13, isbn_10


def _extract_cover(book):
    """Return (cover_bytes, mime, file_ext) for the first cover image, or empties."""
    for item in book.get_items_of_type(ITEM_COVER):
        return item.content, item.media_type, _ext_for_mime(item.media_type)
    for item in book.get_items_of_type(ITEM_IMAGE):
        if "cover" in (item.file_name or "").lower():
            return item.content, item.media_type, _ext_for_mime(item.media_type)
    return None, "", ""


def _ext_for_mime(mime):
    """Normalise an image MIME type to a filesystem extension."""
    ext = Path(mime.replace("image/", ".")).suffix or ".jpg"
    return ".jpg" if ext == ".jpeg" else ext


def find_matching_book(user, title, author=""):  # noqa: ARG001
    """Return the user's Book Item matching ``title``, or None.

    Conservative auto-link: we only match when exactly one Book in the
    user's library normalises to the same title. Multiple candidates
    (anthologies, classics, translations) leave the upload unmatched so
    the user picks in the browser — a wrong auto-bind would silently
    route kosync pushes into the wrong Book row.

    Author is currently advisory metadata (not all Items expose an
    author without a provider round-trip), but the signature accepts it
    so the call sites stay future-proof when we wire ISBN matching.
    """
    if not title:
        return None
    upload_title = _normalise_title(title)
    if not upload_title:
        return None

    book_model = apps.get_model("app", MediaTypes.BOOK.value)
    matches = [
        book.item
        for book in book_model.objects.filter(user=user).select_related("item")
        if _normalise_title(book.item.title) == upload_title
    ]
    return matches[0] if len(matches) == 1 else None


def stream_iter(django_file, chunk_size=64 * 1024):
    """Yield chunks from a Django FieldFile for FileResponse streaming."""
    django_file.open("rb")
    try:
        while True:
            chunk = django_file.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        django_file.close()


def save_cover_for(library_file, cover_bytes, cover_ext):
    """Attach an extracted epub cover (caller must save the LibraryFile)."""
    if not cover_bytes:
        return
    stem = slugify(library_file.title or "cover")[:50] or "cover"
    name = f"{stem}{cover_ext or '.jpg'}"
    library_file.cover.save(name, ContentFile(cover_bytes), save=False)
