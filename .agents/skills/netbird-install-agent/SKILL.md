---
name: netbird-install-agent
description: Join a Linux VM to the self-hosted NetBird network as a peer, with Docker or the native package, a setup key read from a file, and the client matched to the server's release. Use when someone wants to install, add or connect a NetBird agent, client or peer on a VM.
---

# Install the NetBird agent

Before anything else, apply [Where am I?](../../../AGENTS.md#where-am-i) and [Secret files](../../../AGENTS.md#secret-files) from `AGENTS.md`. This skill often runs from a laptop or the server's clone: a native agent VM has no clone of this repo, so hand the user commands for that VM unless they cloned the repo there.

The procedure is [Join agents](../../../README.md#join-agents) in the root README, with the [agent requirements](../../../README.md#agent-vms) first. Work through these steps in order; each one has a check that must pass before the next.

## 1. Pick one method

Ask: Docker or native? If the VM already runs Docker, Docker keeps the client managed like the other containers; otherwise native is simpler. The choice is the user's.

Then check nothing NetBird is already on the VM: `command -v netbird`, `systemctl is-active netbird`, and `docker ps --format '{{.Names}}'` looking for `netbird`. If anything turns up, stop. Use one method per VM: two clients fight over the same WireGuard interface. Offer to remove the other one first with [Uninstall](../../../netbird-agent/README.md#uninstall), after a yes.

## 2. Check the management URL

It is the address the dashboard opens at, for example `https://netbird.example.com`. From the agent VM, `curl -I <management URL>` must get an HTTP answer. No answer means a wrong URL or `443/tcp` blocked on the way to the server; fix that before going on.

## 3. Find the server's release

Follow [Match the server version](../../../README.md#match-the-server-version) now, before installing, so you know which release the agent must run. On the server VM it is the `NETBIRD_SERVER_IMAGE` tag in `./deploy.py config`; anywhere else, ask the user.

## 4. Setup key

The user creates it in the dashboard as described in [Setup keys](../../../README.md#setup-keys): one-off for a single VM, reusable for several (revoked once they have joined), short expiry either way.

The key never passes through you. The user runs the README's hidden-prompt command on the VM and types the key there. Never put it on a command line, in an environment variable or in `.env`. If the user pastes a key into the chat, tell them to revoke it in the dashboard and create a new one.

## 5. Install

Follow [Option A: Docker](../../../README.md#option-a-docker) or [Option B: Native](../../../README.md#option-b-native) exactly.

- Docker: `netbird-agent/docker/.env` holds only `NB_MANAGEMENT_URL` and the optional `NB_HOSTNAME`, so you may write it. Keep `setup-key` in place afterwards; Compose mounts it on every start.
- Native: the installer fetches the latest client. If that is newer than the server, pin it with the commands in [Match the server version](../../../README.md#match-the-server-version). The README shreds the key file once `netbird up` succeeds.

## 6. Verify

Run [Verify](../../../README.md#verify). Done means all three:

- `Management: Connected` and `Signal: Connected`
- the VM listed under **Peers** in the dashboard
- a ping to another peer's NetBird IP answers

Anything else goes to the `netbird-troubleshoot` skill. Finally remind the user to revoke a reusable setup key once every VM has joined.
