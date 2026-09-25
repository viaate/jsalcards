# Synthetic example documents

Every file here is made up for the tests in `pipeline/tests/schemas`. None of it describes a real
school, district, alert, closing or forecast: the names say "Synthetic", the ids are sequential
placeholders and the dates, times and shapes were chosen to exercise the validators.

There is one `synthetic-<name>.json` per entry of `snowlight.schemas.registry.PUBLISHED_FILES`.
They are valid documents, and the tests check that each one parses strictly, round-trips through
its model unchanged, and refuses every injected source field or address.
