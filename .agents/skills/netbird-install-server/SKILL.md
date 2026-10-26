---
name: netbird-install-server
description: Install the self-hosted NetBird server from this repo on a fresh Linux VM, from DNS, ports and the GitHub OAuth App to netbird.yaml, ./deploy.py and the first login. Use when someone wants to set up, deploy or bootstrap the NetBird server, control plane or dashboard.
---

# Install the NetBird server

Before anything else, apply [Where am I?](../../../AGENTS.md#where-am-i) and [Secret files](../../../AGENTS.md#secret-files) from `AGENTS.md`. On a laptop, every command below goes to the user as a short block, and you read what they paste back.

The procedure is [Deploy the server](../../../README.md#deploy-the-server) in the root README, with its [Requirements](../../../README.md#requirements) first. Follow it in order and link the user to each section. Do not move on until the evidence for the current step is in; "done" from the user is not evidence.

| Step | README section | Evidence before moving on |
|---|---|---|
| 1. VM | [Server VM](../../../README.md#server-vm) | `docker compose version` prints v2.x, `python3 -c 'import yaml'` exits 0, `free -m` shows at least 1.5 GB (with swap below 4 GB) |
| 2. Ports | [Inbound ports](../../../README.md#inbound-ports) | `sudo ufw status` lists 80/tcp, 443/tcp and 3478/udp, or reports `inactive` (common on cloud VMs, where the security group is the firewall); the user confirms the cloud security group or router, which you cannot see |
| 3. DNS | [DNS](../../../README.md#dns) | `dig +short` for both names returns the VM's public IP. Any other address means a proxied record or a typo. |
| 4. GitHub OAuth App | [GitHub OAuth App](../../../README.md#github-oauth-app) | Created under the organisation, callback exactly `https://<dex domain>/callback`, user holds the client ID and secret. Ask whether the org restricts OAuth Apps; if so an owner must approve it. |
| 5. `netbird.yaml` | [Fill in netbird.yaml](../../../README.md#fill-in-netbirdyaml) | See below |
| 6. Run | [Run it](../../../README.md#run-it) | `./deploy.py` exits 0. A `warn` on `stun` with a hint about NAT hairpinning still exits 0: the router cannot loop back, external clients are fine. |
| 7. First login | [After the first run](../../../README.md#after-the-first-run), [Prove it works](../../../README.md#prove-it-works) | The user confirms each of the three setup steps and the four manual checks, including that a non-member is refused |

## Filling in netbird.yaml without opening it

`netbird.example.yaml` holds no secrets, so you may read it to learn the keys. Once copied to `netbird.yaml`, the rules in [Secret files](../../../AGENTS.md#secret-files) apply.

1. Clone, copy and `chmod 600` as the README shows.
2. Set the non-secret keys with one targeted command each, shown to the user first: `domains.netbird`, `domains.dex`, `acme.email`, `github.org`, `github.client_id`. Anchor each `sed` on the example's current value so it can only hit one line (`client_id` appears twice), for example:

   ```bash
   sed -i 's|^\(  client_id: \)Ov23li_replace_me$|\1<client id>|' netbird.yaml
   ```

3. The secrets are the user's to type, in their own editor and quoted: `github.client_secret` from GitHub, plus the five the README generates (`postgres.password`, `oidc.client_secret`, `server.relay_auth_secret`, `server.session_cookie_key`, `server.store_encryption_key`). Point them at the generator commands in the README; `server.store_encryption_key` is `openssl rand -base64 32` and keeps its trailing `=`.
4. Before the first run, tell the user to copy `server.store_encryption_key` somewhere off this host. It cannot be changed later, and a backup is unreadable without it.
5. Check without reading the file:
   - `./deploy.py config` shows the right domains, email, org and client ID, with every secret as `<redacted>`.
   - `grep -c replace_me netbird.yaml` prints `0`.
   - `./deploy.py` itself stops with exit 2 and touches nothing if a secret is still empty or `replace_me`; its message names the key.

## Running deploy.py

`./deploy.py` renders the config, starts the stack and runs its checks. The exit code says how far it got:

| Exit | Meaning | Next |
|---|---|---|
| 0 | Running and every check passed | Step 7 |
| 2 | Bad config, nothing was touched | Fix the key it names, run again |
| 3 | Failed to start | Use `netbird-troubleshoot` |
| 4 | Running, but a check failed | Use `netbird-troubleshoot` |

The first run waits 30 to 60 seconds for certificates. If `tls` or either issuer check fails, stop: nothing after them works. After the stack is up, `./deploy.py validate` re-runs the checks at any time without changing anything.

## After the first run

Step 2 of [After the first run](../../../README.md#after-the-first-run) needs `oidc.client_secret` in the dashboard. The user copies it from `netbird.yaml` themselves; do not read it for them.

When all seven steps have their evidence, the server is done. To join VMs as peers, switch to the `netbird-install-agent` skill.
