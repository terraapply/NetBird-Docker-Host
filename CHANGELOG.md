# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-10-28

### Added

- `llms-install.md`: paste one line into Claude Code, Codex, Pi or OpenCode and the agent clones this repository, asks whether you want the server or an agent VM, and follows the matching install skill. The line and a launch command for each agent are under "Using an AI agent" in the README.

### Changed

- NetBird server and client 0.77.0 to 0.81.5, dashboard v2.91.1 to v2.96.0. Upgrade the server first, then move each agent to 0.81.5. Remote debug bundles requested from the dashboard now run on a peer only if its client opts in with `--allow-remote-jobs`.
- Traefik v3.6 to v3.7 and Dex v2.45.1 to v2.46.1. No change to `netbird.yaml` is needed; run `./deploy.py` after pulling to switch. Postgres stays on 17: a new major cannot start on the old data directory.

## [0.2.0] - 2026-10-27

### Added

- NetBird agent install for Linux VMs, with Docker (`netbird-agent/docker/`) or the native package; the setup key is read from a file in both.
- A test that every relative link and anchor in the docs resolves.
- Instructions for coding agents (Claude Code, OpenCode, Codex and others): `AGENTS.md` with the rules, plus skills to install the server and agents, maintain, troubleshoot and extend the stack. Agents are told never to open files that hold secrets.
- "Match the server version" in the install guide: pin a native agent to the server's NetBird release, since the installer always fetches the latest client.
- `scripts/check_versions.py` lists every version this repository pins (NetBird, Traefik, Dex, Postgres, dev tools, GitHub Actions) and the newest release of each. Two agent skills for maintainers build on it: `auto-upgrade` opens tested upgrade pull requests, one per group, and `release-guru` picks the next version from this changelog, opens the release pull request and tags the release.

### Changed

- The root README is now the full install guide (requirements, deploying the server, joining agents, everyday commands) with badges, a Mermaid architecture diagram and quick navigation. The server and agent READMEs hold the reference material: how it works, day-2 operations and troubleshooting.

## [0.1.0] - 2026-10-24

### Added

- Self-hosted NetBird server stack in `netbird-server/`: Traefik with Let's Encrypt, NetBird server, dashboard, Dex for GitHub-organisation login and Postgres, driven by `deploy.py` from a single `netbird.yaml`.
- Unit tests for `deploy.py` and a CI workflow (lint, format, YAML, shell and tests on Python 3.10 and 3.12).
- Contributing guide, security policy, code of conduct, issue forms and a pull request template.
- Release workflow that publishes the matching `CHANGELOG.md` section when a `v*` tag is pushed.
- Renovate configuration that keeps the image tags in `netbird.example.yaml` current and never proposes a Postgres major upgrade.

### Fixed

- `oidc.redirect_uri` now also sets the redirect URI registered in Dex, so the README fix for "Unregistered redirect_uri" works. The `dex_redirect_uri` check now says a rejection means the running Dex is not serving the rendered config.
- The first-run instructions point at `oidc.client_secret` and `server.store_encryption_key` in `netbird.yaml` instead of `.env` variables that do not exist.
- A `netbird.yaml` with a YAML syntax error, or one that is not a mapping, is reported as a config error (exit 2) instead of a traceback.
- A non-integer `schema_version` (for example `"1"`) is reported as a config error (exit 2) instead of a traceback.
- `deploy.py` no longer exits on hosts without `git`; it warns and skips the check that `netbird.yaml` is not committed.

[Unreleased]: https://github.com/terraapply/NetBird-Docker-Host/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/terraapply/NetBird-Docker-Host/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/terraapply/NetBird-Docker-Host/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/terraapply/NetBird-Docker-Host/releases/tag/v0.1.0
