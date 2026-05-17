"""Template helpers for rendering MusicBrainz links on listen rows.

``mb_links_map`` batch-loads PlayMBID rows for a page of plays in one
query (avoids an N+1 in the history list); ``dict_get`` pulls one out
by play id in the template.
"""

from django import template

from integrations.models import PlayMBID

register = template.Library()


@register.simple_tag
def mb_links_map(plays):
    """Return ``{play_id: PlayMBID}`` for the given iterable of plays."""
    ids = [p.id for p in plays]
    if not ids:
        return {}
    return {m.play_id: m for m in PlayMBID.objects.filter(play_id__in=ids)}


@register.filter
def dict_get(mapping, key):
    """Look up ``key`` in ``mapping`` (returns None if absent)."""
    if not mapping:
        return None
    return mapping.get(key)
