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

## Requirements

### Server VM

Linux with Docker Engine and the Compose v2 plugin. Ubuntu 22.04/24.04 or
Debian 12 assumed below.

2 vCPU / 4 GB RAM is comfortable. It does run on 1 vCPU / 1.5 GB (that is what
the reference deployment uses), but with little headroom, so keep some swap and
expect first boot to be slow while Let's Encrypt and the database migrations run.

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # log out and back in
docker compose version            # must print v2.x
sudo apt-get install -y git jq curl python3-yaml
```

`git` fetches this repository and `python3-yaml` is what `deploy.py` needs;
nothing else is installed on the host.

### Inbound ports

| Port | Proto | Why |
|---|---|---|
| 80 | TCP | HTTP → HTTPS redirect; ACME fallback |
| 443 | TCP | Dashboard, REST API, gRPC (management + signal), relay, Dex |
| 3478 | UDP | Embedded STUN: **cannot** be proxied, must reach the host directly |

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 3478/udp
```

Behind a cloud security group or home router, forward the same three.

### DNS

Two A records pointing at the VM's public IP. If your DNS provider offers a
reverse proxy (Cloudflare's orange cloud, for example) it must be **off** for
both: a proxy breaks the long-lived gRPC streams that management and signal
depend on, and carries no UDP at all for STUN.

| Type | Name | Content | Proxy |
|---|---|---|---|
| A | `netbird` | `<VM public IP>` | off / DNS only |
| A | `dex.netbird` | `<VM public IP>` | off / DNS only |

Substitute your own domain for `example.com` throughout this guide, and set the
same two names in `netbird.yaml` under `domains:`.

Check before continuing, Let's Encrypt fails otherwise:

```bash
dig +short netbird.example.com
dig +short dex.netbird.example.com
```

### GitHub OAuth App

Create it **inside the organisation**, not on a personal account:

`https://github.com/organizations/<your-org>/settings/applications/new`

| Field | Value |
|---|---|
| Application name | `NetBird VPN` |
| Homepage URL | `https://netbird.example.com` |
| Authorization callback URL | `https://dex.netbird.example.com/callback` |

Register, then **Generate a new client secret** and copy both values. The
secret is shown once.

> **If your org enforces OAuth App access restrictions**, an owner must approve
> the app under *Settings → Third-party Access → OAuth App policy*. Without it
> every login fails with an unhelpful error and Dex logs `403 Forbidden` reading
> org membership. This is the most common cause of "GitHub SSO doesn't work".

Dex requests `read:user`, `user:email` and `read:org` itself; nothing to set.

### Agent VMs

- Ubuntu 22.04/24.04 or Debian 12.
- Outbound `443/tcp` and `3478/udp` to the NetBird server. No inbound ports: peers find each other through NAT, and traffic falls back to the relay on the server when a direct path is blocked.
- The management URL: the address you open the dashboard at, for example `https://netbird.example.com`.
- A setup key, see [Setup keys](#setup-keys).
- Option A: Docker Engine with the Compose v2 plugin, and `git`.
- Option B: `sudo` and `curl`.

## Deploy the server

Six steps, starting with the [requirements](#requirements) above. Budget about 30 minutes, most of it waiting for DNS.

| # | Step | Where |
|---|---|---|
| 1 | Point two DNS records at the VM | [DNS](#dns) |
| 2 | Open ports 80, 443 and 3478/udp | [Ports](#inbound-ports) |
| 3 | Create a GitHub OAuth App in your org | [GitHub OAuth App](#github-oauth-app) |
| 4 | Fill in `netbird.yaml` | [Fill in netbird.yaml](#fill-in-netbirdyaml) |
| 5 | Run `./deploy.py` | [Run it](#run-it) |
| 6 | Create the admin, connect GitHub | [After the first run](#after-the-first-run) |

### Fill in netbird.yaml

Clone the repository on the VM, then:

```bash
git clone https://github.com/terraapply/NetBird-Docker-Host.git
cd NetBird-Docker-Host/netbird-server
cp netbird.example.yaml netbird.yaml
chmod 600 netbird.yaml
```

Generate the five secrets:

```bash
openssl rand -hex 32                                # postgres.password
openssl rand -hex 32                                # oidc.client_secret
openssl rand -base64 32 | tr -d '=' | tr '/+' '_-'  # server.relay_auth_secret
openssl rand -base64 32                             # server.session_cookie_key
openssl rand -base64 32                             # server.store_encryption_key  (keep the '=')
```

Open `netbird.yaml` and fill in the two hostnames, `acme.email`, the `github:`
block and those five secrets. Every field has its command in a comment beside it.

**Quote every secret.** Unquoted, an all-digit value becomes a number and `no`
becomes a boolean. `deploy.py` catches both, but quoting saves the round trip.

> ### Back up `server.store_encryption_key` now
>
> It encrypts user emails and names in the database. Without it a restored
> backup is unreadable, and it **cannot be changed later** without destroying
> the existing data. Keep a copy somewhere other than this host.
>
> It must also keep its trailing `=` padding: Go decodes it with
> `base64.StdEncoding`, which rejects unpadded input. `deploy.py` refuses to run
> if you strip it.

### Run it

```bash
./deploy.py
```

Traefik requests two certificates over TLS-ALPN-01, which takes 30 to 60 seconds on
a first run. `deploy.py` waits, then reports:

```
netbird.example.com: provision

[ok  ] services           5/5 running, images match
[ok  ] postgres           ready, 3/3 databases present
[ok  ] tls                both hosts, issued certificates
[ok  ] oidc-netbird       issuer https://netbird.example.com/oauth2
[ok  ] oidc-dex           issuer https://dex.netbird.example.com
[ok  ] api-401            /api/users -> 401
[ok  ] dex-redirect-uri   accepted, handed off to github.com
[ok  ] dex-client-secret  accepted (invalid_grant)
[ok  ] stun               binding response, reflexive 203.0.113.10:41234
```

Anything but `ok` prints the cause and the command that fixes it. If TLS or
either issuer fails, stop and fix it; nothing downstream works without them.

### After the first run

`deploy.py` prints these three steps; they cannot be automated safely.

**1. Create the break-glass admin.** Open `https://netbird.example.com`; you are
redirected to `/setup`. Set an email, a name and a strong password, and store the
password in your password manager: this is the way back in if GitHub SSO breaks.
`/setup` stops responding once an owner exists.

**2. Add Dex as an identity provider.** *Settings → Identity Providers → Add*:

| Field | Value |
|---|---|
| Type | `Generic OIDC` |
| Name | `GitHub` (this becomes the login button label) |
| Client ID | `netbird` |
| Client Secret | `oidc.client_secret` from `netbird.yaml` |
| Issuer | `https://dex.netbird.example.com` |

The dashboard may show a Redirect URL ending in a connector ID. Ignore it:
netbird-server sends a plain `/oauth2/callback`, which is already registered.

**3. Approve your GitHub user.** The first person through the GitHub button
arrives *pending approval*; an owner approves them under *Settings → Users*. Log
in as the break-glass admin to do it. Only members of your org get this far.

Optionally register the post-logout URL
`https://netbird.example.com/oauth2/logout/callback` so logout returns cleanly.

### Prove it works

`./deploy.py validate` covers the machine-checkable parts. These four are on you:

1. **GitHub login works.** Log out, click **GitHub**, land back in the dashboard.
2. **A non-member is refused.** Have someone outside the org try it. *Do not skip
   this*: without it you have verified that OAuth works, not that access control
   does.
3. **Break-glass still works.** Log out, log in with the local admin.
4. **A peer connects:**

   ```bash
   curl -fsSL https://pkgs.netbird.io/install.sh | sh
   sudo netbird up --management-url https://netbird.example.com
   netbird status        # Management: Connected / Signal: Connected
   ```

   The peer appears under **Peers**. To join VMs for real, with Docker or the
   native package and a setup key, see [Join agents](#join-agents).

## Join agents

Each VM that joins the network runs the NetBird client and registers with the server as a peer. There are two install methods: [Docker](#option-a-docker) or the [native package](#option-b-native). Use **one method per VM**: two NetBird clients on one VM fight over the same WireGuard interface.

Both methods end the same way: `netbird status` shows Management and Signal connected, and the VM appears in the dashboard under **Peers**. Check the [agent requirements](#agent-vms) first.

### Setup keys

Create one in the dashboard under **Setup Keys**:

- **One-off**: registers a single peer, then it is spent. Use it for one VM.
- **Reusable**: registers any number of peers until it expires. Revoke it in the dashboard once your VMs have joined.

Give it a short expiry either way. A setup key is a secret: anyone holding a valid one can join your network.

Both methods read the key from a file only you can read, never from the command line, so it does not end up in shell history, `ps` output or `docker inspect`. This writes the file from a hidden prompt (bash):

```bash
install -m 600 /dev/null setup-key && read -rsp 'Setup key: ' key && printf '%s' "$key" > setup-key && unset key && echo
```

Paste the key at the prompt; nothing is echoed.

### Option A: Docker

Runs the official `netbirdio/netbird` client image with host networking, so the WireGuard interface lives on the VM and other peers reach the VM itself, not only the container.

```bash
git clone https://github.com/terraapply/NetBird-Docker-Host.git
cd NetBird-Docker-Host/netbird-agent/docker
cp .env.example .env
chmod 600 .env
nano .env                  # set NB_MANAGEMENT_URL, optionally NB_HOSTNAME
```

Write `setup-key` next to `docker-compose.yml` with the hidden prompt:

```bash
install -m 600 /dev/null setup-key && read -rsp 'Setup key: ' key && printf '%s' "$key" > setup-key && unset key && echo
```

Start it and watch it register:

```bash
docker compose up -d
docker compose logs -f     # Ctrl+C to stop following
```

Keep `setup-key` in place. Compose mounts it on every start and fails without it. A spent one-off key does no harm there: the registration lives in the `state` volume, so restarts and reboots reconnect without a new key.

`.env` and `setup-key` are gitignored.

### Option B: Native

Installs the NetBird package and its system service with the official installer, then registers with the key file:

```bash
curl -fsSL https://pkgs.netbird.io/install.sh | sh
install -m 600 /dev/null ~/netbird-setup-key && read -rsp 'Setup key: ' key && printf '%s' "$key" > ~/netbird-setup-key && unset key && echo
sudo netbird up --management-url https://netbird.example.com --setup-key-file ~/netbird-setup-key
shred -u ~/netbird-setup-key
```

Replace `https://netbird.example.com` with your management URL. Add `--hostname <name>` to the `netbird up` line to choose the peer name; the default is the VM hostname.

The key file can go once `netbird up` succeeds: the registration is stored under `/var/lib/netbird`, and the service reconnects on its own after a reboot.

The installer always fetches the latest client. If your server runs an older release, pin it next: see [Match the server version](#match-the-server-version).

### Match the server version

Run the same NetBird release on the agents as on the server. An agent newer than its server is untested, and both install methods can end up newer: the native installer takes the latest release, and `git pull` moves the Docker pin to the release this repository tests.

Find the server's release on the server VM, from `netbird-server/`:

```bash
./deploy.py config | grep NETBIRD_SERVER_IMAGE   # the tag after the colon, for example 0.77.0
```

If you do not run the server, ask whoever does.

Docker: compare it with the `image:` line in `netbird-agent/docker/docker-compose.yml`. If the agent's pin is newer, [upgrade the server](netbird-server/README.md#upgrades) to that release first.

Native: install the server's release and hold it, so a routine `apt upgrade` does not move it past the server:

```bash
sudo apt-get install --allow-downgrades netbird=0.77.0   # the server's release
sudo apt-mark hold netbird
netbird version
```

`apt-cache madison netbird` lists every release in the repository. The package restarts the service itself, and the registration survives the change.

### Verify

Docker, from `netbird-agent/docker`:

```bash
docker compose exec netbird netbird status
```

Native:

```bash
netbird status
```

Expect `Management: Connected` and `Signal: Connected`. Then:

- The VM appears in the dashboard under **Peers**.
- Another peer answers a ping on its NetBird IP (`netbird status` prints this VM's own `NetBird IP`; the dashboard lists the others).

## Operate

Run these from `netbird-server/` on the server VM.

### Everyday commands

```bash
./deploy.py              # render, start, validate  (safe to re-run any time)
./deploy.py validate     # check a running stack, change nothing
./deploy.py status       # what is running, and whether setup is finished
./deploy.py update       # pull new image tags from netbird.yaml, recreate
./deploy.py config       # show the resolved config, secrets hidden
```

Plain `docker compose` works too: `deploy.py` generates the `.env` it needs:

```bash
docker compose ps
docker compose logs -f dex
```

### Exit codes

**Exit codes** tell you how far it got: `0` fine · `2` bad config, *nothing was
touched* · `3` failed to start · `4` running but a check failed.

### Common tasks

| I want to… | Do this |
|---|---|
| Change a hostname, secret or setting | Edit `netbird.yaml`, run `./deploy.py` |
| Turn local email/password login on or off | Set `server.local_auth` in `netbird.yaml`, run `./deploy.py` |
| Upgrade NetBird, Dex or Traefik | Bump the tag under `images:`, run `./deploy.py update` |
| See why something is broken | `./deploy.py validate`; each failure prints its fix |
| Read logs | `docker compose logs -f netbird-server` |
| Back up | [Backups](netbird-server/README.md#backups) |
| Rotate a secret | [Rotating secrets](netbird-server/README.md#rotating-secrets) |
| Troubleshoot the server | [Troubleshooting](netbird-server/README.md#troubleshooting) |
| Upgrade or remove an agent | [Upgrade](netbird-agent/README.md#upgrade), [Uninstall](netbird-agent/README.md#uninstall) |

> **Never edit `config.yaml`, `dex/config.yaml` or `.env`.** They are generated
> and overwritten on every run. Edit `netbird.yaml` instead.

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
