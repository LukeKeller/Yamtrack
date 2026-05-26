"""Web Push (VAPID) helpers.

Push is best-effort and degrades cleanly:
- If VAPID keys are unset, ``push_enabled()`` returns False and the
  subscribe endpoints / UI hide the feature.
- If the push service returns 404/410 (the subscription is dead because
  the user unsubscribed or the browser purged it), the row is deleted
  so the next send doesn't keep retrying.
- All other failures are logged and swallowed; they must never break
  the wider notification pipeline.
"""

import json
import logging

from django.conf import settings
from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

GONE_STATUS_CODES = {404, 410}


def push_enabled():
    """Return True iff VAPID keys are configured."""
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def _vapid_claims():
    return {"sub": settings.VAPID_CLAIM_SUB}


def push_to_subscription(subscription, payload, ttl=60):
    """Send a single push to one subscription.

    Returns True on success. Deletes the subscription if the push service
    reports it gone (404/410).
    """
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims=_vapid_claims(),
            ttl=ttl,
        )
    except WebPushException as exc:
        if exc.response is not None and exc.response.status_code in GONE_STATUS_CODES:
            logger.info(
                "push subscription gone (status=%s) — deleting %s",
                exc.response.status_code,
                subscription.pk,
            )
            subscription.delete()
        else:
            logger.exception("push failed for subscription %s", subscription.pk)
        return False
    except Exception:
        logger.exception("push raised non-WebPushException for sub %s", subscription.pk)
        return False
    return True


def push_to_user(user, title, body, url=None, icon=None, ttl=60):
    """Push to every active subscription on this user. Returns count sent."""
    if not push_enabled():
        return 0

    payload = {
        "title": title,
        "body": body,
        "url": url,
        "icon": icon,
    }
    sent = 0
    for sub in user.push_subscriptions.all():
        if push_to_subscription(sub, payload, ttl=ttl):
            sent += 1
    return sent
