"""Notifications v1 (docs/notify.md): web push for each account's saved schools.

The accounts API (``api/``) stores the browsers' subscriptions, each account's settings and
the log of what was sent (migration 0004); this package sends. ``snowlight notify status``
runs in live-ingest.yml after each closings publish; :class:`~snowlight.notify.cli.
ChanceNotifier` runs in the predictions loop after each pass. Both read the database over
the Cloudflare API, compare the published files with the log, and push through each
browser's push service with the site's VAPID key.
"""
