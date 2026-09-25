"""Weather alerts for Snowlight: the live map layer and the weather-reason check.

* :mod:`~snowlight.weather.hazards`: the allowlist of alert types.
* :mod:`~snowlight.weather.index`: the weather check, indexed for many schools.
* :mod:`~snowlight.weather.live`: today's alerts from the NWS feed.
* :mod:`~snowlight.weather.publish`: the published ``live/alerts.json``.
* :mod:`~snowlight.weather.history`: the check for past dates (IEM archive).
* :mod:`~snowlight.weather.timezones`: local windows and school time zones.
* :mod:`~snowlight.weather.build` and :mod:`~snowlight.weather.cli`: the
  ``snowlight alerts`` command.
"""
