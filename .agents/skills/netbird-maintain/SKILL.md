---
name: netbird-maintain
description: Day-2 work on a running NetBird install from this repo, covering health checks, backups, restore, upgrades of the server and agents, secret rotation, re-keying and removing agents. Use when someone wants to back up, upgrade, update, restore, rotate a secret or check the health of NetBird.
---

# Maintain a NetBird install

Before anything else, apply [Where am I?](../../../AGENTS.md#where-am-i), [Secret files](../../../AGENTS.md#secret-files) and [Confirm or refuse](../../../AGENTS.md#confirm-or-refuse) from `AGENTS.md`. Server commands run from `netbird-server/` on the server VM.

## Health

- `./deploy.py status`: what is running, and whether first-run setup is finished.
- `./deploy.py validate`: the nine checks, changing nothing. Exit 0 is healthy; exit 4 means a check failed, so switch to `netbird-troubleshoot`.

## Backups

Follow [Backups](../../../netbird-server/README.md#backups). On the server VM you may run those commands yourself: they write to `~/netbird-backups/` without printing anything. Never open the files they produce.

- Back up the database and `netbird.yaml` together. The rows are encrypted with `server.store_encryption_key`, so a dump without its config is unreadable.
- Check the result by metadata only: `ls -l ~/netbird-backups/` shows today's files with non-zero sizes, and `gzip -t` on the dump exits 0.
- Remind the user to copy `~/netbird-backups/` off the host.

## Upgrades

Server first, then agents. An agent newer than its server is untested.

1. Back up (above).
2. Choose the target tags. After `git pull`, `netbird.example.yaml` holds the releases this repo is tested with; it has no secrets, so read its `images:` block and compare it with the current tags from `./deploy.py config`.
3. Never move Postgres to a new major version: a new major cannot start on the old data directory.
4. Change each tag in `netbird.yaml` with one targeted command (the example in [Secret files](../../../AGENTS.md#secret-files)), shown to the user first. Keep `netbird_server` and `dashboard` on the same NetBird release. Confirm with `./deploy.py config`.
5. Run `./deploy.py update`. It pulls, recreates only what changed and validates. Exit 0 is done; anything else goes to `netbird-troubleshoot`.
6. Then upgrade each agent to the server's new release, as in [Upgrade](../../../netbird-agent/README.md#upgrade) and [Match the server version](../../../netbird-agent/README.md#match-the-server-version).

## Restore

Follow the restore steps in [Backups](../../../netbird-server/README.md#backups). Ask before `docker compose down` and again before `docker volume rm`, which deletes the live database. The `netbird.yaml` in place must be the one saved with that dump, or at least hold the same `server.store_encryption_key`. Finish with `./deploy.py` and `./deploy.py validate`.

## Rotating secrets

Follow [Rotating secrets](../../../netbird-server/README.md#rotating-secrets). Ask before each rotation. The user types every new value into `netbird.yaml`, then you run `./deploy.py`.

- `server.store_encryption_key`: refuse. Changing it makes every encrypted column unreadable.
- `postgres.password`: the README's `ALTER USER` command must run first, because Postgres only reads the password on an empty data directory. The new password is in that command, so the user runs it, then updates `netbird.yaml`, then you run `./deploy.py`.
- `oidc.client_secret`: two places. `./deploy.py` updates Dex, and the user must paste the same value under *Settings → Identity Providers* in the dashboard, or login fails at token exchange.
- `github.client_secret`: the user generates a new one in the GitHub OAuth App, types it in, and you run `./deploy.py`.

## Agents: re-key and remove

- A rejected or expired setup key: the "Setup key rejected" row of the agent [Troubleshooting](../../../netbird-agent/README.md#troubleshooting) table. The user writes the new key with the hidden prompt.
- Removing an agent: [Uninstall](../../../netbird-agent/README.md#uninstall). Ask before `docker compose down -v`, which deletes the registration. The peer must also be deleted under **Peers** in the dashboard.
