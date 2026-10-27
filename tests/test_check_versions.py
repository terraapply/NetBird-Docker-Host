"""Tests for scripts/check_versions.py. No network: every lookup is faked."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_versions", REPO_ROOT / "scripts" / "check_versions.py"
)
cv = importlib.util.module_from_spec(_spec)
sys.modules["check_versions"] = cv
_spec.loader.exec_module(cv)


def found(**match):
    return {
        (p.name, p.current)
        for p in cv.find_pins(REPO_ROOT)
        if all(getattr(p, k) == v for k, v in match.items())
    }


def test_finds_every_image():
    example = REPO_ROOT / "netbird-server" / "netbird.example.yaml"
    compose = REPO_ROOT / "netbird-agent" / "docker" / "docker-compose.yml"
    services = yaml.safe_load(compose.read_text())["services"].values()
    refs = [
        *yaml.safe_load(example.read_text())["images"].values(),
        *(s["image"] for s in services),
    ]
    assert found(source="image") == {tuple(r.rsplit(":", 1)) for r in refs}
    assert {n for n, _ in found(group="netbird")} == set(cv.NETBIRD)
    assert found(source="image") == found(group="netbird") | found(group="images")


def test_finds_every_dev_requirement():
    lines = (REPO_ROOT / "requirements-dev.txt").read_text().splitlines()
    wanted = {tuple(ln.split(";")[0].strip().split("==")) for ln in lines if ln}
    assert found(source="pypi") == wanted
    markers = {p.name: p.marker for p in cv.find_pins(REPO_ROOT)}
    assert markers["pre-commit"] == ">=3.11"
    assert markers["pytest"] == ""


def test_finds_every_precommit_rev():
    repos = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    wanted = {
        (r["repo"].removeprefix("https://github.com/"), r["rev"])
        for r in repos["repos"]
        if r["repo"] != "local"
    }
    assert found(group="tooling", source="github") == wanted


def test_finds_every_action():
    workflows = (REPO_ROOT / ".github" / "workflows").glob("*.yml")
    text = "".join(p.read_text() for p in workflows)
    wanted = {tuple(u.split("@")) for u in re.findall(r"uses: (\S+)", text)}
    assert found(group="actions", source="github") == wanted


def test_python_matrix():
    assert cv.ci_pythons(REPO_ROOT) == ["3.10", "3.12"]
    assert found(source="python") == {("python", "3.12")}


def test_odd_lines_are_skipped_or_parsed(tmp_path):
    for rel in (
        "netbird-server/netbird.example.yaml",
        "netbird-agent/docker/docker-compose.yml",
        "requirements-dev.txt",
        ".pre-commit-config.yaml",
        ".github/workflows/ci.yml",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text((REPO_ROOT / rel).read_text())
    with (tmp_path / "requirements-dev.txt").open("a") as f:
        f.write("\n# a comment\nrich[jupyter]==14.0.0  # pretty output\n")
    with (tmp_path / ".github/workflows/ci.yml").open("a") as f:
        f.write("      - uses: ./.github/actions/local\n")
        f.write("      - uses: docker://alpine:3.20\n")
    pins = {(p.name, p.current) for p in cv.find_pins(tmp_path)}
    assert ("rich", "14.0.0") in pins
    assert not any(n.startswith(("./", "docker://")) for n, _ in pins)


@pytest.mark.parametrize(
    "current, tags, expected",
    [
        (
            "v3.6",
            ["v3.6", "v3.7", "v3.7.1", "v4.0", "3.8", "latest"],
            ["v3.7", "v4.0"],
        ),
        (
            "17-alpine",
            ["17-alpine", "18-alpine", "18.1-alpine", "18-alpine3.22"],
            ["18-alpine"],
        ),
        (
            "0.77.0",
            ["0.78.0", "0.78.0-rc.1", "0.78.0-ubi", "0.77.1", "0.76.0"],
            ["0.77.1", "0.78.0"],
        ),
        ("1.9.0", ["1.10.0", "1.9.1", "1.10.0"], ["1.9.1", "1.10.0"]),
    ],
)
def test_candidates_keep_the_tag_shape(current, tags, expected):
    assert cv.candidates(current, tags) == expected


@pytest.mark.parametrize(
    "current, new, kind",
    [
        ("1.2.3", "1.2.4", "patch"),
        ("1.2.3", "1.3.0", "minor"),
        ("1.2.3", "2.0.0", "major"),
        ("0.77.0", "0.77.1", "patch"),
        ("0.77.0", "0.78.0", "major"),
        ("v7", "v8", "major"),
        ("v3.6", "v3.7", "minor"),
        ("3.12", "3.13", "minor"),
        ("17-alpine", "18-alpine", "major"),
    ],
)
def test_jump(current, new, kind):
    assert cv.jump(current, new) == kind


@pytest.mark.parametrize(
    "spec, python, ok",
    [
        (">=3.10", "3.10", True),
        (">=3.11", "3.10", False),
        (">=3.9,<4", "3.12", True),
        ("!=3.0.*,>=2.7", "3.10", True),
        (">=3.10.0", "3.10", True),
        ("<3.12", "3.12", False),
        ("", "3.10", True),
        (None, "3.10", True),
    ],
)
def test_allows(spec, python, ok):
    assert cv.allows(spec, python) is ok
