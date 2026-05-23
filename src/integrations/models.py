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
"""

from django.conf import settings
from django.db import models

from app.models import Play


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
        return f"{self.source} {'ok' if self.ok else 'error'} {self.created_at:%Y-%m-%d %H:%M}"

    @classmethod
    def record(cls, *, user, source, ok, status_code, title="", error="", payload_sample=""):
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
