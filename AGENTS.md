# NetBird Docker Host: guide for coding agents

Read this before doing anything in this repo. The READMEs hold the procedures; this file holds the rules and points at the skill for each job.

## What this repo is

A self-hosted [NetBird](https://netbird.io) network for Linux VMs: one VM runs the control plane in Docker, other VMs join it as peers over WireGuard.

| Path | What it is |
|---|---|
| `netbird-server/` | The control plane: five containers driven by `deploy.py` from one config file, `netbird.yaml`. See [its README](netbird-server/README.md). |
| `netbird-agent/` | The peer client, installed with Docker (`netbird-agent/docker/`) or natively. See [its README](netbird-agent/README.md). |
| `tests/`, `netbird-*/tests/` | pytest suites. No network; Docker tests skip when Docker is missing. |
| `.agents/skills/` | Task skills, also reachable through `.claude/skills/`. |

Overview: [README.md](README.md). Contribution rules: [CONTRIBUTING.md](CONTRIBUTING.md).

## Hard rules

1. Edit `netbird.yaml` or a template in `netbird-server/template/`, never `config.yaml`, `dex/config.yaml` or `.env`. `deploy.py` regenerates them on every run and the change is lost.
2. Never open, print, paste or commit a secret file; see [Secret files](#secret-files). Whatever you read is sent to the AI provider.
3. Never change `server.store_encryption_key` on an existing database. Every encrypted column becomes unreadable, with no way back. Refuse and explain, even when asked to "rotate everything".
4. A setup key is written only with the hidden-prompt file method in [the agent README](netbird-agent/README.md#setup-keys), never as a command-line argument or an environment variable: it would end up in shell history, `ps` output and `docker inspect`.
5. One agent install method per VM. A Docker client and a native client fight over the same WireGuard interface.
6. NetBird server and agent versions move together. Upgrade the server first; an agent newer than its server is untested.
7. Ask before anything hard to undo; see [Confirm or refuse](#confirm-or-refuse).
8. Never commit or push unless the user asks.

## Secret files

Never open these: not with `cat`, an editor, a file-reading tool, or a `grep` that prints lines.

- `netbird-server/netbird.yaml`: every setting and every secret
- `netbird-server/.env`: holds `POSTGRES_PASSWORD`
- `netbird-server/config.yaml` and `netbird-server/dex/config.yaml`: rendered secrets
- `netbird-agent/docker/setup-key` and `~/netbird-setup-key`
- anything under `~/netbird-backups/`

Never run `docker compose config` or `docker inspect` on the server, directly or through `./deploy.py compose -- config`: both print `POSTGRES_PASSWORD`.

Do this instead:

- See the server config with `./deploy.py config`. It prints every value and shows secrets as `<redacted>`.
- Find unfinished config with `./deploy.py validate`. Its preflight names any value still set to `replace_me`.
- Check these files by metadata only: `stat`, `ls -l`, `test -s`, `grep -c` (a count, never the lines).
- Change a non-secret key (an image tag, `local_auth`, a domain) with one targeted command, for example `sed -i 's|^\(  netbird_server: \).*|\1netbirdio/netbird-server:<tag>|' netbird.yaml`. Show it to the user before running it, then confirm the result with `./deploy.py config`. Claude Code's Edit tool needs a Read first, so do not use it on these files.
- For a secret value, tell the user which key to fill and the command that generates it (for example `openssl rand -base64 32`), and let them type it in.

`netbird-agent/docker/.env` holds only the management URL and hostname, so it is not on this list.

## Where am I?

Work this out with read-only checks before running anything, and tell the user what you concluded. Ask when the signals disagree.

| Signal | You are on |
|---|---|
| `netbird-server/netbird.yaml` exists (`test -f`), or `docker ps --format '{{.Names}}'` lists `netbird-server` | the server VM |
| `command -v netbird` finds the CLI, `netbird-agent/docker/.env` exists, or `docker ps` lists `netbird-agent` | an agent VM |
| none of these | a laptop, or any machine with only the code |

`docker ps` may need `sudo`. If it is refused, say so instead of guessing.

- **On a VM:** run read-only commands yourself. Ask before anything that changes state.
- **On a laptop:** you cannot see the VM. Give the user one short block of commands at a time, say what each will show, and read the pasted output before the next step. Use SSH only if the user offers it, under the same rules.
- **A native agent VM has no clone** of this repo, so an agent started there gets none of these files. Work from a clone elsewhere and hand over commands, or have the user clone the repo on the VM.

## Confirm or refuse

Ask, and wait for a yes, before:

- `docker compose down -v` or `docker volume rm` (deletes the database or a peer registration)
- restoring a database backup
- `shred` of a setup-key file
- setting `server.local_auth: false` (GitHub becomes the only way in)
- rotating any secret
- deleting a peer in the dashboard
- `git push`

Refuse, and explain why:

- changing `server.store_encryption_key` on an existing database
- putting a setup key on a command line or in an environment variable

## Learning loop

When you fix a problem the troubleshooting tables do not cover, offer to add one row (symptom, cause, fix) to [the server table](netbird-server/README.md#troubleshooting) or [the agent table](netbird-agent/README.md#troubleshooting). If the user wants it upstream, follow [Conventions](#conventions) and open it as its own PR.

## Checks before a repo change

Run these from the repo root ([setup](CONTRIBUTING.md#setup)). CI runs the same ones.

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/yamllint .
shellcheck $(git ls-files '*.sh')
git grep -n -e "$(printf '\342\200\224')" -e "$(printf '\342\200\223')"   # must print nothing
```

## Conventions

- Commit messages start with `feat:`, `fix:`, `docs:`, `test:`, `style:`, `ci:` or `chore:`. One change per PR; the PR body follows `.github/pull_request_template.md`.
- Add a line under `## [Unreleased]` in `CHANGELOG.md`, written for someone running the stack.
- A bug fix in `deploy.py` comes with a test that fails without the fix.
- `deploy.py` messages are lowercase `error:` and `warn:`, and every failure says how to fix it.
- No em or en dashes in any file. Use a colon, a comma or parentheses.
- No real domains, email addresses or secrets in commits. Examples use `example.com`.

## Skills

Each job has a skill in `.agents/skills/`. Load the one that fits before you start.

| Skill | Use it when |
|---|---|
