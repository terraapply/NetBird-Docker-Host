# NetBird self-hosted control plane

A private VPN control plane on one Linux VM, where **logging in means being a
member of your GitHub organisation**. Everything is driven by a single config
file and a single command.

```bash
cp netbird.example.yaml netbird.yaml   # fill it in
./deploy.py                            # render, start, validate
```

`deploy.py` is the whole interface. It renders every config file, starts the
stack, waits for it to settle, and runs nine checks against the running system —
telling you what to fix when one fails.

---

## Quick start

Six steps. Budget about 30 minutes, most of it waiting for DNS.

| # | Step | Where |
|---|---|---|
| 1 | Point two DNS records at the VM | [DNS](#dns) |
| 2 | Open ports 80, 443 and 3478/udp | [Ports](#inbound-ports) |
| 3 | Create a GitHub OAuth App in your org | [GitHub OAuth App](#github-oauth-app) |
| 4 | Fill in `netbird.yaml` | [Fill in netbird.yaml](#fill-in-netbirdyaml) |
| 5 | Run `./deploy.py` | [Install](#install) |
| 6 | Create the admin, connect GitHub | [After the first run](#after-the-first-run) |

---

## Everyday commands

```bash
./deploy.py              # render, start, validate  (safe to re-run any time)
./deploy.py validate     # check a running stack, change nothing
./deploy.py status       # what is running, and whether setup is finished
./deploy.py update       # pull new image tags from netbird.yaml, recreate
./deploy.py config       # show the resolved config, secrets hidden
```

Plain `docker compose` works too — `deploy.py` generates the `.env` it needs:

```bash
docker compose ps
docker compose logs -f dex
```

**Exit codes** tell you how far it got: `0` fine · `2` bad config, *nothing was
touched* · `3` failed to start · `4` running but a check failed.

### Common tasks

| I want to… | Do this |
|---|---|
| Change a hostname, secret or setting | Edit `netbird.yaml`, run `./deploy.py` |
| Turn local email/password login on or off | Set `server.local_auth` in `netbird.yaml`, run `./deploy.py` |
| Upgrade NetBird, Dex or Traefik | Bump the tag under `images:`, run `./deploy.py update` |
| See why something is broken | `./deploy.py validate` — each failure prints its fix |
| Read logs | `docker compose logs -f netbird-server` |
| Back up | [Backups](#backups) |

> **Never edit `config.yaml`, `dex/config.yaml` or `.env`.** They are generated
> and overwritten on every run. Edit `netbird.yaml` instead.

---

## Before you start

### VM

Linux with Docker Engine and the Compose v2 plugin. Ubuntu 22.04/24.04 or
Debian 12 assumed below.

2 vCPU / 4 GB RAM is comfortable. It does run on 1 vCPU / 1.5 GB — that is what
the reference deployment uses — but with little headroom, so keep some swap and
expect first boot to be slow while Let's Encrypt and the database migrations run.

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # log out and back in
docker compose version            # must print v2.x
sudo apt-get install -y jq curl python3-yaml
```

`python3-yaml` is what `deploy.py` needs; there are no other dependencies.

### Inbound ports

| Port | Proto | Why |
|---|---|---|
| 80 | TCP | HTTP → HTTPS redirect; ACME fallback |
| 443 | TCP | Dashboard, REST API, gRPC (management + signal), relay, Dex |
| 3478 | UDP | Embedded STUN — **cannot** be proxied, must reach the host directly |

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

Check before continuing — Let's Encrypt fails otherwise:

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

Register, then **Generate a new client secret** and copy both values — the
secret is shown once.

> **If your org enforces OAuth App access restrictions**, an owner must approve
> the app under *Settings → Third-party Access → OAuth App policy*. Without it
> every login fails with an unhelpful error and Dex logs `403 Forbidden` reading
> org membership. This is the most common cause of "GitHub SSO doesn't work".

Dex requests `read:user`, `user:email` and `read:org` itself — nothing to set.

---

## Install

### Fill in netbird.yaml

Copy this directory to the VM (e.g. `/opt/netbird`), then:

```bash
cd /opt/netbird
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
> It must also keep its trailing `=` padding — Go decodes it with
> `base64.StdEncoding`, which rejects unpadded input. `deploy.py` refuses to run
> if you strip it.

### Run it

```bash
./deploy.py
```

Traefik requests two certificates over TLS-ALPN-01, which takes 30–60 seconds on
a first run. `deploy.py` waits, then reports:

```
netbird.example.com — provision

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
either issuer fails, stop and fix it — nothing downstream works without them.

### After the first run

`deploy.py` prints these three steps; they cannot be automated safely.

**1. Create the break-glass admin.** Open `https://netbird.example.com`; you are
redirected to `/setup`. Set an email, a name and a strong password, and store the
password in your password manager — this is the way back in if GitHub SSO breaks.
`/setup` stops responding once an owner exists.

**2. Add Dex as an identity provider.** *Settings → Identity Providers → Add*:

| Field | Value |
|---|---|
| Type | `Generic OIDC` |
| Name | `GitHub` — this becomes the login button label |
| Client ID | `netbird` |
| Client Secret | `oidc.client_secret` from `netbird.yaml` |
| Issuer | `https://dex.netbird.example.com` |

The dashboard may show a Redirect URL ending in a connector ID. Ignore it —
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
   this* — without it you have verified that OAuth works, not that access control
   does.
3. **Break-glass still works.** Log out, log in with the local admin.
4. **A peer connects:**

   ```bash
   curl -fsSL https://pkgs.netbird.io/install.sh | sh
   sudo netbird up --management-url https://netbird.example.com
   netbird status        # Management: Connected / Signal: Connected
   ```

   The peer appears under **Peers**.

---

## How it works

### Why there is a Dex container

**GitHub is not an OIDC provider.** It has no
`/.well-known/openid-configuration` and never issues an `id_token` — it speaks
plain OAuth2. NetBird only accepts OIDC providers, so GitHub cannot be plugged in
directly.

[Dex](https://dexidp.io/) sits in between. It has a GitHub connector with an
organisation allow-list on one side and speaks OIDC on the other:

```
netbird CLI / dashboard
      │
      ▼
NetBird embedded Dex          issuer: https://netbird.example.com/oauth2
  (inside netbird-server)     the dashboard's AUTH_AUTHORITY
      │  Generic OIDC connector, added via the dashboard UI
      ▼
Standalone Dex                issuer: https://dex.netbird.example.com
      │  GitHub connector, orgs: [ <your-org> ]
      ▼
GitHub OAuth App              org members only — everyone else stops here
```

The org check happens in Dex, before NetBird sees the user.

Local email/password login stays **enabled** by default (`server.local_auth:
true`) so a broken OAuth app, an expired secret or a GitHub outage cannot lock
you out of your own control plane. See
[Hardening](#hardening-and-extras) to turn it off.

### What runs

| Container | Role |
|---|---|
| `netbird-traefik` | TLS termination, Let's Encrypt, routing |
| `netbird-server` | management + signal + relay + STUN + embedded IdP |
| `netbird-dashboard` | web UI |
| `netbird-dex` | GitHub → OIDC broker |
| `netbird-postgres` | all three NetBird datastores |

Since v0.62 NetBird ships management, signal, relay and STUN as one binary — so
this is five containers, not the seven older guides describe.

### Configuration

**`netbird.yaml` is the single source of truth**, holding every setting *and*
every secret. It is gitignored. Everything else is generated:

```
netbird.yaml ──┬─ template/config.yaml.tmpl     ──> config.yaml      (0600)
               ├─ template/dex.config.yaml.tmpl ──> dex/config.yaml  (0644)
               └─────────────────────────────────> .env              (0600)
```

Rendering fails loudly on a placeholder with no value rather than writing a
literal `${FOO}` into a live config, and every output is checked for leftover
markers and parsed as YAML before anything starts.

Each generated file's content hash is published as a Compose label, so a service
whose config actually changed gets recreated and one whose config did not is left
alone. Without that, re-rendering would be a silent no-op: Docker binds a mounted
file by inode, and a running container keeps reading the old one.

`dex/config.yaml` is `0644`, not `0600`, deliberately — the Dex container runs as
UID 1001 and cannot read a `0600` file owned by you. The `dex/` directory is
`0700` instead, which protects it on the host just as well.

Note that secrets do end up in more than one file on disk. `netbird-server` does
no environment expansion in its config, which is why templates exist at all.
`netbird.yaml` is the single source for *authoring*, not for storage.

### Files

| File | Purpose |
|---|---|
| `netbird.example.yaml` | Committed template, every field documented |
| `netbird.yaml` | **Not committed.** Your config and secrets — the only file you edit |
| `deploy.py` | Renders configs, starts the stack, validates it |
| `docker-compose.yml` | The stack |
| `template/*.tmpl` | Templates for the server and Dex configs |
| `postgres/init-databases.sh` | Creates the two extra databases on first boot |
| `config.yaml`, `dex/config.yaml`, `.env` | **Generated** — never edit |

---

## Day-2 operations

### Backups

Two things matter: the database and `netbird.yaml`. Everything else is derived,
and the `netbird_data` volume now holds only re-downloadable geolocation data.

```bash
docker compose exec -T postgres pg_dumpall -U netbird \
  | gzip > netbird-db-$(date +%F).sql.gz

cp netbird.yaml netbird-conf-$(date +%F).yaml
```

Keep the two together: rows are encrypted with `server.store_encryption_key`, so
a dump without the config is unreadable.

`pg_dumpall` is deliberate — state spans `netbird` (peers, groups, policies,
setup keys), `netbird_events` (audit log) and `netbird_idp` (local users and IdP
connectors), and dumping them one by one invites forgetting one.

Restore into an empty instance:

```bash
docker compose down
docker volume rm netbird_netbird_pgdata
docker compose up -d postgres
gunzip -c netbird-db-YYYY-MM-DD.sql.gz \
  | docker compose exec -T postgres psql -U netbird -d postgres
./deploy.py
```

### Upgrades

Back up first, then bump the tags under `images:` in `netbird.yaml`:

```bash
./deploy.py update
```

That pulls, recreates only what changed, and re-validates. Latest tags:
[netbird-server](https://hub.docker.com/r/netbirdio/netbird-server/tags) ·
[dashboard](https://hub.docker.com/r/netbirdio/dashboard/tags) ·
[dex](https://github.com/dexidp/dex/releases).

### Rotating secrets

Edit `netbird.yaml` and run `./deploy.py`. Two exceptions:

- **`server.store_encryption_key` cannot be rotated** against an existing
  database. Changing it makes every encrypted column unreadable.
- **`postgres.password`** is only applied when the data directory is empty.
  Change it on a live instance with
  `docker compose exec -T postgres psql -U netbird -c "ALTER USER netbird PASSWORD '<new>'"`,
  then update `netbird.yaml` to match.

Rotating `oidc.client_secret` is a two-sided change: `deploy.py` updates Dex, but
you must also update the secret in *Settings → Identity Providers*, or login
fails at token exchange.

---

## Troubleshooting

Run `./deploy.py validate` first — most failures name their own fix.

| Symptom | Cause | Fix |
|---|---|---|
| Traefik never gets a certificate | Record is orange-clouded, or 80/443 blocked | Set both records to DNS only, open the ports, `docker compose logs traefik` |
| `Unregistered redirect_uri` after clicking GitHub | Dex's registered URI is not exactly what NetBird sends | `docker compose logs dex \| grep unregistered`, then set `oidc.redirect_uri` in `netbird.yaml` to that exact value |
| Real org member gets 403 / "not a member" | Org enforces OAuth App restrictions, app unapproved | An owner approves it under Third-party Access |
| Dex starts then exits | Bad config, or the file is unreadable to UID 1001 | `docker compose logs dex`; check `dex/` is `0700` and `dex/config.yaml` is `0644` |
| `netbird-server` crash-loops on boot | `store_encryption_key` is not padded base64 of 32 bytes | Regenerate with `openssl rand -base64 32`, keep the `=`, re-run |
| Peers connect then drop after minutes | A proxy is applying timeouts to the gRPC streams | The bundled Traefik sets responding timeouts to `0`; do the same on any proxy in front |
| Dashboard loads but the API returns 502 | Router priority collision on `/api` | Dashboard router stays `priority=1`, netbird-server routers `priority=100` |
| `netbird up` hangs at the device code | UDP 3478 or TCP 443 unreachable from the client | Check firewall and NAT; `./deploy.py validate --only stun` |
| A config change seems to do nothing | You edited a generated file | Edit `netbird.yaml` (or the template) and re-run `./deploy.py` |

```bash
docker compose logs -f netbird-server
docker compose logs -f dex
docker compose exec traefik traefik healthcheck
```

---

## Hardening and extras

**Disable local login once SSO is proven.** In `netbird.yaml`:

```yaml
server:
  local_auth: false
```

then `./deploy.py`. Note the flag is positive — `local_auth: false` renders
NetBird's `localAuthDisabled: true`.

Only do this after the checks above pass, and only if you accept that GitHub
becomes the single way in: a GitHub outage or an expired client secret locks out
everyone, including you. `deploy.py` warns on every run while it is off.

**Restrict to specific GitHub teams.** In `template/dex.config.yaml.tmpl`:

```yaml
      orgs:
        - name: ${GITHUB_ORG}
          teams:
            - platform
            - infra
```

Re-run `./deploy.py`. Only members of those teams can authenticate.

**Sync GitHub teams into NetBird groups.** Dex already emits `<org>:<team-slug>`
group claims. *Settings → Groups → JWT group sync*, claim name `groups`. You can
then write access policies per GitHub team.

**NetBird Proxy / CrowdSec.** Deliberately omitted — they add attack surface and
need a `*.netbird` wildcard CNAME. See the
[reverse-proxy guide](https://docs.netbird.io/selfhosted/migration/enable-reverse-proxy)
if you want them later.

---

## Appendix — unattended first run

The owner account can be created over the API instead of through `/setup`. Add to
the `netbird-server` service:

```yaml
    environment:
      NB_SETUP_PAT_ENABLED: "true"
```

Then, before anyone visits the dashboard:

```bash
curl -X POST "https://netbird.example.com/api/setup" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "name": "Admin",
    "password": "<long-random-password>",
    "create_pat": true,
    "pat_expire_in": 7
  }'
```

The response contains a personal access token, shown once, which can drive the
rest of the configuration through the REST API. The endpoint becomes unavailable
after it succeeds. For ongoing automation, create a dedicated service user with
its own PAT and let the setup token expire.

---

## References

- [Self-hosting quickstart](https://docs.netbird.io/selfhosted/selfhosted-quickstart)
- [Configuration files reference](https://docs.netbird.io/selfhosted/maintenance/configuration-files)
- [Local user management (embedded IdP)](https://docs.netbird.io/selfhosted/identity-providers/local)
- [Generic OIDC provider](https://docs.netbird.io/selfhosted/identity-providers/generic-oidc)
- [Automated setup with a PAT](https://docs.netbird.io/selfhosted/automated-setup)
- [`config.yaml.example` upstream](https://github.com/netbirdio/netbird/blob/main/combined/config.yaml.example)
- [Dex GitHub connector](https://dexidp.io/docs/connectors/github/)
