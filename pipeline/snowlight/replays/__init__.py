"""Storm replays: one past school day, built offline from archived station closing lists.

A replay day ``D`` is built from the rows of the archived captures of station lists
(:mod:`snowlight.listed.evidence`), matched to schools with the committed matcher
(:mod:`snowlight.listed.matching`), read by the status reader through the
:class:`~snowlight.replays.gates.ParseFn` protocol, and kept only when every gate
holds (:mod:`snowlight.replays.gates`). The result is a derived seed keyed by NCES
id, with no names and no list text (:mod:`snowlight.replays.seed`), and an internal
report that is never published (:mod:`snowlight.replays.report`).

* :mod:`~snowlight.replays.rows`: the rows and reads in a day's widest window.
* :mod:`~snowlight.replays.gates`: the source, claim, read and day gates.
* :mod:`~snowlight.replays.build`: match, expand, read, settle and bar one day.
* :mod:`~snowlight.replays.control`: the D+7 control.
* :mod:`~snowlight.replays.report`: the internal report and its audit samples.
* :mod:`~snowlight.replays.seed`: the derived seed and its provenance hashes.
* :mod:`~snowlight.replays.publish`: the seeds as the site's ``replays/`` files, against
  the directory of each deploy.
* :mod:`~snowlight.replays.cli`: ``snowlight replays build``, ``days`` and ``publish``.
"""
