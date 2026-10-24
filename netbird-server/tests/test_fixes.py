"""Regression tests for the deploy.py bugs fixed after the migration."""

import deploy
import yaml
from conftest import expect_exit, make_cfg, make_ctx, write_config


def render_dex(server_dir, raw):
    deploy.phase_render(make_ctx(make_cfg(raw)))
    return yaml.safe_load((server_dir / "dex" / "config.yaml").read_text())


def test_dex_redirect_uri_default(server_dir, raw):
    dex = render_dex(server_dir, raw)
    assert dex["staticClients"][0]["redirectURIs"] == [
        "https://netbird.example.com/oauth2/callback"
    ]


def test_dex_redirect_uri_override(server_dir, raw):
    uri = "https://netbird.example.com/oauth2/callback/github"
    raw["oidc"]["redirect_uri"] = uri
    assert render_dex(server_dir, raw)["staticClients"][0]["redirectURIs"] == [uri]


def test_onboarding_names_netbird_yaml_keys(raw, capsys):
    deploy.print_onboarding(make_cfg(raw))
    out = capsys.readouterr().out
    assert "oidc.client_secret" in out
    assert "server.store_encryption_key" in out
    assert ".env" not in out
    assert "NETBIRD_OIDC_CLIENT_SECRET" not in out


def test_invalid_yaml_exits_2(tmp_path, capsys):
    path = tmp_path / "netbird.yaml"
    path.write_text("domains: [\n")
    expect_exit(capsys, lambda: deploy.load_config(str(path)), "is not valid yaml")


def test_non_mapping_exits_2(tmp_path, capsys):
    path = tmp_path / "netbird.yaml"
    path.write_text("- a\n- b\n")
    expect_exit(capsys, lambda: deploy.load_config(str(path)), "must be a mapping")


def test_schema_version_string_exits_2(raw, capsys):
    raw["schema_version"] = "1"
    expect_exit(capsys, lambda: make_cfg(raw), "schema_version must be an integer")


def test_schema_version_bool_exits_2(raw, capsys):
    raw["schema_version"] = True
    expect_exit(capsys, lambda: make_cfg(raw), "schema_version must be an integer")


def test_preflight_without_git_warns(server_dir, raw, tmp_path, capsys, monkeypatch):
    def no_git(*args, **kw):
        raise FileNotFoundError("git")

    monkeypatch.setattr(deploy.shutil, "which", lambda name: None)
    monkeypatch.setattr(deploy.subprocess, "run", no_git)
    path = write_config(tmp_path / "netbird.yaml", raw)
    deploy.phase_preflight(make_ctx(make_cfg(raw, str(path))), resources=False)
    assert "warn: git not found" in capsys.readouterr().out


def test_dex_redirect_uri_fail_hint_points_at_stale_dex(raw, monkeypatch):
    # Dex registers exactly cfg.oidc_redirect_uri, so a rejection means the
    # running Dex is not serving the rendered config; changing
    # oidc.redirect_uri cannot fix that.
    monkeypatch.setattr(deploy, "https_get", lambda *a, **kw: deploy.Resp(400, {}, ""))
    result = deploy.check_dex_redirect_uri(make_ctx(make_cfg(raw)))
    assert result.status == deploy.FAIL
    assert any("not serving the rendered" in h for h in result.hints)
    assert not any(h.startswith("fix: set oidc.redirect_uri") for h in result.hints)
