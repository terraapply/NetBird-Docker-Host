# NetBird Docker Host: guide for coding agents

Read this before doing anything in this repo. The READMEs hold the procedures; this file holds the rules and points at the skill for each job.

## What this repo is

A self-hosted [NetBird](https://netbird.io) network for Linux VMs: one VM runs the control plane in Docker, other VMs join it as peers over WireGuard.

| Path | What it is |
|---|---|
| `README.md` | The full install guide: requirements, deploying the server, joining agents, everyday commands. |
| `netbird-server/` | The control plane: five containers driven by `deploy.py` from one config file, `netbird.yaml`. [Its README](netbird-server/README.md) is the reference: how it works, day-2 operations, troubleshooting. |
| `netbird-agent/` | The peer client, installed with Docker (`netbird-agent/docker/`) or natively. [Its README](netbird-agent/README.md) covers upgrade, uninstall and troubleshooting. |
| `tests/`, `netbird-*/tests/` | pytest suites. No network; Docker tests skip when Docker is missing. |
| `scripts/` | `check_versions.py`: every pinned version and the newest release of each. Read-only; needs network. |
| `.agents/skills/` | Task skills, also reachable through `.claude/skills/`. |

Overview: [README.md](README.md). Contribution rules: [CONTRIBUTING.md](CONTRIBUTING.md).

## Hard rules

1. Edit `netbird.yaml` or a template in `netbird-server/template/`, never `config.yaml`, `dex/config.yaml` or `.env`. `deploy.py` regenerates them on every run and the change is lost.
2. Never open, print, paste or commit a secret file; see [Secret files](#secret-files). Whatever you read is sent to the AI provider.
3. Never change `server.store_encryption_key` on an existing database. Every encrypted column becomes unreadable, with no way back. Refuse and explain, even when asked to "rotate everything".
4. A setup key is written only with the hidden-prompt file method in [Setup keys](README.md#setup-keys), never as a command-line argument or an environment variable: it would end up in shell history, `ps` output and `docker inspect`.
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

Secrets also leak through commands that never name these files. Never run:

- `docker compose config` or `docker inspect` on the server, directly or through `./deploy.py compose -- config`, nor `env`, `printenv` or `/proc/*/environ` inside a container: all print `POSTGRES_PASSWORD`.
- `grep -r` over `netbird-server/` or a home directory: it reads ignored files, secrets included. Search code with `git grep`, which skips them.
- a secret generator such as `openssl rand`: its output is the secret. The user runs it in their own terminal, not through a shell your tool shows you (such as Claude Code's `!` prefix), which puts the output into the conversation. The same goes for any command with a secret in it, like the README's `ALTER USER`.

Do this instead:

- See the server config with `./deploy.py config`. It prints every value and shows secrets as `<redacted>`.
- Find unfinished config with `grep -c replace_me netbird.yaml`, expecting `0`. Before the first deploy, `./deploy.py` also stops with exit 2 and names every secret still empty or `replace_me`, but when nothing is missing it goes on to deploy, so run it only when you mean to. After the first deploy, `./deploy.py validate` runs the same check without changing anything.
- Check these files by metadata only: `stat`, `ls -l`, `test -s`, `grep -c` (a count, never the lines).
- Change a non-secret key (an image tag, `local_auth`, a domain) with one targeted command. Keys such as `dex`, `client_id` and `client_secret` appear twice, so anchor the pattern on the key's current value too, and first check it matches exactly one line: `grep -c '^  dex: ghcr.io/dexidp/dex:' netbird.yaml` prints `1`. Then show the user the edit, for example `sed -i 's|^\(  dex: \)ghcr.io/dexidp/dex:.*|\1ghcr.io/dexidp/dex:<tag>|' netbird.yaml`, run it, and compare the whole `./deploy.py config` output with the one from before, not only the changed value. Claude Code's Edit tool needs a Read first, so do not use it on these files.
- For a secret value, tell the user which key to fill and which command generates it, and let them run it and type the value in themselves.

`netbird-agent/docker/.env` holds only the management URL and hostname, so it is not on this list.

## Where am I?

Work this out with read-only checks before running anything. Tell the user what you concluded and have them confirm it before the first command that changes state or the first diagnosis: a wrong guess runs server or agent commands on the wrong machine.

| Signal | Suggests |
|---|---|
| `docker ps --format '{{.Names}}'` lists `netbird-server` | the server VM |
| `systemctl is-active netbird` prints `active`, or `docker ps` lists `netbird-agent` | an agent VM |
| none of these | a laptop, or any machine with only the code |

A file or a CLI alone is weak evidence: an admin's laptop often runs the NetBird client and may hold a filled-in `netbird.yaml`. Trust a running service or container, and ask when unsure. On a fresh VM nothing runs yet, so ask which role it will have.

`docker ps` may need `sudo`. If it is refused, say so instead of guessing.

- **On a VM:** run read-only commands yourself. Ask before anything that changes state.
- **On a laptop:** you cannot see the VM. Give the user one short block of commands at a time, say what each will show, and read the pasted output before the next step. Use SSH only if the user offers it, under the same rules.
- **A native agent VM has no clone** of this repo, so an agent started there gets none of these files. Work from a clone elsewhere and hand over commands, or have the user clone the repo on the VM.

## Confirm or refuse

Ask, and wait for a yes, before:

- `docker compose down -v` or `docker volume rm` (deletes the database or a peer registration)
- restoring a database backup
- `shred` of a setup-key file
- setting `server.local_auth: false`, and only once every check in [Prove it works](README.md#prove-it-works) has passed: GitHub becomes the only way in
- rotating any secret
- deleting a peer in the dashboard
- `git push`
- deleting or moving a pushed tag

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
| [netbird-install-server](.agents/skills/netbird-install-server/SKILL.md) | Setting up the NetBird server on a new VM, up to the first login |
| [netbird-install-agent](.agents/skills/netbird-install-agent/SKILL.md) | Joining a VM to the network as a peer, with Docker or natively |
| [netbird-maintain](.agents/skills/netbird-maintain/SKILL.md) | Health checks, backups, restore, upgrades, secret rotation, re-keying or removing agents |
| [netbird-troubleshoot](.agents/skills/netbird-troubleshoot/SKILL.md) | Something is broken on the server or an agent VM: failed checks, login, certificates, peers |
| [netbird-extend](.agents/skills/netbird-extend/SKILL.md) | Adding or changing a feature, in the repo or in one deployment |
| [auto-upgrade](.agents/skills/auto-upgrade/SKILL.md) | Checking the repo's pinned versions for newer releases and opening upgrade PRs (upgrading a running server is netbird-maintain) |
| [release-guru](.agents/skills/release-guru/SKILL.md) | Cutting a release: choosing the version from the changelog, the release PR, then the tag |
