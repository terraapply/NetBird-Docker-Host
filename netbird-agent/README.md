<div align="center">

# netbird-agent

**Reference for the NetBird client on agent VMs in [NetBird Docker Host](../README.md): upgrade, uninstall, troubleshooting.**

[![CI](https://img.shields.io/github/actions/workflow/status/terraapply/NetBird-Docker-Host/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/terraapply/NetBird-Docker-Host/actions/workflows/ci.yml)
[![AI agents: AGENTS.md](https://img.shields.io/badge/AI_agents-AGENTS.md-blueviolet?style=flat-square)](../AGENTS.md)

[Install guide](../README.md#join-agents) · [Upgrade](#upgrade) · [Uninstall](#uninstall) · [Troubleshooting](#troubleshooting)

</div>

The NetBird client joins a Linux VM to the network as a peer, with Docker (`docker/`) or the native package. Requirements and both install methods are in the root README under [Join agents](../README.md#join-agents), including [setup keys](../README.md#setup-keys) and how to [match the server version](../README.md#match-the-server-version).

## Upgrade

Upgrade the server first, then the agents. An agent newer than its server is untested.

Docker, from `netbird-agent/docker`: the image is pinned in `docker/docker-compose.yml` to the same NetBird release as the server in [`../netbird-server`](../netbird-server/README.md), and the two move together in this repository, so pull the repository first:

```bash
git pull
docker compose pull
docker compose up -d
```

Native, to the server's new release (see [Match the server version](../README.md#match-the-server-version)):

```bash
sudo apt-get update
sudo apt-mark unhold netbird
sudo apt-get install netbird=0.78.0   # the server's new release
sudo apt-mark hold netbird
```

## Uninstall

Docker, from `netbird-agent/docker`:

```bash
docker compose down -v     # -v also deletes the state volume (the registration)
rm -f .env
shred -u setup-key
```

Native:

```bash
sudo netbird down
sudo netbird service stop
sudo netbird service uninstall
sudo apt-mark unhold netbird
sudo apt-get remove netbird
sudo rm -rf /var/lib/netbird
```

Both: delete the peer in the dashboard under **Peers**.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Management: Disconnected` or stuck connecting | Wrong management URL, or `443/tcp` to the server is blocked. From the VM run `curl -I https://netbird.example.com` with your URL; it must answer. Docker: check `NB_MANAGEMENT_URL` in `.env`, then `docker compose up -d`. |
| `docker compose up` fails with `bind source path does not exist: .../setup-key` | The `setup-key` file is missing. Write it with the [hidden prompt](../README.md#option-a-docker), then `docker compose up -d`. |
| Setup key rejected in the logs | The key expired, was revoked, or is a one-off key already spent on another peer. Create a new key. Docker: write `setup-key` again with the [hidden prompt](../README.md#option-a-docker), then `docker compose up -d --force-recreate`. Native: run the last three commands of [Option B](../README.md#option-b-native) again. |
| Container exits at once or keeps restarting | Read `docker compose logs netbird`. Check that `setup-key` exists and is not empty, and that the VM has `/dev/net/tun`. |
