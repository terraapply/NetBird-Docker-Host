# NetBird Docker Host

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

## Install methods

| Component | Method | Where |
|---|---|---|
| Server | Docker Compose on a VM | [`netbird-server/`](netbird-server/README.md) |
| Agent | Docker container | [`netbird-agent/`](netbird-agent/README.md#option-a-docker) |
| Agent | Native install on the VM | [`netbird-agent/`](netbird-agent/README.md#option-b-native) |

## Prerequisites

- TODO: supported VM operating systems
- TODO: domain name and DNS records for the server
- TODO: ports that must be open on the server VM
- TODO: minimum Docker and Docker Compose versions

## Quick start

1. Deploy the server on a VM: see [`netbird-server/README.md`](netbird-server/README.md).
2. Log in to the NetBird dashboard and create a setup key.
3. Install the agent on each VM that should join the network: see [`netbird-agent/README.md`](netbird-agent/README.md).

## License

[MIT](LICENSE)
