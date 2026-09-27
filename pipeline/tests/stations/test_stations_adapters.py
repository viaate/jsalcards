"""The adapter registry: adapters found from the platform files present, imported by name.

The platform files built here (in ``tmp_path``) are synthetic and named so; the real
ones are ``pipeline/config/sources/*.yaml``.
"""

import ast
from pathlib import Path

import pytest

from snowlight.sources.stations import adapters, gray, hearst
from snowlight.sources.stations.adapters import (
    ADAPTERS,
    AdapterRegistry,
    adapter_for,
    declared_adapter,
    load_adapter,
    module_name,
)
from snowlight.sources.stations.registry import DEFAULT_REGISTRY_DIR, RegistryError, load_registry

SYNTHETIC_PLATFORM = """\
# synthetic platform file
platform:
  id: {pid}
  name: Demo platform (synthetic)
  operator: Nobody
  adapter: {adapter}
  poll_minutes: 10
  terms: {{automated_access: unread, summary: not read, evidence: []}}
  notes: synthetic test platform
stations: []
"""


def _platform_file(folder: Path, pid: str, adapter: str) -> Path:
    path = folder / f"{pid}.yaml"
    path.write_text(SYNTHETIC_PLATFORM.format(pid=pid, adapter=adapter), encoding="utf-8")
    return path


def test_real_platform_files_name_their_adapters() -> None:
    assert declared_adapter(DEFAULT_REGISTRY_DIR / "gray.yaml") == "gray"
    assert declared_adapter(DEFAULT_REGISTRY_DIR / "hearst.yaml") == "hearst"
    registry = load_registry(DEFAULT_REGISTRY_DIR)
    for platform in registry.platforms.values():
        path = DEFAULT_REGISTRY_DIR / f"{platform.id}.yaml"
        assert declared_adapter(path) == platform.adapter


def test_default_registry_has_gray_and_hearst() -> None:
    assert ADAPTERS["gray"] is gray.parse
    assert ADAPTERS["hearst"] is hearst.parse
    assert {"gray", "hearst"} <= set(ADAPTERS)
    load_registry(DEFAULT_REGISTRY_DIR).check_adapters(ADAPTERS)


def test_only_platforms_whose_files_are_present_are_adapters(tmp_path: Path) -> None:
    _platform_file(tmp_path, "gray", "gray")
    found = AdapterRegistry(tmp_path)
    assert list(found) == ["gray"]
    assert len(found) == 1
    assert found["gray"] is gray.parse
    # Hearst's module exists, but no platform file here names it.
    with pytest.raises(KeyError):
        found["hearst"]


def test_a_platform_naming_a_missing_adapter_is_refused(tmp_path: Path) -> None:
    _platform_file(tmp_path, "gray", "gray")
    _platform_file(tmp_path, "demo", "nope")
    found = AdapterRegistry(tmp_path)
    assert list(found) == ["gray"]
    with pytest.raises(RegistryError, match="demo names unknown adapter"):
        load_registry(tmp_path).check_adapters(found)


@pytest.mark.parametrize("name", ["robots", "registry", "adapters", "nope", "Gray", "gray_files"])
def test_names_that_are_not_adapters(name: str) -> None:
    # robots.parse reads robots.txt text, not a closings body; registry has no parse;
    # the rest name no module, or not in the registry's spelling.
    with pytest.raises(KeyError):
        load_adapter(name)
    with pytest.raises(KeyError):
        adapter_for(name)


def test_a_dash_names_an_underscored_module() -> None:
    assert module_name("abc-owned") == "snowlight.sources.stations.abc_owned"
    assert adapter_for("gray") is gray.parse
    with pytest.raises(KeyError):
        module_name("../gray")


@pytest.mark.parametrize(
    ("synthetic", "expected"),
    [
        # The adapter after a nested block, whose own keys are not the platform's.
        (
            "platform:\n  id: x\n  terms: {adapter: nope, evidence: [a, b]}\n"
            "  notes: [adapter]\n  adapter: gray\n",
            "gray",
        ),
        # Stations before the platform block.
        ("stations:\n  - {adapter: nope}\nplatform:\n  adapter: hearst\n", "hearst"),
        # No adapter in the platform block; one under stations does not count.
        ("platform:\n  id: x\nstations:\n  - adapter: gray\n", None),
        ("adapter: gray\n", None),
        ("platform: gray\n", None),
        ("platform:\n  adapter: [gray]\n", None),
        ("platform:\n  adapter: gray\n  id: [unclosed\n", "gray"),
        ("platform: {adapter: [unclosed\n", None),
        ("", None),
    ],
)
def test_declared_adapter_in_synthetic_files(
    tmp_path: Path, synthetic: str, expected: str | None
) -> None:
    path = tmp_path / "synthetic.yaml"
    path.write_text(synthetic, encoding="utf-8")
    assert declared_adapter(path) == expected


def test_declared_adapter_of_a_missing_or_binary_file(tmp_path: Path) -> None:
    assert declared_adapter(tmp_path / "absent.yaml") is None
    binary = tmp_path / "binary.yaml"
    binary.write_bytes(b"\xff\xfe\x00platform")
    assert declared_adapter(binary) is None


def test_the_registry_module_imports_no_platform_module() -> None:
    # Each platform's module is found from its platform file, so this module never
    # names one and ships without any of them.
    tree = ast.parse(Path(adapters.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    stations = {name for name in imported if name.startswith("snowlight.sources.stations")}
    assert stations == {
        "snowlight.sources.stations.model",
        "snowlight.sources.stations.model.Listing",
        "snowlight.sources.stations.registry",
        "snowlight.sources.stations.registry.DEFAULT_REGISTRY_DIR",
    }
