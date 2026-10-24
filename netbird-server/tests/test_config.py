import shutil
import subprocess
import sys

import deploy
from conftest import SERVER_DIR, expect_exit, make_cfg, write_config


def test_fixture_loads(raw):
    cfg = make_cfg(raw)
    assert cfg.netbird_domain == "netbird.example.com"
    assert cfg.oidc_redirect_uri == "https://netbird.example.com/oauth2/callback"
    assert cfg.project == "netbird"


def test_missing_required_field_exits_2(raw, capsys):
    del raw["domains"]
    expect_exit(capsys, lambda: make_cfg(raw), "domains.netbird")


def test_missing_image_exits_2(raw, capsys):
    del raw["images"]["dex"]
    expect_exit(capsys, lambda: make_cfg(raw), "images.dex")


def test_newer_schema_version_exits_2(raw, capsys):
    raw["schema_version"] = 2
    expect_exit(capsys, lambda: make_cfg(raw), "newer than this script understands")


def test_main_bad_config_exits_2(raw, tmp_path, capsys):
    del raw["domains"]
    path = write_config(tmp_path / "netbird.yaml", raw)
    expect_exit(
        capsys,
        lambda: deploy.main(["config", "--config", str(path)]),
        "domains.netbird",
    )


def test_dsn_percent_encodes_password(raw):
    raw["postgres"]["password"] = "p@ss/w:rd"
    assert make_cfg(raw).dsn("netbird") == (
        "postgres://netbird:p%40ss%2Fw%3Ard@postgres:5432/netbird?sslmode=disable"
    )


def test_env_file_vars_keys(raw):
    assert set(make_cfg(raw).env_file_vars()) == {
        "COMPOSE_PROJECT_NAME",
        "NETBIRD_DOMAIN",
        "DEX_DOMAIN",
        "LETSENCRYPT_EMAIL",
        "TRAEFIK_IMAGE",
        "NETBIRD_SERVER_IMAGE",
        "DASHBOARD_IMAGE",
        "DEX_IMAGE",
        "POSTGRES_IMAGE",
        "POSTGRES_PASSWORD",
    }


def test_redact():
    for key in (
        "POSTGRES_PASSWORD",
        "NETBIRD_STORE_DSN",
        "NETBIRD_STORE_ENCRYPTION_KEY",
    ):
        assert deploy._redact(key, "x") == "<redacted>"
    assert deploy._redact("NETBIRD_DOMAIN", "a") == "a"


def test_cli_resolves_paths_from_script_dir(raw, tmp_path, tmp_path_factory):
    # The runbook may call netbird-server/deploy.py from the repo root: the
    # default --config must still be the netbird.yaml next to deploy.py.
    srv = tmp_path / "srv"
    srv.mkdir()
    shutil.copy(SERVER_DIR / "deploy.py", srv)
    write_config(srv / "netbird.yaml", raw)
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    p = subprocess.run(
        [sys.executable, str(srv / "deploy.py"), "config"],
        cwd=elsewhere,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 0, p.stderr
    assert "config:      %s" % (srv / "netbird.yaml") in p.stdout
