"""Flights: the chance a US departure is cancelled or leaves 45+ minutes late (docs/flights.md).

Everything here is its own package beside the Schools pipeline: the airports table
(:mod:`~snowlight.flights.airports`); the history the model learns from
(:mod:`~snowlight.flights.bts` for flights, :mod:`~snowlight.flights.nbs` for the forecasts known
at the time, :mod:`~snowlight.flights.obs` for the weather that came); the model and its held-out
test (:mod:`~snowlight.flights.model`, :mod:`~snowlight.flights.train`); each airport's own
record in bad weather (:mod:`~snowlight.flights.records`); the usual flights on each route
(:mod:`~snowlight.flights.schedules`); the live job (:mod:`~snowlight.flights.live`) and the
monthly scoring and refit (:mod:`~snowlight.flights.monthly`).
"""
