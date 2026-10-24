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

The tests need no network and no running stack. One test runs `docker compose config` and skips itself when Docker is not installed.

## Pull requests

- One change per pull request.
- Add a line under `## [Unreleased]` in `CHANGELOG.md`, written for someone running the stack.
- Commit messages start with `feat:`, `fix:`, `docs:`, `test:`, `style:`, `ci:` or `chore:`.
- Bug fixes in `deploy.py` come with a test that fails without the fix.
- Keep the style of `deploy.py`: lowercase `error:` and `warn:` messages, and every failure prints how to fix it.

## Never commit

- `netbird-server/netbird.yaml` or anything `deploy.py` generates (`config.yaml`, `dex/config.yaml`, `.env`).
- Backups, setup keys, client secrets, or real domains and email addresses.

## Text style

No em dashes or en dashes in any file; a pre-commit hook and CI reject them. Use a colon, a comma or parentheses instead.

## Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
