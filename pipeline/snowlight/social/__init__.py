"""Automatic posts on the X account @SnowlightMap (docs/social.md).

``snowlight social post`` (``.github/workflows/social-post.yml``) posts at most one post a
run: the oldest queued post in ``social/queue/`` first, else, on the daily scheduled run and
only with an Anthropic key and the facts file's ``HAIKU_POSTS`` switch on (off now), one post
Claude Haiku writes from ``social/facts.md``. Every post passes the same deterministic checks
(:mod:`snowlight.social.rules`) and carries one image.

The X refresh token rotates on every use, so each run stores the new one, sealed with a key
derived from ``X_CLIENT_SECRET``, in the D1 database ``snowlight-live-state``
(:mod:`snowlight.social.store`); what was posted is recorded there too, so nothing posts
twice.
"""
