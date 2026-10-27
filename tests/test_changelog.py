"""CHANGELOG.md must stay in the shape release.yml and release-guru rely on."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/terraapply/NetBird-Docker-Host"
HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})$")
LINK = re.compile(r"^\[([^\]]+)\]: (\S+)$")


def changelog_problems(text):
    lines = text.splitlines()
    headings = [ln for ln in lines if ln.startswith("## ")]
    links = [m.groups() for ln in lines if (m := LINK.match(ln))]
    problems = []
    if not headings or headings[0] != "## [Unreleased]":
        problems.append("the first ## heading must be ## [Unreleased]")
    releases = []
    for heading in headings[1:]:
        if m := HEADING.match(heading):
            releases.append(m.groups())
        else:
            problems.append(f"not ## [X.Y.Z] - YYYY-MM-DD: {heading}")
    versions = [v for v, _ in releases]
    keys = [tuple(int(n) for n in v.split(".")) for v in versions]
    if keys != sorted(set(keys), reverse=True):
        problems.append("versions must go down the file, each once")
    dates = [d for _, d in releases]
    if dates != sorted(dates, reverse=True):
        problems.append("dates must not increase down the file")
    wanted = (
        [("Unreleased", f"{REPO}/compare/v{versions[0]}...HEAD")] if versions else []
    )
    for older, version in zip(versions[1:] + [None], versions, strict=True):
        if older:
            wanted.append((version, f"{REPO}/compare/v{older}...v{version}"))
        else:
            wanted.append((version, f"{REPO}/releases/tag/v{version}"))
    if links != wanted:
        problems.append(f"link lines must be, in order: {wanted}")
    return problems


GOOD = f"""# Changelog

## [Unreleased]

### Fixed

- Something.

## [0.2.0] - 2026-11-01

### Added

- Something.

## [0.1.0] - 2026-10-24

### Added

- Something.

[Unreleased]: {REPO}/compare/v0.2.0...HEAD
[0.2.0]: {REPO}/compare/v0.1.0...v0.2.0
[0.1.0]: {REPO}/releases/tag/v0.1.0
"""


def test_changelog_is_release_ready():
    assert changelog_problems((REPO_ROOT / "CHANGELOG.md").read_text()) == []


def test_good_sample_passes():
    assert changelog_problems(GOOD) == []


def test_empty_unreleased_is_valid():
    text = GOOD.replace("### Fixed\n\n- Something.\n\n## [0.2.0]", "## [0.2.0]")
    assert changelog_problems(text) == []


@pytest.mark.parametrize(
    "old, new",
    [
        ("## [Unreleased]", "## Unreleased"),
        ("## [0.2.0] - 2026-11-01", "## [0.2.0]"),
        ("## [0.2.0] - 2026-11-01", "## [0.0.9] - 2026-11-01"),
        ("compare/v0.2.0...HEAD", "compare/v0.1.0...HEAD"),
        (f"[0.2.0]: {REPO}/compare/v0.1.0...v0.2.0\n", ""),
        ("## [0.1.0] - 2026-10-24", "## [0.1.0] - 2026-12-24"),
    ],
)
def test_mistakes_are_caught(old, new):
    assert old in GOOD
    assert changelog_problems(GOOD.replace(old, new)) != []
