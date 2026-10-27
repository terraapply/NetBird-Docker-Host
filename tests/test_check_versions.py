"""Tests for scripts/check_versions.py. No network: every lookup is faked."""

import http.client
import importlib.util
import json
import re
import subprocess
import sys
import urllib.error
from dataclasses import replace
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
EXAMPLE = REPO_ROOT / "netbird-server" / "netbird.example.yaml"

# Row and command-line tests run on this repo, never on the real pins, so an
# upgrade of the real pins cannot break them.
FAKE_REPO = {
    "netbird-server/netbird.example.yaml": """images:
  traefik: traefik:v3.6
  netbird_server: netbirdio/netbird-server:0.77.0
  dashboard: netbirdio/dashboard:v2.91.1
  dex: ghcr.io/dexidp/dex:v2.45.1
  postgres: postgres:17-alpine
""",
    "netbird-agent/docker/docker-compose.yml": """services:
  netbird:
    image: netbirdio/netbird:0.77.0
""",
    "requirements-dev.txt": """pytest==9.1.1
ruff==0.17.2
pre-commit==4.7.0; python_version >= "3.11"
""",
    ".pre-commit-config.yaml": """repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.17.2
""",
    ".github/workflows/ci.yml": """jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
""",
    "README.md": "[![NetBird 0.77.0](https://img.shields.io/badge/NetBird-0.77.0-blue)](x)\n",
    "CHANGELOG.md": "- Pinned NetBird 0.77.0.\n",
}


@pytest.fixture
def fake_repo(tmp_path):
    for rel, text in FAKE_REPO.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    return tmp_path


def netbird_version():
    tag = yaml.safe_load(EXAMPLE.read_text())["images"]["netbird_server"]
    return tag.rsplit(":", 1)[1]


def found(**match):
    return {
        (p.name, p.current)
        for p in cv.find_pins(REPO_ROOT)
        if all(getattr(p, k) == v for k, v in match.items())
    }


def test_finds_every_image():
    compose = REPO_ROOT / "netbird-agent" / "docker" / "docker-compose.yml"
    services = yaml.safe_load(compose.read_text())["services"].values()
    refs = [
        *yaml.safe_load(EXAMPLE.read_text())["images"].values(),
        *(s["image"] for s in services),
    ]
    assert found(source="image") == {tuple(r.rsplit(":", 1)) for r in refs}
    assert {n for n, _ in found(group="netbird")} == set(cv.NETBIRD)
    assert found(source="image") == found(group="netbird") | found(group="images")


def test_finds_every_dev_requirement():
    lines = (REPO_ROOT / "requirements-dev.txt").read_text().splitlines()
    wanted = {tuple(ln.split(";")[0].strip().split("==")) for ln in lines if ln}
    assert found(source="pypi") == wanted


def test_requirement_markers_are_read(fake_repo):
    markers = {p.name: p.marker for p in cv.find_pins(fake_repo)}
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
    ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    matrix = ci["jobs"]["test"]["strategy"]["matrix"]["python-version"]
    assert cv.ci_pythons(REPO_ROOT) == matrix
    assert found(source="python") == {("python", max(matrix, key=cv.version_key))}


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


FAKE_TAGS = {
    "netbirdio/netbird-server": ["0.77.0", "0.78.0", "0.79.0", "0.79.0-rc.1", "latest"],
    "netbirdio/netbird": ["0.77.0", "0.78.0"],
    "netbirdio/dashboard": ["v2.91.1", "v2.92.0"],
    "traefik": ["v3.6", "v3.7", "v3.7.1"],
    "ghcr.io/dexidp/dex": ["v2.45.1", "v2.46.0", "v2.46.0-alpine"],
    "postgres": ["17-alpine", "18-alpine", "18.1-alpine"],
}
FAKE_PYPI = {
    "pytest": {"9.1.1": ">=3.10", "9.2.0": ">=3.11"},
    "pre-commit": {"4.7.0": ">=3.10", "4.8.0": ">=3.11"},
}
FAKE_GITHUB = {"actions/checkout": ["v7", "v7.0.1", "v8"]}


@pytest.fixture
def lookups(monkeypatch):
    fake = {
        "tags": dict(FAKE_TAGS),
        "pypi": dict(FAKE_PYPI),
        "github": dict(FAKE_GITHUB),
        "python": {},
        "missing": set(),
        "fail": {},
        "fail_all": None,
    }

    def call(kind, key, default):
        if fake["fail_all"]:
            raise fake["fail_all"]
        if key in fake["fail"]:
            raise fake["fail"][key]
        return fake[kind].get(key, default)

    def exists(image, tag):
        if fake["fail_all"]:
            raise fake["fail_all"]
        return (image, tag) not in fake["missing"]

    monkeypatch.setattr(
        cv, "registry_tags", lambda image, suffix="": call("tags", image, [])
    )
    monkeypatch.setattr(cv, "image_exists", exists)
    monkeypatch.setattr(cv, "pypi_releases", lambda name: call("pypi", name, {}))
    monkeypatch.setattr(cv, "github_tags", lambda repo: call("github", repo, []))
    monkeypatch.setattr(
        cv,
        "python_versions",
        lambda: call("python", "python", ["3.10", "3.12", "3.13", "3.14"]),
    )
    return fake


def rows(root, pins=None):
    pins = cv.find_pins(root) if pins is None else pins
    checked = cv.check(root, pins, cv.ci_pythons(root))
    return {r.pin.name: r for r in checked}


def changed(root, name, current):
    return [
        replace(p, current=current) if p.name == name else p for p in cv.find_pins(root)
    ]


def test_netbird_target_needs_server_and_client(lookups, fake_repo):
    r = rows(fake_repo)
    assert r["netbirdio/netbird-server"].candidates == ["0.78.0"]
    assert r["netbirdio/netbird"].candidates == ["0.78.0"]
    assert r["netbirdio/netbird-server"].jump == "major"


def test_dashboard_has_its_own_tag(lookups, fake_repo):
    assert rows(fake_repo)["netbirdio/dashboard"].newest == "v2.92.0"


def test_postgres_major_is_never_applied(lookups, fake_repo):
    row = rows(fake_repo)["postgres"]
    assert row.newest == "18-alpine"
    assert row.apply is False
    assert any("data directory" in n for n in row.notes)


def test_release_that_drops_a_ci_python_is_not_offered(lookups, fake_repo):
    row = rows(fake_repo)["pytest"]
    assert row.candidates == []
    assert any("9.2.0" in n and ">=3.11" in n for n in row.notes)


def test_marker_limits_the_pythons_checked(lookups, fake_repo):
    assert rows(fake_repo)["pre-commit"].candidates == ["4.8.0"]


def test_newest_ci_python_moves(lookups, fake_repo):
    assert rows(fake_repo)["python"].candidates == ["3.13", "3.14"]


def test_server_and_client_mismatch_is_flagged(lookups, fake_repo):
    r = rows(fake_repo, changed(fake_repo, "netbirdio/netbird", "0.76.0"))
    for name in ("netbirdio/netbird-server", "netbirdio/netbird"):
        assert any("0.76.0" in n and "0.77.0" in n for n in r[name].notes)


def test_lint_tool_pair_mismatch_is_flagged(lookups, fake_repo):
    r = rows(fake_repo, changed(fake_repo, "astral-sh/ruff-pre-commit", "v0.17.1"))
    assert any("v0.17.1" in n for n in r["ruff"].notes)
    assert any("0.17.2" in n for n in r["astral-sh/ruff-pre-commit"].notes)


def test_missing_current_tag_is_flagged(lookups, fake_repo, capsys):
    lookups["missing"].add(("ghcr.io/dexidp/dex", "v2.45.1"))
    assert rows(fake_repo)["ghcr.io/dexidp/dex"].exists is False
    cv.main(["--group", "images"], root=fake_repo)
    assert "not found" in capsys.readouterr().out


def test_failed_lookup_is_an_error_row(lookups, fake_repo, capsys):
    lookups["fail"]["traefik"] = urllib.error.URLError("timed out")
    assert cv.main(["--group", "images"], root=fake_repo) == 1
    out = capsys.readouterr().out
    assert "timed out" in out
    assert "ghcr.io/dexidp/dex" in out


def test_offline_run_prints_valid_json(lookups, fake_repo, capsys):
    lookups["fail_all"] = urllib.error.URLError("no network")
    assert cv.main(["--json"], root=fake_repo) == 1
    data = json.loads(capsys.readouterr().out)
    assert data and all(row["error"] for row in data)


def test_rate_limit_hints_at_token(lookups, fake_repo, capsys):
    lookups["fail"]["actions/checkout"] = urllib.error.HTTPError(
        "https://api.github.com/repos/actions/checkout/tags",
        403,
        "rate limit",
        None,
        None,
    )
    assert cv.main(["--group", "actions"], root=fake_repo) == 1
    assert "GITHUB_TOKEN" in capsys.readouterr().out


def test_json_lists_where_each_version_appears(lookups, fake_repo, capsys):
    assert cv.main(["--json", "--group", "netbird"], root=fake_repo) == 0
    data = {row["name"]: row for row in json.loads(capsys.readouterr().out)}
    assert set(data) == set(cv.NETBIRD)
    locs = data["netbirdio/netbird-server"]["locations"]
    assert any(loc.startswith("README.md:") for loc in locs)
    assert any(loc.startswith("netbird-server/netbird.example.yaml:") for loc in locs)
    assert not any(loc.startswith("CHANGELOG.md:") for loc in locs)
    assert (
        data["netbirdio/dashboard"]["release_notes"]
        == "https://github.com/netbirdio/dashboard/releases"
    )


def test_locations_skip_this_scripts_fake_data():
    locs = cv.locations(REPO_ROOT, netbird_version())
    assert any(loc.startswith("README.md:") for loc in locs)
    assert not any(loc.startswith("tests/test_check_versions.py:") for loc in locs)


def test_config_comments_name_no_netbird_version():
    version = netbird_version()
    for rel in (
        "netbird-server/netbird.example.yaml",
        "netbird-server/template/dex.config.yaml.tmpl",
    ):
        comments = [
            ln
            for ln in (REPO_ROOT / rel).read_text().splitlines()
            if ln.lstrip().startswith("#")
        ]
        assert not any(version in ln for ln in comments), rel


def test_action_locations_name_the_action(lookups, fake_repo):
    r = rows(fake_repo)
    locs = r["actions/checkout"].locations
    assert len(locs) == 1
    assert locs[0].startswith(".github/workflows/ci.yml:")
    assert r["python"].locations


def test_broken_response_is_an_error_row(lookups, fake_repo, capsys):
    lookups["fail"]["traefik"] = http.client.IncompleteRead(b"")
    lookups["fail"]["ghcr.io/dexidp/dex"] = TypeError("not subscriptable")
    lookups["fail"]["postgres"] = AttributeError("no attribute 'get'")
    assert cv.main(["--group", "images"], root=fake_repo) == 1
    assert capsys.readouterr().out.count("error:") == 3
