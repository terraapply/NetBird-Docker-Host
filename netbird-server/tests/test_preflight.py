import deploy
import pytest
from conftest import expect_exit, make_cfg, make_ctx, write_config

pytestmark = pytest.mark.usefixtures("server_dir", "git_untracked")


def preflight(raw, tmp_path):
    path = write_config(tmp_path / "netbird.yaml", raw)
    deploy.phase_preflight(make_ctx(make_cfg(raw, str(path))), resources=False)


def test_valid_config_passes(raw, tmp_path):
    preflight(raw, tmp_path)


def test_unquoted_numeric_secret_exits_2(raw, tmp_path, capsys):
    raw["postgres"]["password"] = 123456
    expect_exit(capsys, lambda: preflight(raw, tmp_path),
                "must be quoted strings", "postgres.password (int)")


def test_unpadded_store_key_exits_2(raw, tmp_path, capsys):
    raw["server"]["store_encryption_key"] = raw["server"]["store_encryption_key"].rstrip("=")
    expect_exit(capsys, lambda: preflight(raw, tmp_path), "padding")


def test_store_key_wrong_length_exits_2(raw, tmp_path, capsys):
    raw["server"]["store_encryption_key"] = "AAAAAAAAAAAAAAAAAAAAAA=="
    expect_exit(capsys, lambda: preflight(raw, tmp_path), "exactly 32 bytes")


def test_placeholder_secret_exits_2(raw, tmp_path, capsys):
    raw["github"]["client_secret"] = "replace_me"
    expect_exit(capsys, lambda: preflight(raw, tmp_path), "unset in")


def test_unsafe_secret_chars_exits_2(raw, tmp_path, capsys):
    raw["oidc"]["client_secret"] = "abc$def"
    expect_exit(capsys, lambda: preflight(raw, tmp_path), "break the generated files")


def test_tracked_config_exits_2(raw, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(deploy, "run", lambda argv, ctx, **kw: (0, "", ""))
    expect_exit(capsys, lambda: preflight(raw, tmp_path), "tracked by git")


def test_shell_env_clash_exits_2(raw, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("NETBIRD_DOMAIN", "other.example.com")
    expect_exit(capsys, lambda: preflight(raw, tmp_path), "exported shell variables")
