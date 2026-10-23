"""renovate.json must keep finding every image tag in netbird.example.yaml."""

import json
import re

import yaml
from conftest import SERVER_DIR

RENOVATE = SERVER_DIR.parent / "renovate.json"
EXAMPLE = SERVER_DIR / "netbird.example.yaml"


def load_renovate():
    return json.loads(RENOVATE.read_text())


def example_images():
    images = yaml.safe_load(EXAMPLE.read_text())["images"]
    return {tuple(ref.rsplit(":", 1)) for ref in images.values()}


def test_renovate_regex_finds_all_images():
    managers = [
        m for m in load_renovate()["customManagers"] if m["customType"] == "regex"
    ]
    assert len(managers) == 1
    text = EXAMPLE.read_text()
    found = set()
    for pattern in managers[0]["matchStrings"]:
        # Renovate uses JS-style (?<name>); Python spells it (?P<name>).
        for m in re.finditer(pattern.replace("(?<", "(?P<"), text):
            found.add((m.group("depName"), m.group("currentValue")))
    assert found == example_images()


def test_renovate_blocks_postgres_major():
    # A postgres major cannot start on the previous major's data directory.
    assert any(
        r.get("matchPackageNames") == ["postgres"]
        and r.get("matchUpdateTypes") == ["major"]
        and r.get("enabled") is False
        for r in load_renovate()["packageRules"]
    )


def test_renovate_groups_netbird():
    wanted = {"netbirdio/netbird-server", "netbirdio/dashboard"}
    assert any(
        wanted <= set(r.get("matchPackageNames", [])) and r.get("groupName")
        for r in load_renovate()["packageRules"]
    )


def test_renovate_updates_precommit_hooks():
    assert load_renovate().get("pre-commit", {}).get("enabled") is True


def test_renovate_groups_lint_tools_with_their_hooks():
    # requirements-dev.txt (CI) and .pre-commit-config.yaml must move together,
    # or a hook that passed locally fails the same check in CI.
    rules = load_renovate()["packageRules"]
    for pair in (
        {"ruff", "astral-sh/ruff-pre-commit"},
        {"yamllint", "adrienverge/yamllint"},
    ):
        assert any(
            pair <= set(r.get("matchPackageNames", [])) and r.get("groupName")
            for r in rules
        ), pair
