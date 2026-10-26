"""Checks over AGENTS.md and the agent skills: structure, links, safety rules."""

import os
import re
from pathlib import Path

import pytest
import yaml
from test_docs import FENCE, anchors

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_MD = REPO_ROOT / "AGENTS.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
CLAUDE_SKILLS_DIR = REPO_ROOT / ".claude" / "skills"
READMES = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "netbird-server" / "README.md",
    REPO_ROOT / "netbird-agent" / "README.md",
)

SKILLS = (
    "netbird-install-server",
    "netbird-install-agent",
    "netbird-maintain",
)

# Files an agent never opens: whatever it reads is sent to the AI provider.
SECRET_PATHS = (
    "netbird-server/netbird.yaml",
    "netbird-server/.env",
    "netbird-server/config.yaml",
    "netbird-server/dex/config.yaml",
    "netbird-agent/docker/setup-key",
    "~/netbird-setup-key",
    "~/netbird-backups/",
)

SETUP_KEY_ON_CLI = re.compile(r"--setup-key[\s=]|NB_SETUP_KEY=")
README_LINK = re.compile(r"\]\([^)]*README\.md")


def skill_text(name):
    return (SKILLS_DIR / name / "SKILL.md").read_text()


def frontmatter(name):
    lines = skill_text(name).splitlines()
    assert lines[0] == "---"
    end = lines.index("---", 1)
    return yaml.safe_load("\n".join(lines[1:end]))


def names_in(path):
    return {p.name for p in path.iterdir()} if path.is_dir() else set()


def fenced_blocks(text):
    blocks, current = [], None
    for line in text.splitlines():
        if FENCE.match(line):
            if current is None:
                current = []
            else:
                blocks.append("\n".join(current))
                current = None
        elif current is not None:
            current.append(line)
    return blocks


def test_claude_md_imports_agents_md():
    assert "@AGENTS.md" in CLAUDE_MD.read_text().splitlines()


def test_agents_md_names_secret_files_and_leaky_commands():
    text = AGENTS_MD.read_text()
    for needle in (
        *SECRET_PATHS,
        "docker compose config",
        "docker inspect",
        "./deploy.py config",
    ):
        assert needle in text


def test_agents_md_refuses_encryption_key_change():
    rules = AGENTS_MD.read_text().split("\n## Hard rules", 1)[1].split("\n## ", 1)[0]
    assert "store_encryption_key" in rules


def test_agents_md_has_required_sections():
    required = {
        "where-am-i",
        "secret-files",
        "confirm-or-refuse",
        "learning-loop",
        "skills",
    }
    assert required <= set(anchors(AGENTS_MD))


def test_agents_md_never_puts_setup_key_on_command_line():
    assert not SETUP_KEY_ON_CLI.search(AGENTS_MD.read_text())


def test_skill_folders_match_list():
    assert names_in(SKILLS_DIR) == set(SKILLS)
    assert names_in(CLAUDE_SKILLS_DIR) == set(SKILLS)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_frontmatter(name):
    meta = frontmatter(name)
    assert set(meta) == {"name", "description"}
    assert meta["name"] == name
    assert 0 < len(meta["description"]) <= 300


@pytest.mark.parametrize("name", SKILLS)
def test_claude_symlink_points_at_skill(name):
    link = CLAUDE_SKILLS_DIR / name
    assert link.is_symlink()
    assert os.readlink(link) == f"../../.agents/skills/{name}"
    assert link.resolve() == (SKILLS_DIR / name).resolve()


@pytest.mark.parametrize("name", SKILLS)
def test_agents_md_links_skill(name):
    assert f"(.agents/skills/{name}/SKILL.md)" in AGENTS_MD.read_text()


@pytest.mark.parametrize("name", SKILLS)
def test_skill_starts_with_where_am_i(name):
    assert "AGENTS.md#where-am-i" in skill_text(name)


@pytest.mark.parametrize("name", SKILLS)
def test_skill_links_a_readme(name):
    assert README_LINK.search(skill_text(name))


@pytest.mark.parametrize("name", SKILLS)
def test_skill_never_puts_setup_key_on_command_line(name):
    assert not SETUP_KEY_ON_CLI.search(skill_text(name))


@pytest.mark.parametrize("name", SKILLS)
def test_skill_does_not_copy_readme_blocks(name):
    # A copied procedure drifts from the README it came from; link it instead.
    readme_blocks = [b for doc in READMES for b in fenced_blocks(doc.read_text())]
    copied = [
        block
        for block in fenced_blocks(skill_text(name))
        if block.count("\n") >= 1 and any(block in r for r in readme_blocks)
    ]
    assert copied == []


def test_install_server_checks_without_opening_config():
    text = skill_text("netbird-install-server")
    for needle in (
        "./deploy.py config",
        "./deploy.py validate",
        "openssl rand -base64 32",
        "netbird-install-agent",
    ):
        assert needle in text


def test_install_agent_enforces_one_method_and_version():
    text = skill_text("netbird-install-agent")
    for needle in ("one method per VM", "#match-the-server-version", "curl -I"):
        assert needle in text


def test_maintain_covers_rotation_exceptions():
    text = skill_text("netbird-maintain")
    for needle in ("store_encryption_key", "ALTER USER", "oidc.client_secret"):
        assert needle in text


def test_maintain_edits_without_opening_config():
    text = skill_text("netbird-maintain")
    for needle in (
        "./deploy.py update",
        "./deploy.py config",
        "#backups",
        "#match-the-server-version",
    ):
        assert needle in text
