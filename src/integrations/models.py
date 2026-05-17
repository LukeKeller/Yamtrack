"""Integration-owned models.

``PlayMBID`` stores MusicBrainz IDs resolved for a :class:`app.models.Play`
out-of-band via the ListenBrainz metadata lookup API. It's a separate
table (not columns on Play) so this fork's enrichment stays isolated
from upstream's core schema.

The presence of a row means a lookup was *attempted*. A row with all
MBID fields empty is a recorded miss, so backfill won't re-query it.
"""

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
