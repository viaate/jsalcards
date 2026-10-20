"""The chance of no school for every district, every school day (S7).

* :mod:`~snowlight.predict.calendar`: school days, seasons, the days a pass forecasts.
* :mod:`~snowlight.predict.situations`: the weather class of a day, one rule for history
  and live, and the situations the rates are kept for.
* :mod:`~snowlight.predict.alerts_history` and :mod:`~snowlight.predict.alerts_live`: the
  alerts that make the class, from the IEM season files and from the NWS feed.
* :mod:`~snowlight.predict.labels`: what each district did on past school days.
* :mod:`~snowlight.predict.pool`: the pooled rates, borrowed up a chain of places.
* :mod:`~snowlight.predict.backtest`: the walk-forward backtest and its gates.
* :mod:`~snowlight.predict.artifact`: the committed model (derived counts by LEAID).
* :mod:`~snowlight.predict.why`: how a chance adds up.
* :mod:`~snowlight.predict.serve`: one pass's ``predictions/latest.json``.
* :mod:`~snowlight.predict.publish`: the live host, and when to stay dark.
* :mod:`~snowlight.predict.cli`: ``snowlight predict``.
"""
