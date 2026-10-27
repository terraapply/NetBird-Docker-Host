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

Exit codes:
  0  every lookup worked
  1  at least one lookup failed; the row says why
  2  usage error
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

NETBIRD = ("netbirdio/netbird-server", "netbirdio/dashboard", "netbirdio/netbird")

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
