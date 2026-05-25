"""Per-user taste profile derived from rated / completed / dismissed media.

The profile is a pair of weighted genre bags — one positive (built from
items the user has scored highly or completed) and one negative (built
from items they dismissed on the Browse page or marked Dropped). A
match score for any candidate item is a normalized dot product against
those bags, clipped to ``0..100`` for display on cards.

Profiles are cached in Redis for 24h per (user, media_type). The cache
is invalidated by signals in ``app/signals.py`` whenever the user's
library, dismissals, or scores change so the next read rebuilds from
fresh state.
"""

from __future__ import annotations

import logging
from math import sqrt

from django.apps import apps
from django.core.cache import cache

from app.models import DismissedItem, MediaTypes, Sources, Status
from app.providers import services

logger = logging.getLogger(__name__)

PROFILE_TTL = 60 * 60 * 24  # 24h; signals invalidate sooner on changes
# Minimum number of positive signals (rated/completed items) before we
# trust the profile enough to surface match scores in the UI. Below this
# threshold the badge stays hidden — a 30% match built from one rating
# is noise, not signal.
MIN_POSITIVE_SIGNALS = 5
# Media types we can build a useful taste profile for. Limited to types
# that have rich genre metadata via TMDB; expand as other providers
# (IGDB for games, Hardcover for books) get genre extraction in
# ``_genres_for_item``.
SUPPORTED_MEDIA_TYPES = frozenset({MediaTypes.MOVIE.value, MediaTypes.TV.value})


def is_supported(media_type):
    """Return True when match scoring can run for this media_type."""
    return media_type in SUPPORTED_MEDIA_TYPES


def profile_cache_key(user_id, media_type):
    """Redis key for a user's per-type taste profile."""
    return f"taste_profile_v1_{user_id}_{media_type}"


def invalidate(user_id, media_type=None):
    """Drop cached profile(s) so the next read rebuilds.

    Called from save/delete/dismiss signals. When ``media_type`` is None
    we drop the profile for every supported type — score changes on a
    movie don't affect TV but it's cheap to clear both.
    """
    types = [media_type] if media_type else SUPPORTED_MEDIA_TYPES
    cache.delete_many([profile_cache_key(user_id, mt) for mt in types])


def build_profile(user, media_type):
    """Return ``{"pos": {...}, "neg": {...}, "n_pos": int, "n_neg": int}``.

    Positive weights come from items the user has actively engaged with:
    scored items (weight = score / 10) plus a small floor weight for
    Completed / In progress without an explicit score. Negative weights
    come from explicit dismissals and items marked Dropped.

    Result is cached on read; callers should treat the dict as
    read-only. An empty profile (``n_pos == 0``) is still cached so we
    don't re-query on every page load for fresh users.
    """
    if not is_supported(media_type):
        return _empty_profile()

    key = profile_cache_key(user.id, media_type)
    cached = cache.get(key)
    if cached is not None:
        return cached

    model = apps.get_model("app", media_type)
    media_rows = (
        model.objects.filter(user=user)
        .select_related("item")
        .only(
            "score",
            "status",
            "item__media_id",
            "item__source",
            "item__media_type",
        )
    )

    pos_weights = {}
    neg_weights = {}
    n_pos = 0
    n_neg = 0

    for row in media_rows:
        item = row.item
        genres = _genres_for_item(item.source, item.media_type, item.media_id)
        if not genres:
            continue

        if row.status == Status.DROPPED.value:
            weight = 1.0
            _accumulate(neg_weights, genres, weight)
            n_neg += 1
            continue

        weight = _positive_weight(row.score, row.status)
        if weight <= 0:
            continue
        _accumulate(pos_weights, genres, weight)
        n_pos += 1

    dismissed_qs = DismissedItem.objects.filter(user=user, media_type=media_type)
    for d in dismissed_qs:
        genres = _genres_for_item(d.source, d.media_type, d.media_id)
        if not genres:
            continue
        _accumulate(neg_weights, genres, 1.0)
        n_neg += 1

    profile = {
        "pos": pos_weights,
        "neg": neg_weights,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "pos_norm": _vector_norm(pos_weights),
        "neg_norm": _vector_norm(neg_weights),
    }
    cache.set(key, profile, PROFILE_TTL)
    return profile


def has_enough_signal(profile):
    """Return True when the profile has enough positive data to score items."""
    return profile.get("n_pos", 0) >= MIN_POSITIVE_SIGNALS


def score_item(profile, genres):
    """Return a 0..100 match score for an item with the given genres.

    Cosine similarity against the positive bag, minus a smaller
    penalty proportional to overlap with the negative bag. The mix
    favors the positive signal (the user explicitly rated those
    items) and treats the negative as a soft veto.

    Items with no genres get a neutral 50 — we don't have a reason
    to push them up or down, but suppressing the badge entirely
    feels worse than showing "50% match" on the rare unrated tile.
    """
    if not genres:
        return 50
    pos = profile.get("pos") or {}
    neg = profile.get("neg") or {}
    pos_norm = profile.get("pos_norm") or 0.0

    if pos_norm == 0:
        return 50

    candidate_vec = dict.fromkeys(genres, 1.0)
    candidate_norm = sqrt(len(candidate_vec))

    pos_dot = sum(pos.get(g, 0.0) for g in candidate_vec)
    neg_dot = sum(neg.get(g, 0.0) for g in candidate_vec)

    pos_sim = pos_dot / (pos_norm * candidate_norm) if candidate_norm else 0.0
    # Negative penalty is dampened: even a strong genre veto shouldn't
    # zero out an otherwise-loved combo (you might dislike horror in
    # general but love a horror-comedy if comedy weight is strong).
    neg_norm = profile.get("neg_norm") or 0.0
    if neg_norm and candidate_norm:
        neg_sim = neg_dot / (neg_norm * candidate_norm)
    else:
        neg_sim = 0.0

    raw = pos_sim - 0.6 * neg_sim
    # Map cosine-ish range (~-0.6..1.0) to 0..100, biased a bit upward
    # so a totally orthogonal item lands near 50, not 0.
    scaled = 50 + raw * 50
    return max(0, min(100, round(scaled)))


def _empty_profile():
    return {
        "pos": {},
        "neg": {},
        "n_pos": 0,
        "n_neg": 0,
        "pos_norm": 0.0,
        "neg_norm": 0.0,
    }


def _positive_weight(score, status):
    """Convert score / status to a positive-bag weight.

    Scored items dominate: a 10/10 contributes 1.0, a 5/10 contributes
    0.5. Completed-without-score gets a small floor weight (0.6) so
    "watched and didn't bother rating" still nudges the profile.
    Planning / Paused are neutral — they're aspirational, not signal.
    """
    if score is not None:
        return float(score) / 10.0
    if status == Status.COMPLETED.value:
        return 0.6
    if status == Status.IN_PROGRESS.value:
        return 0.4
    return 0.0


def _accumulate(bag, genres, weight):
    for g in genres:
        bag[g] = bag.get(g, 0.0) + weight


def _vector_norm(bag):
    return sqrt(sum(v * v for v in bag.values()))


def _genres_for_item(source, media_type, media_id):
    """Extract a list of genre names from cached provider metadata.

    Uses ``get_media_metadata`` which is itself Redis-cached, so the
    profile build pays at most one round-trip per unique item the
    first time it's used. Any provider error or missing-genre case
    returns an empty list — the caller skips that item.
    """
    try:
        meta = services.get_media_metadata(media_type, str(media_id), source)
    except services.ProviderAPIError:
        logger.debug(
            "taste: metadata lookup failed for %s/%s/%s",
            source,
            media_type,
            media_id,
        )
        return []
    return meta.get("genres") or []


def attach_match_scores(user, media_type, source, results):
    """Annotate Browse result dicts with a ``match_score`` (0..100).

    Mutates and returns the same list. No-op when the media_type isn't
    supported, the source isn't TMDB (only place we have reliable
    genres on browse rows today), or the user lacks enough positive
    signal — see ``has_enough_signal``.
    """
    if not results:
        return results
    if not is_supported(media_type) or source != Sources.TMDB.value:
        return results

    profile = build_profile(user, media_type)
    if not has_enough_signal(profile):
        return results

    for r in results:
        genres = r.get("genre_names") or []
        if not genres:
            continue
        r["match_score"] = score_item(profile, genres)
    return results
