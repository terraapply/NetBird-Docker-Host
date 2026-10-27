# Contributing

Thanks for helping. This repo holds a self-hosted NetBird server stack (`netbird-server/`) and NetBird agent installs (`netbird-agent/`).

## Setup

```bash
git clone https://github.com/terraapply/NetBird-Docker-Host.git
cd NetBird-Docker-Host
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pre-commit install
```

`deploy.py` itself needs only Python 3.10+ and PyYAML. The dev requirements add the test and lint tools.

## Checks

Run these before opening a pull request. CI runs the same ones.

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/yamllint .
shellcheck $(git ls-files '*.sh')
```

The tests need no network and no running stack. The tests that run `docker compose config` skip themselves when Docker is not installed.

## Pull requests

- One change per pull request.
- Add a line under `## [Unreleased]` in `CHANGELOG.md`, written for someone running the stack.
- Commit messages start with `feat:`, `fix:`, `docs:`, `test:`, `style:`, `ci:` or `chore:`.
- Bug fixes in `deploy.py` come with a test that fails without the fix.
- Keep the style of `deploy.py`: lowercase `error:` and `warn:` messages, and every failure prints how to fix it.

## Keeping versions current

Versions are pinned in several places: the images in `netbird-server/netbird.example.yaml`, the client in `netbird-agent/docker/docker-compose.yml`, the dev tools in `requirements-dev.txt` and `.pre-commit-config.yaml`, the actions and Python versions in `.github/workflows/`, and the docs that quote them. `scripts/check_versions.py` lists every pin and the newest release of each. It needs network and changes nothing:

```bash
python3 scripts/check_versions.py
python3 scripts/check_versions.py --json --group netbird
```

The first prints a table of every pin. The second limits it to one group and adds, under `locations`, every line in the repository that names each version. GitHub allows 60 anonymous API requests an hour; if a row says it hit the limit, set `GITHUB_TOKEN` or `GH_TOKEN`.

Upgrade one group per pull request:

| Group | What it covers |
|---|---|
| `netbird` | NetBird server, dashboard and client |
| `images` | Traefik, Dex and Postgres |
| `tooling` | `requirements-dev.txt` and the pre-commit hooks |
| `actions` | GitHub Actions and the newest Python in CI |

The rules:

- NetBird server and client run the same release; `test_client_matches_server_release` fails otherwise. The dashboard has its own version and moves only when the server and client move: a newer dashboard can call API the server does not have yet.
- Read the release notes of every major version before applying it, and below 1.0 of every minor too: `0.77` to `0.78` may break things. Read each release in between, oldest first, for config keys, environment variables, ports, CLI flags, Traefik labels and Dex connector settings this repository uses. Upgrade to the newest release that needs no change here; if one does, stop below it and make that change in its own pull request.
- Never move Postgres to a new major version: a new major cannot start on the old data directory. The script marks it `APPLY no`.
- The oldest Python in CI, 3.10, stays: `deploy.py` runs on the system Python of Ubuntu 22.04. Only the newest one moves, and the script does not offer a tool release that drops a Python CI still runs.
- ruff and yamllint move together with their pre-commit hooks; the script flags a pair that differs.
- Change every line listed under `locations`, reading each first: the README badge, doc examples and the test fixture quote the NetBird version too, and a hit can be unrelated text.
- After a `tooling` bump, reinstall `.venv` from `requirements-dev.txt` and run `ruff format .` and `ruff check --fix .`.
- Run every command in [Checks](#checks), then the script again for that group. Every pin you changed shows the new version under `CURRENT`, and no row has a `must match`, `differ` or `not found` note. A release you held back, or a Postgres major marked `APPLY no`, still shows as newer; that is expected.
- `netbird` and `images` pull requests add a `CHANGELOG.md` line for people running the stack. `tooling` and `actions` change nothing for them and add none; say so in the pull request.
- Wait for the pull request's CI: it runs the tests on every Python in the matrix, where your local run used one.

Merging changes this repository only. A running server is upgraded as in [Upgrades](netbird-server/README.md#upgrades), and agents after it.

## Releasing

Releases follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The next version comes from what is under `## [Unreleased]` in `CHANGELOG.md`:

| Under `## [Unreleased]` | Below 1.0 | From 1.0 |
|---|---|---|
| Removed, or a change that breaks existing setups | minor | major |
| Added, Changed or Deprecated | minor | minor |
| Only Fixed or Security | patch | patch |

Going to 1.0.0 is a maintainer's decision, never the outcome of the table.

1. Open a release pull request that changes only `CHANGELOG.md`. Move the entries under `## [Unreleased]` to a new `## [X.Y.Z] - YYYY-MM-DD` heading, leave an empty `## [Unreleased]` above it, and update the links at the bottom: `[Unreleased]` compares `vX.Y.Z...HEAD`, and `[X.Y.Z]` compares the previous tag with `vX.Y.Z`. `tests/test_changelog.py` checks the result.
2. If another pull request merges first and adds lines under `## [Unreleased]`, rebase the release pull request, move those lines into the release, since they are in the code being released, and push with `git push --force-with-lease`. Check the version against the table again.
3. Once the release pull request has merged and CI has passed on its merge commit, tag that merge commit and push only the tag:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z" <merge-commit>
   git push origin vX.Y.Z
   ```

   Tag the merge commit, not the newest commit on `main`: anything merged after it belongs to the next release.
4. The tag starts [`release.yml`](.github/workflows/release.yml), which publishes a GitHub release with the `## [X.Y.Z]` section as its notes. Check it with `gh release view vX.Y.Z`.

Do not delete or move a tag once it is pushed without agreeing it with the other maintainers: someone may already have fetched it.

## Agent docs

[`AGENTS.md`](AGENTS.md) and the skills in `.agents/skills/` tell coding agents how to work with this repo. They link to the READMEs, or to this guide for work on the repository itself, and never copy them, so when a procedure changes, update the README or this guide first and the matching skill or `AGENTS.md` second.

A new skill needs its folder in `.agents/skills/`, a symlink to it in `.claude/skills/`, a row in the `AGENTS.md` skill table, a line in the README's "Using an AI agent" table, and its name in `DEPLOY_SKILLS` or `REPO_SKILLS` in `tests/test_agent_skills.py`.

## Never commit

- `netbird-server/netbird.yaml` or anything `deploy.py` generates (`config.yaml`, `dex/config.yaml`, `.env`).
- Backups, setup keys, client secrets, or real domains and email addresses.

## Text style

No em dashes or en dashes in any file; a pre-commit hook and CI reject them. Use a colon, a comma or parentheses instead.

## Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
