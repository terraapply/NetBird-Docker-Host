#!/usr/bin/env python3
"""List every version this repo pins and the newest release of each.

Reads the pins from the files below, asks Docker Hub, GHCR, PyPI, GitHub and
the actions/python-versions manifest for newer releases, and prints a table.
Needs network; never edits a file.

  scripts/check_versions.py                  every group
  scripts/check_versions.py --group netbird  one group
  scripts/check_versions.py --json           the same data, plus every line
                                             where each version appears

Groups:
  netbird  netbird-server, dashboard and the client, in
           netbird-server/netbird.example.yaml and
           netbird-agent/docker/docker-compose.yml
  images   traefik, dex and postgres, in netbird-server/netbird.example.yaml
  tooling  requirements-dev.txt and the .pre-commit-config.yaml hooks
  actions  uses: lines in .github/workflows/ and the newest CI Python

Set GITHUB_TOKEN or GH_TOKEN to lift GitHub's anonymous rate limit.

Exit codes:
  0  every lookup worked
  1  at least one lookup failed; the row says why
  2  usage error
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

NETBIRD = ("netbirdio/netbird-server", "netbirdio/dashboard", "netbirdio/netbird")
GROUPS = ("netbird", "images", "tooling", "actions")
PAIRS = (("ruff", "astral-sh/ruff-pre-commit"), ("yamllint", "adrienverge/yamllint"))

EXAMPLE = "netbird-server/netbird.example.yaml"
AGENT_COMPOSE = "netbird-agent/docker/docker-compose.yml"
REQUIREMENTS = "requirements-dev.txt"
PRE_COMMIT = ".pre-commit-config.yaml"
WORKFLOWS = ".github/workflows"

IMAGE_REF = r"([a-z0-9][a-z0-9./_-]*):([A-Za-z0-9][A-Za-z0-9._-]*)"
EXAMPLE_IMAGE = re.compile(rf"^  \w+: {IMAGE_REF}\s*$")
COMPOSE_IMAGE = re.compile(rf"^\s+image: {IMAGE_REF}\s*$")
REQUIREMENT = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;#]+)\s*"
    r"(?:;\s*python_version\s*(>=|<=|==|!=|>|<)\s*[\"']([^\"']+)[\"'])?\s*(?:#.*)?$"
)
PRE_COMMIT_REPO = re.compile(r"^\s*-?\s*repo:\s*(\S+)")
PRE_COMMIT_REV = re.compile(r"^\s*rev:\s*(\S+)")
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s@]+)@(\S+)")
MATRIX = re.compile(r"python-version:\s*\[([^\]]*)\]")
CLAUSE = re.compile(r"^(~=|===|==|!=|>=|<=|>|<)\s*(\d+(?:\.\d+)*)(\.\*)?$")


@dataclass(frozen=True)
class Pin:
    group: str
    name: str
    current: str
    source: str
    marker: str = ""


def _lines(root: Path, rel: str) -> list[str]:
    path = root / rel
    return path.read_text().splitlines() if path.is_file() else []


def _image_pins(root: Path) -> list[Pin]:
    refs, in_images = [], False
    for line in _lines(root, EXAMPLE):
        if line and not line[0].isspace():
            in_images = line.startswith("images:")
        elif in_images and (m := EXAMPLE_IMAGE.match(line)):
            refs.append(m.groups())
    refs += [
        m.groups()
        for ln in _lines(root, AGENT_COMPOSE)
        if (m := COMPOSE_IMAGE.match(ln))
    ]
    return [
        Pin("netbird" if name in NETBIRD else "images", name, tag, "image")
        for name, tag in refs
    ]


def _requirement_pins(root: Path) -> list[Pin]:
    pins = []
    for line in _lines(root, REQUIREMENTS):
        if m := REQUIREMENT.match(line.strip()):
            name, version, op, bound = m.groups()
            marker = f"{op}{bound}" if op else ""
            pins.append(Pin("tooling", name, version, "pypi", marker))
    return pins


def _pre_commit_pins(root: Path) -> list[Pin]:
    pins, repo = [], ""
    for line in _lines(root, PRE_COMMIT):
        if m := PRE_COMMIT_REPO.match(line):
            repo = m.group(1)
        elif (m := PRE_COMMIT_REV.match(line)) and repo.startswith(
            "https://github.com/"
        ):
            name = repo.removeprefix("https://github.com/").removesuffix(".git")
            pins.append(Pin("tooling", name, m.group(1), "github"))
    return pins


def _action_pins(root: Path) -> list[Pin]:
    pins = []
    for path in sorted((root / WORKFLOWS).glob("*.yml")):
        for line in path.read_text().splitlines():
            m = USES.match(line)
            if m and not m.group(1).startswith(("./", "docker://")):
                pins.append(Pin("actions", m.group(1), m.group(2), "github"))
    return pins


def ci_pythons(root: Path) -> list[str]:
    for line in _lines(root, f"{WORKFLOWS}/ci.yml"):
        if m := MATRIX.search(line):
            return re.findall(r"\d+(?:\.\d+)*", m.group(1))
    return []


def find_pins(root: Path) -> list[Pin]:
    pins = [
        *_image_pins(root),
        *_requirement_pins(root),
        *_pre_commit_pins(root),
        *_action_pins(root),
    ]
    if pythons := ci_pythons(root):
        pins.append(Pin("actions", "python", max(pythons, key=version_key), "python"))
    unique = {}
    for pin in pins:
        unique.setdefault((pin.name, pin.current), pin)
    return list(unique.values())


def version_key(tag: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", tag))


def _shape(tag: str) -> list[str]:
    return re.split(r"\d+", tag)


def candidates(current: str, tags: Iterable[str]) -> list[str]:
    shape, key = _shape(current), version_key(current)
    newer = {t for t in tags if _shape(t) == shape and version_key(t) > key}
    return sorted(newer, key=version_key)


def jump(current: str, new: str) -> str:
    old, nxt = version_key(current), version_key(new)
    pairs = zip(old, nxt, strict=False)
    index = next((i for i, (a, b) in enumerate(pairs) if a != b), len(old))
    if index == 0:
        return "major"
    if index == 1:
        return "major" if old[0] == 0 and len(old) > 1 else "minor"
    return "patch"


def _padded(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    size = max(len(a), len(b))
    return a + (0,) * (size - len(a)), b + (0,) * (size - len(b))


def allows(spec: str | None, python: str) -> bool:
    have = version_key(python)
    for clause in (spec or "").split(","):
        m = CLAUSE.match(clause.strip())
        if not m:
            continue
        op, version, wildcard = m.groups()
        want = version_key(version)
        if wildcard:
            prefix = _padded(have, want)[0][: len(want)] == want
            if (op == "==" and not prefix) or (op == "!=" and prefix):
                return False
            continue
        a, b = _padded(have, want)
        ok = {
            ">=": a >= b,
            "~=": a >= b,
            ">": a > b,
            "<=": a <= b,
            "<": a < b,
            "==": a == b,
            "===": a == b,
            "!=": a != b,
        }[op]
        if not ok:
            return False
    return True


TIMEOUT = 20
USER_AGENT = "NetBird-Docker-Host check_versions"
DOCKER_HUB = "https://hub.docker.com/v2/namespaces"
GITHUB_API = "https://api.github.com"
PYTHON_MANIFEST = (
    "https://raw.githubusercontent.com/actions/python-versions/main/"
    "versions-manifest.json"
)
MANIFEST_TYPES = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
    )
)
NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')
NOT_LOCATIONS = ("CHANGELOG.md", "tests/test_check_versions.py")
SUFFIX = re.compile(r"-[A-Za-z][\w.-]*$")
NOTES = {
    "netbirdio/netbird-server": "https://github.com/netbirdio/netbird/releases",
    "netbirdio/netbird": "https://github.com/netbirdio/netbird/releases",
    "netbirdio/dashboard": "https://github.com/netbirdio/dashboard/releases",
    "traefik": "https://github.com/traefik/traefik/releases",
    "ghcr.io/dexidp/dex": "https://github.com/dexidp/dex/releases",
    "postgres": "https://www.postgresql.org/docs/release/",
    "python": "https://docs.python.org/3/whatsnew/",
}
POSTGRES_NOTE = "never applied: a Postgres major cannot start on the old data directory"
RATE_LIMIT = (
    "HTTP {code} from GitHub: set GITHUB_TOKEN or GH_TOKEN to lift the anonymous "
    "rate limit"
)


def _request(url: str, headers: dict | None = None, method: str = "GET"):
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, **(headers or {})}, method=method
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read()
        link = NEXT_LINK.search(response.headers.get("Link", ""))
    following = urllib.parse.urljoin(url, link.group(1)) if link else None
    return (json.loads(body) if body else None), following


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if token := os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _ghcr_auth(repo: str) -> dict:
    data, _ = _request(f"https://ghcr.io/token?scope=repository:{repo}:pull")
    return {"Authorization": f"Bearer {data['token']}"}


def _docker_hub(image: str) -> str:
    namespace, _, repo = image.rpartition("/")
    return f"{DOCKER_HUB}/{namespace or 'library'}/repositories/{repo}/tags"


def registry_tags(image: str, suffix: str = "") -> list[str]:
    tags = []
    if image.startswith("ghcr.io/"):
        repo = image.removeprefix("ghcr.io/")
        auth = _ghcr_auth(repo)
        url = f"https://ghcr.io/v2/{repo}/tags/list?n=1000"
        for _ in range(20):
            data, url = _request(url, auth)
            tags += data.get("tags") or []
            if not url:
                break
        return tags
    query = {"page_size": 100, "ordering": "last_updated"}
    if suffix:
        query["name"] = suffix
    url = f"{_docker_hub(image)}?{urllib.parse.urlencode(query)}"
    for _ in range(10):
        data, _ = _request(url)
        tags += [result["name"] for result in data["results"]]
        url = data.get("next")
        if not url:
            break
    return tags


def image_exists(image: str, tag: str) -> bool:
    try:
        if image.startswith("ghcr.io/"):
            repo = image.removeprefix("ghcr.io/")
            headers = {**_ghcr_auth(repo), "Accept": MANIFEST_TYPES}
            _request(f"https://ghcr.io/v2/{repo}/manifests/{tag}", headers, "HEAD")
        else:
            _request(f"{_docker_hub(image)}/{urllib.parse.quote(tag)}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise
    return True


def pypi_releases(name: str) -> dict[str, str | None]:
    data, _ = _request(f"https://pypi.org/pypi/{name}/json")
    releases = {}
    for version, files in data["releases"].items():
        live = [f for f in files if not f.get("yanked")]
        if live:
            releases[version] = live[0].get("requires_python")
    return releases


def github_tags(repo: str) -> list[str]:
    tags, url = [], f"{GITHUB_API}/repos/{repo}/tags?per_page=100"
    for _ in range(10):
        data, url = _request(url, _github_headers())
        tags += [tag["name"] for tag in data]
        if not url:
            break
    return tags


def python_versions() -> list[str]:
    data, _ = _request(PYTHON_MANIFEST)
    stable = {".".join(v["version"].split(".")[:2]) for v in data if v.get("stable")}
    return sorted(stable, key=version_key)


def locations(root: Path, text: str) -> list[str]:
    command = ["git", "-C", str(root), "grep", "-n", "-F", "-e", text]
    command += ["--", ".", *(f":(exclude){rel}" for rel in NOT_LOCATIONS)]
    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except OSError:
        return []
    if result.returncode != 0:
        return []
    return [":".join(ln.split(":", 2)[:2]) for ln in result.stdout.splitlines()]


@dataclass
class Row:
    pin: Pin
    candidates: list[str] = field(default_factory=list)
    apply: bool = True
    notes: list[str] = field(default_factory=list)
    error: str = ""
    exists: bool | None = None
    locations: list[str] = field(default_factory=list)
    release_notes: str = ""

    @property
    def newest(self) -> str:
        return self.candidates[-1] if self.candidates else ""

    @property
    def jump(self) -> str:
        return jump(self.pin.current, self.newest) if self.newest else ""


def release_notes(pin: Pin) -> str:
    if pin.source == "pypi":
        return f"https://pypi.org/project/{pin.name}/#history"
    if pin.source == "github":
        return f"https://github.com/{pin.name}/releases"
    return NOTES.get(pin.name, "")


def _lookup(row: Row, pythons: list[str]) -> None:
    pin = row.pin
    if pin.source == "image":
        suffix = m.group(0) if (m := SUFFIX.search(pin.current)) else ""
        row.candidates = candidates(pin.current, registry_tags(pin.name, suffix=suffix))
        row.exists = image_exists(pin.name, pin.current)
    elif pin.source == "pypi":
        checked = [py for py in pythons if allows(pin.marker, py)]
        offered = []
        for version, spec in pypi_releases(pin.name).items():
            if all(allows(spec, py) for py in checked):
                offered.append(version)
            elif candidates(pin.current, [version]):
                row.notes.append(f"{version} not offered: needs Python {spec}")
        row.candidates = candidates(pin.current, offered)
    elif pin.source == "github":
        row.candidates = candidates(pin.current, github_tags(pin.name))
    else:
        row.candidates = candidates(pin.current, python_versions())


def _cross_checks(rows: list[Row]) -> None:
    ok = {row.pin.name: row for row in rows if not row.error}
    server, client = ok.get("netbirdio/netbird-server"), ok.get("netbirdio/netbird")
    if server and client:
        both = sorted(set(server.candidates) & set(client.candidates), key=version_key)
        server.candidates, client.candidates = list(both), list(both)
        versions = server.pin.current, client.pin.current
        if versions[0] != versions[1]:
            note = "server and client differ: {} vs {}".format(*versions)
            server.notes.append(note)
            client.notes.append(note)
    postgres = ok.get("postgres")
    if postgres and any(
        jump(postgres.pin.current, c) == "major" for c in postgres.candidates
    ):
        postgres.apply = False
        postgres.notes.append(POSTGRES_NOTE)
    for a, b in PAIRS:
        if a in ok and b in ok:
            left, right = ok[a].pin.current, ok[b].pin.current
            if left.removeprefix("v") != right.removeprefix("v"):
                ok[a].notes.append(f"must match {b} {right}")
                ok[b].notes.append(f"must match {a} {left}")


def check(root: Path, pins: list[Pin], pythons: list[str]) -> list[Row]:
    rows = []
    for pin in pins:
        action = pin.group == "actions" and pin.source == "github"
        text = f"{pin.name}@{pin.current}" if action else pin.current
        row = Row(pin, locations=locations(root, text))
        row.release_notes = release_notes(pin)
        try:
            _lookup(row, pythons)
        except urllib.error.HTTPError as exc:
            limited = pin.source == "github" and exc.code in (403, 429)
            row.error = RATE_LIMIT.format(code=exc.code) if limited else str(exc)
        except (
            urllib.error.URLError,
            http.client.HTTPException,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            row.error = str(exc)
        rows.append(row)
    _cross_checks(rows)
    return rows


def _notes(row: Row) -> str:
    notes = list(row.notes)
    if row.exists is False:
        notes.append("current tag not found in registry")
    if row.error:
        notes.append(f"error: {row.error}")
    return "; ".join(notes)


def render_table(rows: list[Row]) -> str:
    table = [("GROUP", "NAME", "CURRENT", "NEWEST", "JUMP", "APPLY", "NOTES")]
    for row in rows:
        pin = row.pin
        apply = "yes" if row.apply else "no"
        newest, kind = row.newest or "-", row.jump or "-"
        table.append(
            (pin.group, pin.name, pin.current, newest, kind, apply, _notes(row))
        )
    widths = [max(len(line[i]) for line in table) for i in range(6)]
    return "\n".join(
        "  ".join(
            [*(c.ljust(w) for c, w in zip(line[:6], widths, strict=True)), line[6]]
        ).rstrip()
        for line in table
    )


def to_json(rows: list[Row]) -> str:
    return json.dumps(
        [
            {
                "group": row.pin.group,
                "name": row.pin.name,
                "current": row.pin.current,
                "newest": row.newest,
                "jump": row.jump,
                "apply": row.apply,
                "candidates": row.candidates,
                "notes": row.notes,
                "error": row.error,
                "exists": row.exists,
                "locations": row.locations,
                "release_notes": row.release_notes,
            }
            for row in rows
        ],
        indent=2,
    )


def main(argv: list[str] | None = None, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List every pinned version and the newest release of each."
    )
    parser.add_argument(
        "--json", action="store_true", help="print JSON, with where each version is"
    )
    parser.add_argument("--group", choices=GROUPS, help="check one group only")
    args = parser.parse_args(argv)
    root = root or Path(__file__).resolve().parents[1]
    pins = [p for p in find_pins(root) if args.group in (None, p.group)]
    rows = check(root, pins, ci_pythons(root))
    print(to_json(rows) if args.json else render_table(rows))
    return 1 if any(row.error for row in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
