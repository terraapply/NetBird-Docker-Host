"""Shared helpers for the deploy.py unit tests.

deploy.py resolves every path from its module-level HERE, so tests point HERE
at a temp copy of the server folder instead of refactoring the script. Nothing
here touches Docker or the network.
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

SERVER_DIR = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "netbird.test.yaml"

sys.path.insert(0, str(SERVER_DIR))

import deploy  # noqa: E402  (needs SERVER_DIR on sys.path first)


def load_fixture():
    with open(FIXTURE) as fh:
        return yaml.safe_load(fh)


@pytest.fixture
def raw():
    return load_fixture()


def make_cfg(raw, path="netbird.yaml"):
    return deploy.Config(raw, path)


def make_ctx(cfg):
    args = argparse.Namespace(
        timeout_scale=1.0, strict=False, show_onboarding=False, only=None, skip=None
    )
    return deploy.Ctx(cfg, args)


def write_config(path, raw):
    path.write_text(yaml.safe_dump(raw))
    os.chmod(path, 0o600)
    return path


def expect_exit(capsys, fn, *needles, code=2):
    """Run fn, assert it exits with code, return stderr after checking needles."""
    with pytest.raises(SystemExit) as e:
        fn()
    assert e.value.code == code
    err = capsys.readouterr().err
    for needle in needles:
        assert needle in err
    return err


@pytest.fixture
def server_dir(tmp_path, monkeypatch):
    shutil.copytree(SERVER_DIR / "template", tmp_path / "template")
    shutil.copytree(SERVER_DIR / "postgres", tmp_path / "postgres")
    shutil.copy(SERVER_DIR / "docker-compose.yml", tmp_path)
    monkeypatch.setattr(deploy, "HERE", str(tmp_path))
    return tmp_path


@pytest.fixture
def git_untracked(monkeypatch):
    def fake_run(argv, ctx, **kw):
        assert argv[:2] == ["git", "ls-files"], "unexpected command: %r" % (argv,)
        return 1, "", ""

    monkeypatch.setattr(deploy, "run", fake_run)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # preflight refuses to run when the shell exports a variable the generated
    # .env also sets; a dev box or CI runner must not leak one into the tests.
    for key in make_cfg(load_fixture()).env_file_vars():
        monkeypatch.delenv(key, raising=False)
