# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Self-hosted NetBird server stack in `netbird-server/`: Traefik with Let's Encrypt, NetBird server, dashboard, Dex for GitHub-organisation login and Postgres, driven by `deploy.py` from a single `netbird.yaml`.
- Unit tests for `deploy.py` and a CI workflow (lint, format, YAML, shell and tests on Python 3.10 and 3.12).
- Contributing guide, security policy, code of conduct, issue forms and a pull request template.
- Release workflow that publishes the matching `CHANGELOG.md` section when a `v*` tag is pushed.
- Renovate configuration that keeps the image tags in `netbird.example.yaml` current and never proposes a Postgres major upgrade.

### Fixed

- `oidc.redirect_uri` now also sets the redirect URI registered in Dex, so the fix printed by the `dex_redirect_uri` check works.
- The first-run instructions point at `oidc.client_secret` and `server.store_encryption_key` in `netbird.yaml` instead of `.env` variables that do not exist.
- A `netbird.yaml` with a YAML syntax error, or one that is not a mapping, is reported as a config error (exit 2) instead of a traceback.
- A non-integer `schema_version` (for example `"1"`) is reported as a config error (exit 2) instead of a traceback.
- `deploy.py` no longer exits on hosts without `git`; it warns and skips the check that `netbird.yaml` is not committed.
