# NetBird Docker Host

[![CI](https://img.shields.io/github/actions/workflow/status/terraapply/NetBird-Docker-Host/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/terraapply/NetBird-Docker-Host/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/terraapply/NetBird-Docker-Host?style=flat-square)](https://github.com/terraapply/NetBird-Docker-Host/releases)
[![License: MIT](https://img.shields.io/github/license/terraapply/NetBird-Docker-Host?style=flat-square)](LICENSE)
<br>
[![NetBird 0.77.0](https://img.shields.io/badge/NetBird-0.77.0-blue?style=flat-square)](netbird-server/netbird.example.yaml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python&logoColor=white)](CONTRIBUTING.md#setup)
[![Docker Compose v2](https://img.shields.io/badge/docker_compose-v2-blue?style=flat-square&logo=docker&logoColor=white)](https://docs.docker.com/compose/)
<br>
[![Renovate enabled](https://img.shields.io/badge/renovate-enabled-brightgreen?style=flat-square&logo=renovatebot)](renovate.json)
[![pre-commit enabled](https://img.shields.io/badge/pre--commit-enabled-brightgreen?style=flat-square&logo=pre-commit)](.pre-commit-config.yaml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&style=flat-square)](https://github.com/astral-sh/ruff)
[![AI agents: AGENTS.md](https://img.shields.io/badge/AI_agents-AGENTS.md-blueviolet?style=flat-square)](AGENTS.md)

Self-hosted [NetBird](https://netbird.io) setup for virtual machines.

NetBird is a WireGuard-based overlay network. This repository holds everything needed to run your own NetBird control plane on one VM and connect other VMs to it as peers.

## Repository layout

| Path | Purpose |
|---|---|
| [`netbird-server/`](netbird-server/README.md) | Self-hosted NetBird server on a VM, running in Docker |
| [`netbird-agent/`](netbird-agent/README.md) | Standalone NetBird agent for a VM, installed with Docker or natively |

## Architecture

```
            +---------------------------+
            |  Server VM                |
            |  netbird-server (Docker)  |
            +-------------+-------------+
                          |
          +---------------+---------------+
          |                               |
+---------+---------+           +---------+---------+
|  Agent VM         |           |  Agent VM         |
|  netbird-agent    |  <------> |  netbird-agent    |
|  (Docker/native)  |    P2P    |  (Docker/native)  |
+-------------------+           +-------------------+
```

The server VM hosts the NetBird control plane. Agent VMs register with the server using a setup key and then talk to each other directly over WireGuard where possible.

The server VM runs five containers: `traefik` (TLS and routing), `netbird-server` (management, signal, relay and STUN), `dashboard`, `dex` and `postgres`. Login is limited to members of one GitHub organisation through Dex, and a local break-glass login stays on by default so a GitHub problem cannot lock you out.

## Install methods

| Component | Method | Where |
|---|---|---|
| Server | Docker Compose on a VM | [`netbird-server/`](netbird-server/README.md) |
| Agent | Docker container | [`netbird-agent/`](netbird-agent/README.md#option-a-docker) |
| Agent | Native install on the VM | [`netbird-agent/`](netbird-agent/README.md#option-b-native) |

## Prerequisites

Server VM:

- Ubuntu 22.04/24.04 or Debian 12. 2 vCPU / 4 GB RAM recommended; 1 vCPU / 1.5 GB works with some swap. See [VM](netbird-server/README.md#vm).
- Docker Engine with the Compose v2 plugin, `git` and `python3-yaml`.
- Two DNS-only A records pointing at the VM, for example `netbird.<domain>` and `dex.netbird.<domain>`. See [DNS](netbird-server/README.md#dns).
- Inbound `80/tcp`, `443/tcp` and `3478/udp`. See [Inbound ports](netbird-server/README.md#inbound-ports).
- A GitHub organisation where you can create an OAuth App. See [GitHub OAuth App](netbird-server/README.md#github-oauth-app).

## Quick start

1. Deploy the server on a VM: see [`netbird-server/README.md`](netbird-server/README.md).
2. Log in to the NetBird dashboard and create a setup key: see [Setup keys](netbird-agent/README.md#setup-keys).
3. Install the agent on each VM that should join the network: see [`netbird-agent/README.md`](netbird-agent/README.md).

## Using an AI agent

This repository ships instructions for coding agents. [`AGENTS.md`](AGENTS.md) holds the rules every agent loads, and five skills cover the common jobs. They work in Claude Code, OpenCode, Codex and any other agent that reads `AGENTS.md`.

| Skill | Use it to |
|---|---|
| [netbird-install-server](.agents/skills/netbird-install-server/SKILL.md) | Set up the server on a new VM, up to the first login |
| [netbird-install-agent](.agents/skills/netbird-install-agent/SKILL.md) | Join a VM to the network, with Docker or natively |
| [netbird-maintain](.agents/skills/netbird-maintain/SKILL.md) | Back up, restore, upgrade, rotate secrets, re-key or remove agents |
| [netbird-troubleshoot](.agents/skills/netbird-troubleshoot/SKILL.md) | Find and fix a problem on the server or an agent VM |
| [netbird-extend](.agents/skills/netbird-extend/SKILL.md) | Add or change a feature, in the repository or in one deployment |

Start your agent inside a clone of this repository, on a laptop or on a VM. A VM with the native agent install has no clone; drive it from a clone elsewhere, where the agent hands you the commands to run, or clone the repository there.

Agents are told never to open `netbird.yaml`, the generated configs, setup keys or backups, because whatever an agent reads is sent to its AI provider. Do not paste secrets into the chat either.

## License

[MIT](LICENSE)
