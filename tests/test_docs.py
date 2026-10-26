"""Checks over the tracked Markdown docs: links resolve, no placeholders left."""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_README = REPO_ROOT / "netbird-agent" / "README.md"

HEADING = re.compile(r"^(?:>\s*)?#{1,6}\s+(.*?)\s*#*\s*$")
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(```|~~~)")


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


def test_agent_readme_warns_one_method_per_vm():
    # Two clients on one VM fight over the same WireGuard interface, so the
    # warning must come before the reader picks an option.
    text = AGENT_README.read_text()
    intro = text.split("\n## Option A: Docker", 1)[0]
    assert "one method per VM" in intro


def test_agent_readme_never_puts_setup_key_on_command_line():
    bad = [
        line
        for line in AGENT_README.read_text().splitlines()
        if re.search(r"--setup-key[\s=]|NB_SETUP_KEY=", line)
    ]
    assert bad == []


def test_agent_readme_rekey_steps_are_runnable():
    # A bare `netbird up` skips sudo, the management URL and the key file,
    # and starts the SSO login instead of using the new key.
    trouble = AGENT_README.read_text().split("\n## Troubleshooting", 1)[1]
    assert "`netbird up`" not in trouble
    assert "(#option-b-native)" in trouble


def test_agent_readme_has_match_server_version():
    # The install script and apt install the latest client, which can be newer
    # than the server; the README must say how to pin it to the server's release.
    text = AGENT_README.read_text()
    section = text.split("\n## Match the server version", 1)[1].split("\n## ", 1)[0]
    assert "./deploy.py config" in section
    assert "netbird=" in section
    native = text.index("## Option B: Native")
    match = text.index("## Match the server version")
    assert native < match < text.index("## Verify")
    upgrade = text.split("\n## Upgrade", 1)[1].split("\n## ", 1)[0]
    assert "netbird=" in upgrade
