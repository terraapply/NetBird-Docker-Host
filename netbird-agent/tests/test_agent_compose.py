"""Checks for the Docker install of the NetBird agent in netbird-agent/docker/."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

DOCKER_DIR = Path(__file__).resolve().parents[1] / "docker"
REPO_ROOT = DOCKER_DIR.parents[1]

needs_docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker not installed"
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # A value exported in the shell would hide a missing one in .env.
    monkeypatch.delenv("NB_MANAGEMENT_URL", raising=False)
    monkeypatch.delenv("NB_HOSTNAME", raising=False)


def compose():
    return yaml.safe_load((DOCKER_DIR / "docker-compose.yml").read_text())


def service():
    return compose()["services"]["netbird"]


def prepare(tmp):
    target = tmp / "docker"
    shutil.copytree(DOCKER_DIR, target)
    shutil.copy(target / ".env.example", target / ".env")
    (target / "setup-key").write_text("TESTKEY")
    return target


def compose_cmd(*args, cwd):
    return subprocess.run(
        ["docker", "compose", *args], cwd=cwd, capture_output=True, text=True
    )


def test_image_pinned():
    assert re.fullmatch(r"netbirdio/netbird:\d+\.\d+\.\d+", service()["image"])


def test_runs_with_host_network_and_caps():
    svc = service()
    assert svc["network_mode"] == "host"
    assert set(svc["cap_add"]) == {"NET_ADMIN", "SYS_ADMIN", "SYS_RESOURCE"}
    assert "/dev/net/tun" in svc["devices"]
    assert svc["restart"] == "unless-stopped"


def test_state_volume_persists_registration():
    # A spent one-off key cannot register again; the state volume keeps the
    # peer's registration across restarts and recreates.
    assert "state:/var/lib/netbird" in service()["volumes"]
    assert "state" in compose()["volumes"]


def test_setup_key_is_a_compose_file_secret():
    # A file secret fails loudly when the file is missing; a bind mount would
    # create an empty directory in its place.
    svc = service()
    assert svc["environment"]["NB_SETUP_KEY_FILE"] == "/run/secrets/netbird_setup_key"
    assert "NB_SETUP_KEY" not in svc["environment"]
    assert svc["secrets"] == ["netbird_setup_key"]
    assert compose()["secrets"]["netbird_setup_key"] == {"file": "./setup-key"}


def test_env_example_keys():
    keys = {
        line.split("=", 1)[0]
        for line in (DOCKER_DIR / ".env.example").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert keys == {"NB_MANAGEMENT_URL", "NB_HOSTNAME"}


@pytest.mark.parametrize(
    "path",
    [
        "netbird-agent/docker/.env",
        "netbird-agent/docker/setup-key",
        ".env",
        "netbird-agent/.env",
    ],
)
def test_secrets_are_gitignored(path):
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT)
    assert result.returncode == 0, f"{path} is not gitignored"


@needs_docker
def test_compose_config_valid(tmp_path):
    result = compose_cmd("config", "-q", cwd=prepare(tmp_path))
    assert result.returncode == 0, result.stderr


@needs_docker
def test_compose_requires_management_url(tmp_path):
    target = prepare(tmp_path)
    env = target / ".env"
    env.write_text(
        "".join(
            line
            for line in env.read_text().splitlines(keepends=True)
            if not line.startswith("NB_MANAGEMENT_URL=")
        )
    )
    result = compose_cmd("config", "-q", cwd=target)
    assert result.returncode != 0
    assert "NB_MANAGEMENT_URL" in result.stderr


@needs_docker
def test_compose_from_other_cwd_resolves_secret(tmp_path):
    target = prepare(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = compose_cmd(
        "-f",
        str(target / "docker-compose.yml"),
        "config",
        "--format",
        "json",
        cwd=elsewhere,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["secrets"]["netbird_setup_key"]["file"] == str(target / "setup-key")


def test_client_matches_server_release():
    # Client and server ship from one NetBird release; the Renovate netbird
    # group then moves them together.
    example = DOCKER_DIR.parents[1] / "netbird-server" / "netbird.example.yaml"
    server = yaml.safe_load(example.read_text())["images"]["netbird_server"]
    assert service()["image"].rsplit(":", 1)[1] == server.rsplit(":", 1)[1]
