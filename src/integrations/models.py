"""Integration-owned models.

``PlayMBID`` stores MusicBrainz IDs resolved for a :class:`app.models.Play`
out-of-band via the ListenBrainz metadata lookup API. It's a separate
table (not columns on Play) so this fork's enrichment stays isolated
from upstream's core schema.

The presence of a row means a lookup was *attempted*. A row with all
MBID fields empty is a recorded miss, so backfill won't re-query it.

``WebhookEvent`` is a small rolling activity log for inbound Jellyfin /
Plex / Emby webhook hits — visible on the integrations settings page so
self-hosters can see when a webhook fired, whether it succeeded, and a
sample of the payload when it didn't. Capped per-user via a post-insert
trim (see ``integrations.views`` webhook handlers).

``HardcoverIntegration`` holds a user's encrypted Hardcover API token and
push settings; ``HardcoverBookMapping`` caches the Yamtrack-Item ↔
Hardcover-book resolution for OpenLibrary-sourced rows (Hardcover-sourced
items already carry the Hardcover book id as ``Item.media_id``).

``KOReaderBookMapping`` is the inbound side of KOReader's progress-sync
plugin (the kosync protocol). Each row binds a KOReader-computed file
hash (32-char hex MD5 of the ebook's binary content) to an optional
Yamtrack ``Item``. Rows are created on first PUT from a device; until
the user links a hash to a book in the integrations UI, the row sits
unmapped and only stores the raw progress / percentage so a future bind
can backfill the Book.
"""

from django.conf import settings
from django.db import models

from app.models import Item, Play


class PlayMBID(models.Model):
    """MusicBrainz IDs for a single Play (one-to-one, attempt marker)."""

    play = models.OneToOneField(
        Play,
        on_delete=models.CASCADE,
        related_name="mbid",
    )
    recording_mbid = models.CharField(max_length=36, blank=True, default="")
    release_mbid = models.CharField(max_length=36, blank=True, default="")
    artist_mbid = models.CharField(max_length=36, blank=True, default="")
    checked_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        """Return a short label."""
        return f"MBID for play {self.play_id}: {self.recording_mbid or '(miss)'}"

    @property
    def has_any(self):
        """True if at least one MBID was resolved."""
        return bool(self.recording_mbid or self.release_mbid or self.artist_mbid)


class WebhookEvent(models.Model):
    """Single inbound webhook hit recorded for self-hoster visibility."""

    EVENTS_PER_USER_CAP = 100

    class Source(models.TextChoices):
        """Where the inbound webhook came from."""

        JELLYFIN = "jellyfin", "Jellyfin"
        PLEX = "plex", "Plex"
        EMBY = "emby", "Emby"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="webhook_events",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=20, choices=Source.choices)
    ok = models.BooleanField(default=False)
    status_code = models.PositiveSmallIntegerField(default=0)
    title = models.CharField(max_length=255, blank=True, default="")
    error = models.TextField(blank=True, default="")
    payload_sample = models.TextField(blank=True, default="")

    class Meta:
        """Newest-first lets the integrations panel and trim query share an index."""

        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        """Short label for admin / shell."""
        return (
            f"{self.source} {'ok' if self.ok else 'error'} "
            f"{self.created_at:%Y-%m-%d %H:%M}"
        )

    @classmethod
    def record(
        cls, *, user, source, ok, status_code, title="", error="", payload_sample=""
    ):
        """Insert an event and trim older rows beyond the per-user cap.

        The trim uses a single query keyed on the (user, -created_at) index
        so the rolling log doesn't grow unbounded. Wrapped here (not in the
        view) so any future caller stays consistent.
        """
        cls.objects.create(
            user=user,
            source=source,
            ok=ok,
            status_code=status_code,
            title=title[:255],
            error=error[:4000],
            payload_sample=payload_sample[:2000],
        )
        if user is None:
            return
        # Keep only the most recent CAP events for this user.
        keep_ids = list(
            cls.objects.filter(user=user)
            .order_by("-created_at")
            .values_list("id", flat=True)[: cls.EVENTS_PER_USER_CAP]
        )
        cls.objects.filter(user=user).exclude(id__in=keep_ids).delete()


class HardcoverIntegration(models.Model):
    """A user's connected Hardcover account.

    One row per Yamtrack user. ``api_token`` is Fernet-encrypted via
    ``integrations.imports.helpers.encrypt`` so a DB dump alone can't be
    replayed against the Hardcover API. ``hardcover_user_id`` is cached on
    connect so the push task doesn't have to ``me { id }`` every time.

    ``enabled`` is the kill switch: leaving the integration connected but
    paused. ``last_pushed_at`` is a coarse "we did something successfully"
    timestamp for the settings UI; per-row timing for echo suppression
    lives on ``Book.last_hardcover_sync_at`` instead.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hardcover",
    )
    api_token = models.TextField()
    hardcover_user_id = models.PositiveIntegerField(null=True, blank=True)
    hardcover_username = models.CharField(max_length=255, blank=True, default="")
    enabled = models.BooleanField(default=True)
    last_pushed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    last_error_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        """Display the linked Hardcover username, or pk fallback."""
        return f"Hardcover<{self.hardcover_username or self.pk}>"


class HardcoverBookMapping(models.Model):
    """Cached Yamtrack ``Item`` → Hardcover ``book_id`` resolution.

    Only stores cross-source matches: when ``Item.source == 'hardcover'``,
    ``Item.media_id`` IS the Hardcover book id, so no row is needed. For
    ``source == 'openlibrary'`` (or ``'manual'``), the resolver looks up
    via ISBN-13 first, then a title+author search, and caches the winner
    here so subsequent pushes skip the round-trip.
    """

    class MatchMethod(models.TextChoices):
        """How a Yamtrack Item was matched to its Hardcover counterpart."""

        DIRECT_ID = "direct_id", "Direct ID"
        ISBN = "isbn", "ISBN-13"
        TITLE_AUTHOR = "title_author", "Title + Author search"
        MANUAL = "manual", "Manual override"

    item = models.OneToOneField(
        Item,
        on_delete=models.CASCADE,
        related_name="hardcover_mapping",
    )
    hardcover_book_id = models.PositiveIntegerField()
    hardcover_edition_id = models.PositiveIntegerField(null=True, blank=True)
    match_method = models.CharField(
        max_length=16,
        choices=MatchMethod.choices,
        default=MatchMethod.ISBN,
    )
    last_verified_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        """Item id + resolved Hardcover book id."""
        return f"Item {self.item_id} → HC book {self.hardcover_book_id}"


class KOReaderBookMapping(models.Model):
    """Per-user binding of a KOReader file hash to a Yamtrack book Item.

    The kosync protocol keys every PUT on a 32-char MD5 of the ebook
    file's contents — KOReader has no concept of ISBN, OpenLibrary id, or
    any other metadata identifier the rest of the app uses, so a mapping
    table is the only way to bridge the two. ``item`` is nullable: when
    KOReader pushes progress for a hash we've never seen, we create the
    row in unbound state and surface it in the integrations settings
    page for the user to link manually. ``last_*`` columns persist the
    raw kosync payload so a delayed bind can replay it onto the Book.

    ``(user, document_hash)`` is the natural key. The same physical
    file shared between two users still gets independent rows (KOReader
    progress is private; we don't want one user's reading to flow into
    another's Book row).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="koreader_mappings",
    )
    document_hash = models.CharField(
        max_length=32,
        help_text="32-char hex MD5 KOReader computes per ebook file.",
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="koreader_mappings",
    )
    last_progress = models.TextField(
        blank=True,
        default="",
        help_text="Opaque KOReader position string (epubcfi or xpointer).",
    )
    last_percentage = models.FloatField(default=0.0)
    last_device = models.CharField(max_length=255, blank=True, default="")
    last_device_id = models.CharField(max_length=64, blank=True, default="")
    last_progress_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Newest-bound first; one row per (user, document_hash)."""

        ordering = ["-last_progress_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document_hash"],
                name="koreader_unique_user_document",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "document_hash"]),
        ]

    def __str__(self):
        """Short label for admin / shell."""
        return (
            f"KOReader {self.document_hash[:8]}… → "
            f"{self.item_id or 'unbound'} (user {self.user_id})"
        )
