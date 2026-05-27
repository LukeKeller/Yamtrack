"""LibraryFile — user-uploaded ebook hosted by Yamtrack.

The library is the second half of the KOReader auto-bind story. KOReader's
kosync wire protocol only carries an opaque 32-char file hash; it does not
send title, author, ISBN, or filename. So the only way Yamtrack can bind
a kosync push to a tracked Book without manual user action is to know the
hash *before* the sync arrives. Two paths achieve that:

1. ``koreader_filename.find_match_for_hash`` (shipped ynh130) guesses
   ``md5(<book-title>.epub)`` for every book in the user's library.
2. **This module.** When the user uploads the book through Yamtrack and
   downloads it onto their KOReader device via the OPDS server, we control
   the filename — so we know ``md5(canonical_filename)`` at upload time and
   can stash it on the ``LibraryFile`` row for instant lookup on the next
   kosync push. 100% match rate, no rename dance.

Storage path uses a per-user UUID so two users uploading the same file get
isolated copies (avoids cross-user leakage on cover images / DRM-stripped
copies). The on-disk basename is opaque; the user-facing basename is
``canonical_filename`` and is what OPDS serves via Content-Disposition.

The (user, koreader_filename_md5) uniqueness constraint is what makes
the kosync auto-bind lookup O(1) instead of O(library). Pre-computed at
upload time, cheap to query on every kosync PUT.
"""

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models

from app.models import Item


def library_file_upload_path(instance, filename):
    """Per-user UUID-named path so uploads never collide across users."""
    ext = Path(filename).suffix.lower()
    return f"library/files/{instance.user_id}/{uuid.uuid4().hex}{ext}"


def library_cover_upload_path(instance, filename):
    """Covers live alongside files but in a sibling dir for tidy backups."""
    ext = Path(filename).suffix.lower() or ".jpg"
    return f"library/covers/{instance.user_id}/{uuid.uuid4().hex}{ext}"


class LibraryFile(models.Model):
    """A user-owned ebook file hosted by Yamtrack for OPDS + auto-bind.

    ``canonical_filename`` is the basename we want KOReader to save the
    file under once downloaded; ``koreader_filename_md5`` is its md5 and
    serves as the kosync auto-bind key. Both are computed once at upload
    time (or when the user renames via the UI) — keeping them as columns
    lets the kosync hot path stay a single indexed lookup.

    ``item`` is nullable: an upload that doesn't match an existing Book on
    ISBN or title+author lands in unmatched state, and the user can link
    it manually from the library browser. When linked (or auto-matched),
    a kosync push for ``koreader_filename_md5`` binds straight onto the
    Book without ever passing through ``/koreader/unmatched``.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="library_files",
    )
    file = models.FileField(upload_to=library_file_upload_path)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    canonical_filename = models.CharField(
        max_length=255,
        help_text="Basename OPDS serves and md5s. Auto-bind key.",
    )
    koreader_filename_md5 = models.CharField(
        max_length=32,
        db_index=True,
        help_text="md5(canonical_filename); matched against kosync document hashes.",
    )
    mime_type = models.CharField(max_length=100, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)
    title = models.CharField(max_length=500, blank=True, default="")
    author = models.CharField(max_length=500, blank=True, default="")
    language = models.CharField(max_length=20, blank=True, default="")
    isbn_13 = models.CharField(max_length=13, blank=True, default="", db_index=True)
    isbn_10 = models.CharField(max_length=10, blank=True, default="")
    cover = models.ImageField(
        upload_to=library_cover_upload_path,
        blank=True,
        null=True,
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="library_files",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Newest first; per-user filename hash uniqueness for O(1) auto-bind."""

        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "koreader_filename_md5"],
                name="library_unique_user_filename_md5",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "koreader_filename_md5"]),
        ]

    def __str__(self):
        """Short label for admin / shell."""
        return f"{self.canonical_filename} (user {self.user_id})"
