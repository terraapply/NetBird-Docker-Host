---
name: netbird-extend
description: Add or change a feature in this NetBird repo or in one running deployment of it, such as a new netbird.yaml option, a template change, a deploy.py fix or a version bump, with tests and docs. Use when someone wants NetBird to do something new, a setting changed, or a change contributed back.
---

# Extend NetBird Docker Host

Before anything else, apply [Where am I?](../../../AGENTS.md#where-am-i) and [Secret files](../../../AGENTS.md#secret-files) from `AGENTS.md`.

First ask: should this change **the repo** (code, tests and docs, ready for a pull request), or only **this deployment**? The answer picks the path below.

## Path A: only this deployment

1. Check whether `netbird.yaml` already supports it: read `netbird.example.yaml` (no secrets) and the [server README](../../../netbird-server/README.md).
2. If it does, change that one key with a targeted command shown to the user first (or let the user type it, if it is a secret), confirm with `./deploy.py config`, then run `./deploy.py`.
3. If it does not, explain the limits before touching anything:
   - `deploy.py` always runs Compose with `-f docker-compose.yml`, so a `docker-compose.override.yml` is ignored.
   - The only local route is editing a tracked file (a template, `docker-compose.yml`), and that edit conflicts with the next `git pull`.
4. Offer Path B instead: turn the change into a proper `netbird.yaml` option, so it survives updates and helps other users. Restricting login to GitHub teams, today a template edit in [Hardening and extras](../../../netbird-server/README.md#hardening-and-extras), is a good example.
5. Only if the user declines, make the local edit, keep it small, and tell them how to carry it across updates: `git stash` before `git pull`, then `git stash pop` and resolve any conflict. Re-run `./deploy.py`.

## Path B: change the repo

Read the code and its tests before changing either. Follow [CONTRIBUTING.md](../../../CONTRIBUTING.md) and the [Conventions](../../../AGENTS.md#conventions) in `AGENTS.md`.

**A new `netbird.yaml` option** passes through these places in `netbird-server/`:

1. `deploy.py`, `Config.__init__`: read it with `need("block.key", <default>)`. Any default other than `None` keeps every existing `netbird.yaml` working; with no default the key is required, and every current install fails with exit 2 after `git pull`. A value with no sensible default is read with `raw.get()`, the way `oidc.redirect_uri` is.
2. `template_vars()` for a value used in `template/*.tmpl`, or `env_file_vars()` only if `docker-compose.yml` interpolates it.
3. A secret needs two more things:
   - `./deploy.py config` hides values by variable name, in `_redact()`: names containing `secret`, `password`, `key` or `dsn`. Name the variable to match, or extend `_redact()` and `test_redact`; otherwise the "safe" config view prints it.
   - `secrets()` makes a value required: empty, `replace_me` or unsafe characters stop `deploy.py` with exit 2. Add a required secret there, never an optional one.
4. `netbird.example.yaml`: the key with a comment saying what it does, and its generator command if it is a secret.
5. The server README section that covers it.
6. Tests in `netbird-server/tests/`, with the fixture `tests/fixtures/netbird.test.yaml`. Note that `test_env_file_vars_keys` pins the exact `.env` keys.

**A `deploy.py` bug fix** starts with a test that fails without the fix. Keep its message style: lowercase `error:` and `warn:`, and every failure says how to fix it.

**A NetBird version bump** moves three images together: `netbirdio/netbird-server` and `netbirdio/dashboard` in `netbird.example.yaml`, and `netbirdio/netbird` in `netbird-agent/docker/docker-compose.yml`. The test `test_client_matches_server_release` in `netbird-agent/tests/test_agent_compose.py` enforces that the server and client match. Renovate groups them the same way.

**A changed procedure** goes into the README first and the matching skill in `.agents/skills/` second. Skills link to the README, never copy it.

**Finish every repo change** with:

1. A line under `## [Unreleased]` in `CHANGELOG.md`, written for someone running the stack.
2. Every command in [Checks before a repo change](../../../AGENTS.md#checks-before-a-repo-change), all passing.
3. A commit with the right prefix, and a pull request body following `.github/pull_request_template.md`, but only when the user asks for them. Never commit or push unasked.
