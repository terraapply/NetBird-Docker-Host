"""Checks over the tracked Markdown docs: links resolve, no placeholders left."""

import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_README = REPO_ROOT / "README.md"
SERVER_README = REPO_ROOT / "netbird-server" / "README.md"
AGENT_README = REPO_ROOT / "netbird-agent" / "README.md"

HEADING = re.compile(r"^(?:>\s*)?#{1,6}\s+(.*?)\s*#*\s*$")
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")
BADGE = re.compile(
    r"!\[NetBird (\d+\.\d+\.\d+)\]"
    r"\(https://img\.shields\.io/badge/NetBird-(\d+\.\d+\.\d+)-"
)


def tracked_docs():
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / name for name in out.splitlines()]


def prose_lines(path):
    in_fence = False
    for line in path.read_text().splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield line


def doc_section(path, heading):
    """From `heading` (hashes included) to the next heading at its level or above."""
    level = len(heading) - len(heading.lstrip("#"))
    lines, out, in_fence, found = path.read_text().splitlines(), [], False, False
    for line in lines:
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and HEADING.match(line):
            hashes = len(line) - len(line.lstrip("#"))
            if found and line.startswith("#") and hashes <= level:
                break
            if line == heading:
                found = True
        if found:
            out.append(line)
    if not found:
        raise ValueError(f"{heading!r} not in {path}")
    return "\n".join(out)


def slug(text):
    # GitHub's heading anchors: lowercase, punctuation dropped, spaces to dashes.
    text = re.sub(r"[^\w\- ]", "", text.lower())
    return text.replace(" ", "-")


def anchors(path):
    seen = {}
    for line in prose_lines(path):
        m = HEADING.match(line)
        if not m:
            continue
        base = slug(m.group(1))
        n = seen.get(base, 0)
        seen[base] = n + 1
        yield base if n == 0 else f"{base}-{n}"


def test_relative_links_resolve():
    broken = []
    for doc in tracked_docs():
        for line in prose_lines(doc):
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path_part, _, anchor = target.partition("#")
                dest = (doc.parent / path_part).resolve() if path_part else doc
                rel = doc.relative_to(REPO_ROOT)
                if not dest.exists():
                    broken.append(f"{rel}: {target} (no such path)")
                elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                    broken.append(f"{rel}: {target} (no such heading)")
    assert broken == []


def test_no_todo_in_docs():
    left = [
        str(doc.relative_to(REPO_ROOT))
        for doc in tracked_docs()
        if "TODO" in doc.read_text()
    ]
    assert left == []


def test_readme_warns_one_method_per_vm():
    # Two clients on one VM fight over the same WireGuard interface, so the
    # warning must come before the reader picks an option.
    join = doc_section(ROOT_README, "## Join agents")
    assert "one method per VM" in join.split("\n### Option A: Docker", 1)[0]


def test_readmes_never_put_setup_key_on_command_line():
    for doc in (ROOT_README, SERVER_README, AGENT_README):
        assert not re.search(r"--setup-key[\s=]|NB_SETUP_KEY=", doc.read_text()), doc


def test_agent_readme_rekey_steps_are_runnable():
    # A bare `netbird up` skips sudo, the management URL and the key file,
    # and starts the SSO login instead of using the new key.
    trouble = doc_section(AGENT_README, "## Troubleshooting")
    assert "`netbird up`" not in trouble
    assert "(../README.md#option-b-native)" in trouble


def test_readme_has_match_server_version():
    # The install script and apt install the latest client, which can be newer
    # than the server; the README must say how to pin it to the server's release.
    text = ROOT_README.read_text()
    match = doc_section(ROOT_README, "### Match the server version")
    assert "./deploy.py config" in match
    assert "netbird=" in match
    native = text.index("### Option B: Native")
    assert (
        native < text.index("### Match the server version") < text.index("### Verify")
    )
    assert "netbird=" in doc_section(AGENT_README, "## Upgrade")


def test_agent_readme_has_no_install_steps():
    text = AGENT_README.read_text()
    for heading in (
        "## Requirements",
        "## Setup keys",
        "## Option A: Docker",
        "## Option B: Native",
        "## Match the server version",
        "## Verify",
    ):
        assert f"\n{heading}\n" not in text, heading
    assert "../README.md#join-agents" in text


def test_readme_docker_agent_commands_follow_cd():
    blocks = re.findall(
        r"```bash\n(.*?)```", doc_section(ROOT_README, "### Option A: Docker"), re.S
    )
    first_cd = next(
        i
        for i, b in enumerate(blocks)
        if "cd NetBird-Docker-Host/netbird-agent/docker" in b
    )
    first_up = next(i for i, b in enumerate(blocks) if "docker compose up -d" in b)
    assert first_cd < first_up


def test_readme_netbird_badge_matches_example():
    example = REPO_ROOT / "netbird-server" / "netbird.example.yaml"
    tag = yaml.safe_load(example.read_text())["images"]["netbird_server"]
    version = tag.rsplit(":", 1)[1]
    assert BADGE.findall(ROOT_README.read_text()) == [(version, version)]


def test_readme_badges_point_at_this_repo():
    urls = re.findall(
        r"https://img\.shields\.io/github/[^)\s]+", ROOT_README.read_text()
    )
    assert len(urls) >= 3
    assert all("terraapply/NetBird-Docker-Host" in u for u in urls)


def test_readme_badges_use_one_style():
    urls = re.findall(r"https://img\.shields\.io/[^)\s]+", ROOT_README.read_text())
    assert len(urls) >= 10
    assert all("style=flat-square" in u for u in urls)


def test_readme_has_server_install():
    text = ROOT_README.read_text()
    for heading in (
        "## Requirements",
        "### Server VM",
        "### Inbound ports",
        "### DNS",
        "### GitHub OAuth App",
        "## Deploy the server",
        "### Fill in netbird.yaml",
        "### Run it",
        "### After the first run",
        "### Prove it works",
        "## Operate",
        "### Everyday commands",
        "### Exit codes",
        "### Common tasks",
    ):
        assert f"\n{heading}\n" in text, heading


def test_server_readme_has_no_install_steps():
    text = SERVER_README.read_text()
    for heading in (
        "## Quick start",
        "## Before you start",
        "## Install",
        "## Everyday commands",
    ):
        assert f"\n{heading}\n" not in text, heading
    assert "../README.md#deploy-the-server" in text
    assert "../README.md#operate" in text


def test_readme_deploy_commands_follow_cd():
    # A copied block must not run ./deploy.py from the wrong directory.
    blocks = re.findall(
        r"```bash\n(.*?)```", doc_section(ROOT_README, "## Deploy the server"), re.S
    )
    first_cd = next(
        i for i, b in enumerate(blocks) if "cd NetBird-Docker-Host/netbird-server" in b
    )
    first_run = next(i for i, b in enumerate(blocks) if "./deploy.py" in b)
    assert first_cd < first_run
