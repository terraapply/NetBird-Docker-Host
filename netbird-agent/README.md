# netbird-agent

Joins a Linux VM to the NetBird network run by [`../netbird-server`](../netbird-server/README.md), as a peer.

There are two install methods: [Docker](#option-a-docker) or the [native package](#option-b-native). Use **one method per VM**: two NetBird clients on one VM fight over the same WireGuard interface.

Both methods end the same way: `netbird status` shows Management and Signal connected, and the VM appears in the dashboard under **Peers**.

## Requirements

- Ubuntu 22.04/24.04 or Debian 12.
- Outbound `443/tcp` and `3478/udp` to the NetBird server. No inbound ports: peers find each other through NAT, and traffic falls back to the relay on the server when a direct path is blocked.
- The management URL: the address you open the dashboard at, for example `https://netbird.example.com`.
- A setup key, see [Setup keys](#setup-keys).
- Option A: Docker Engine with the Compose v2 plugin, and `git`.
- Option B: `sudo` and `curl`.

## Setup keys

Create one in the dashboard under **Setup Keys**:

- **One-off**: registers a single peer, then it is spent. Use it for one VM.
- **Reusable**: registers any number of peers until it expires. Revoke it in the dashboard once your VMs have joined.

Give it a short expiry either way. A setup key is a secret: anyone holding a valid one can join your network.

Both methods read the key from a file only you can read, never from the command line, so it does not end up in shell history, `ps` output or `docker inspect`. This writes the file from a hidden prompt (bash):

```bash
install -m 600 /dev/null setup-key && read -rsp 'Setup key: ' key && printf '%s' "$key" > setup-key && unset key && echo
```

Paste the key at the prompt; nothing is echoed.

## Option A: Docker

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

## Option B: Native

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

## Match the server version

Run the same NetBird release on the agents as on the server. An agent newer than its server is untested, and both install methods can end up newer: the native installer takes the latest release, and `git pull` moves the Docker pin to the release this repository tests.

Find the server's release on the server VM, from `netbird-server`:

```bash
./deploy.py config | grep NETBIRD_SERVER_IMAGE   # the tag after the colon, for example 0.77.0
```

If you do not run the server, ask whoever does.

Docker: compare it with the `image:` line in `docker/docker-compose.yml`. If the agent's pin is newer, [upgrade the server](../netbird-server/README.md#upgrades) to that release first.

Native: install the server's release and hold it, so a routine `apt upgrade` does not move it past the server:

```bash
sudo apt-get install --allow-downgrades netbird=0.77.0   # the server's release
sudo apt-mark hold netbird
netbird version
```

`apt-cache madison netbird` lists every release in the repository. The package restarts the service itself, and the registration survives the change.

## Verify

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

## Upgrade

Upgrade the server first, then the agents. An agent newer than its server is untested.

Docker: the image is pinned in `docker-compose.yml` to the same NetBird release as the server in [`../netbird-server`](../netbird-server/README.md), and the two move together in this repository, so pull the repository first:

```bash
git pull
docker compose pull
docker compose up -d
```

Native, to the server's new release (see [Match the server version](#match-the-server-version)):

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
| `docker compose up` fails with `bind source path does not exist: .../setup-key` | The `setup-key` file is missing. Write it with the hidden prompt, then `docker compose up -d`. |
| Setup key rejected in the logs | The key expired, was revoked, or is a one-off key already spent on another peer. Create a new key. Docker: write `setup-key` again with the hidden prompt, then `docker compose up -d --force-recreate`. Native: run the last three commands of [Option B](#option-b-native) again. |
| Container exits at once or keeps restarting | Read `docker compose logs netbird`. Check that `setup-key` exists and is not empty, and that the VM has `/dev/net/tun`. |
