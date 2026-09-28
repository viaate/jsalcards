"""config/aliases.yaml: loading, validation and lookups."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from snowlight.match import Aliases, Directory, alias_key, load_aliases
from snowlight.match.aliases import DEFAULT_ALIASES_PATH, AliasFile


def test_the_shipped_alias_file_loads_and_holds_only_checked_entries(
    handmade_directory: Directory,
) -> None:
    aliases = load_aliases()
    assert DEFAULT_ALIASES_PATH.name == "aliases.yaml"
    # Every entry must come from a listing seen in a live market; none is live yet.
    assert len(aliases) == 0
    assert aliases.problems(handmade_directory) == []


def test_alias_key_ignores_spacing_and_case() -> None:
    assert alias_key("  Lancaster   SCHOOLS\t") == "lancaster schools"
    assert alias_key("Café Academy") == alias_key("Café academy")
    assert alias_key("Lancaster Schools") != alias_key("Lancaster School")


def test_lookup_is_per_market(tmp_path: Path, handmade_directory: Directory) -> None:
    path = tmp_path / "aliases.yaml"
    path.write_text(
        "schema_version: 1\n"
        "markets:\n"
        "  wxyz:\n"
        '    "FCPS": "SYN-VA-FAIR"\n'
        '    "Old Name Academy": "SYN-GONE"\n'
        "  kabc-tv:\n"
        '    "FCPS": "SYN-PA-LANSD"\n',
        encoding="utf-8",
    )
    aliases = load_aliases(path)
    assert len(aliases) == 3
    assert aliases.lookup("wxyz", "fcps ") == ("SYN-VA-FAIR",)
    assert aliases.lookup("kabc-tv", "FCPS") == ("SYN-PA-LANSD",)
    assert aliases.lookup("other", "FCPS") is None
    assert aliases.lookup(None, "FCPS") is None
    assert aliases.lookup("wxyz", "FCPS Schools") is None
    assert aliases.problems(handmade_directory) == [
        "wxyz: 'old name academy' maps to SYN-GONE, which is not in the directory"
    ]
    assert Aliases().lookup("wxyz", "FCPS") is None


def test_a_listing_may_be_pinned_to_several_records(
    tmp_path: Path, handmade_directory: Directory
) -> None:
    path = tmp_path / "aliases.yaml"
    path.write_text(
        "schema_version: 1\n"
        "markets:\n"
        "  wxyz:\n"
        '    "Kellby Pub. Schs.": ["SYN-MT-KELE", "SYN-MT-GLAH"]\n'
        '    "Brackley Schools":\n'
        '      - "SYN-MT-KELE"\n'
        '      - "SYN-GONE"\n',
        encoding="utf-8",
    )
    aliases = load_aliases(path)
    assert len(aliases) == 2
    assert aliases.lookup("wxyz", "KELLBY PUB.  SCHS.") == ("SYN-MT-KELE", "SYN-MT-GLAH")
    assert aliases.problems(handmade_directory) == [
        "wxyz: 'brackley schools' maps to SYN-GONE, which is not in the directory"
    ]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"schema_version": 1, "markets": {"wxyz": {"A": []}}}, "no NCES id"),
        ({"schema_version": 1, "markets": {"wxyz": {"A": ["0100005", "0100005"]}}}, "twice"),
        ({"schema_version": 1, "markets": {"wxyz": {"A": ["0100005", "01 5"]}}}, "not an NCES"),
        ({"schema_version": 1, "markets": {"wxyz": {"A": 100005}}}, "valid string"),
        ({"schema_version": 2, "markets": {}}, "schema_version"),
        ({"schema_version": 1}, "markets"),
        ({"schema_version": 1, "markets": {}, "extra": 1}, "extra"),
        ({"schema_version": 1, "markets": {"WXYZ": {}}}, "market id"),
        ({"schema_version": 1, "markets": {"wxyz": {"  ": "0100005"}}}, "empty listing"),
        ({"schema_version": 1, "markets": {"wxyz": {"A": "01 00005"}}}, "not an NCES id"),
        (
            {"schema_version": 1, "markets": {"wxyz": {"Lancaster SD": "1", "lancaster  sd": "2"}}},
            "same listing",
        ),
    ],
)
def test_bad_alias_files_are_refused(raw: object, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        AliasFile.model_validate(raw)
