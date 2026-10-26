---
name: netbird-troubleshoot
description: Find and fix problems with the NetBird server or an agent VM from this repo, starting from deploy.py checks and logs, without exposing secrets. Use when NetBird, deploy.py, login, GitHub SSO, certificates, the dashboard or a peer connection is broken, failing or behaving strangely.
---

# Troubleshoot NetBird

Before anything else, apply [Where am I?](../../../AGENTS.md#where-am-i), [Secret files](../../../AGENTS.md#secret-files) and [Confirm or refuse](../../../AGENTS.md#confirm-or-refuse) from `AGENTS.md`.

Collect evidence before proposing a fix. Read each output in full, and never guess past a missing one. On a laptop, ask for one block at a time.

## 1. Evidence: server

From `netbird-server/` on the server VM, in this order:

1. `./deploy.py validate`. Exit 0 is healthy, 2 is bad config (nothing touched), 4 is a failed check. Every failed check prints its own fix: try that first, unless it means opening a generated file. For example, the `stun` hint points at `stunPorts` in `config.yaml`; read it in `template/config.yaml.tmpl` instead, which holds no secrets.
2. `./deploy.py validate --only <check>` re-runs one check. The report prints ids with dashes (`oidc-netbird`); `--only` takes the underscore form (`oidc_netbird`).
3. `./deploy.py status` and `docker compose ps`: which containers run, restart or exited.
4. `docker compose logs --tail=100 <service>` for the service the failure points at: `traefik`, `netbird-server`, `dashboard`, `dex` or `postgres`.

A check marked skipped because another one failed is not a separate problem: fix the one it names first. `services` comes before everything, and `tls` before every HTTPS check.

| Check | Function in `deploy.py` | What it proves | Look at first |
|---|---|---|---|
| `services` | `check_services` | All five containers run the configured images, no OOM kill | `docker compose ps`, logs of the stopped one |
| `postgres` | `check_postgres` | Postgres is ready and all three databases exist | `postgres` logs |
| `tls` | `check_tls` | Both hostnames serve a real certificate, not Traefik's self-signed one | `traefik` logs, DNS-only records, ports 80/443 |
| `oidc_netbird` | `check_oidc_netbird` | The embedded IdP's discovery document answers | `netbird-server` logs |
| `oidc_dex` | `check_oidc_dex` | Dex's discovery document answers | `dex` logs |
| `api_401` | `check_api_401` | `/api/users` demands a token | `netbird-server` logs, Traefik router priorities |
| `dex_redirect_uri` | `check_dex_redirect_uri` | Dex accepts the registered redirect URI | `dex` logs, `oidc.redirect_uri` |
| `dex_client_secret` | `check_dex_client_secret` | The static client secret matches | `dex` logs, a stale Dex config |
| `stun` | `check_stun` | A real STUN binding on 3478/udp | firewall and cloud rules for 3478/udp |

When a fix is not obvious, read that function in [deploy.py](../../../netbird-server/deploy.py) to see exactly what it tests and what its hints mean.

## 2. Evidence: agent VM

- Docker, from `netbird-agent/docker/`: `docker compose ps`, `docker compose logs --tail=100 netbird`, `docker compose exec netbird netbird status -d`, and `test -s setup-key && echo present`.
- Native: `netbird status -d`, `systemctl status netbird`, `sudo tail -n 100 /var/log/netbird/client.log`.
- Both: `curl -I <management URL>` must answer, `ls -l /dev/net/tun` must exist, and `netbird version` must not be newer than the server (see [Match the server version](../../../netbird-agent/README.md#match-the-server-version)).

## 3. Match known problems

Compare the evidence with the [server table](../../../netbird-server/README.md#troubleshooting) and the [agent table](../../../netbird-agent/README.md#troubleshooting). Most problems are there with their fix. Apply it, ask first where [Confirm or refuse](../../../AGENTS.md#confirm-or-refuse) says so, then re-run the evidence step that failed.

## 4. Generated files, without opening them

Never open `config.yaml`, `dex/config.yaml` or `.env` to diagnose. Use metadata and the redacted views instead. For example, "Dex starts then exits":

- `docker compose logs dex` for the parse or permission error
- `stat -c '%a %n' dex dex/config.yaml`, expecting `700 dex` and `644 dex/config.yaml`
- `./deploy.py config` to check a suspected wrong value, then fix it in `netbird.yaml` and run `./deploy.py`

A config change that "does nothing" usually means someone edited a generated file. Run `./deploy.py` to re-render from `netbird.yaml`.

## 5. Before you quote output

Logs can carry secrets by accident: database connection strings, client secrets, tokens in URLs. Check any output before repeating it, and replace such values with `<redacted>`.

## 6. A bug in this repo

If the setup is right and the repo is wrong (a traceback from `deploy.py`, a README fix that does not work, a check that fails on a healthy stack), draft an issue matching `.github/ISSUE_TEMPLATE/bug_report.yml`: component, what happened, `./deploy.py validate` output, `./deploy.py config` output, OS and version. Remind the user that both outputs contain their domains and email, and to replace them if they prefer before posting.

## 7. Learning loop

Once it works, if the problem was not in either table, make the offer in [Learning loop](../../../AGENTS.md#learning-loop): one new row with symptom, cause and fix.
