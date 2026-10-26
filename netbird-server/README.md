# NetBird self-hosted control plane

Part of [NetBird Docker Host](../README.md).

A private VPN control plane on one Linux VM, where **logging in means being a
member of your GitHub organisation**. Everything is driven by a single config
file and a single command, `deploy.py`. It renders every config file, starts the
stack, waits for it to settle, and runs nine checks against the running system,
telling you what to fix when one fails.

Requirements and the install steps are in the root README under
[Deploy the server](../README.md#deploy-the-server); everyday commands and exit
codes are under [Operate](../README.md#operate). This page is the reference: how
the stack works, day-2 operations, troubleshooting and hardening.

---

## How it works

### Why there is a Dex container

**GitHub is not an OIDC provider.** It has no
`/.well-known/openid-configuration` and never issues an `id_token`; it speaks
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
GitHub OAuth App              org members only, everyone else stops here
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

Since v0.62 NetBird ships management, signal, relay and STUN as one binary, so
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

`dex/config.yaml` is `0644`, not `0600`, deliberately: the Dex container runs as
UID 1001 and cannot read a `0600` file owned by you. The `dex/` directory is
`0700` instead, which protects it on the host just as well.

Note that secrets do end up in more than one file on disk. `netbird-server` does
no environment expansion in its config, which is why templates exist at all.
`netbird.yaml` is the single source for *authoring*, not for storage.

### Files

| File | Purpose |
|---|---|
| `netbird.example.yaml` | Committed template, every field documented |
| `netbird.yaml` | **Not committed.** Your config and secrets, the only file you edit |
| `deploy.py` | Renders configs, starts the stack, validates it |
| `docker-compose.yml` | The stack |
| `template/*.tmpl` | Templates for the server and Dex configs |
| `postgres/init-databases.sh` | Creates the two extra databases on first boot |
| `config.yaml`, `dex/config.yaml`, `.env` | **Generated**, never edit |

---

## Day-2 operations

### Backups

Two things matter: the database and `netbird.yaml`. Everything else is derived,
and the `netbird_data` volume now holds only re-downloadable geolocation data.

```bash
mkdir -p ~/netbird-backups && chmod 700 ~/netbird-backups
docker compose exec -T postgres pg_dumpall -U netbird \
  | gzip > ~/netbird-backups/netbird-db-$(date +%F).sql.gz

cp netbird.yaml ~/netbird-backups/netbird-conf-$(date +%F).yaml
```

The backups go outside the git clone on purpose, so they can never be committed.
Copy `~/netbird-backups` off this host as well.

Keep the two together: rows are encrypted with `server.store_encryption_key`, so
a dump without the config is unreadable.

`pg_dumpall` is deliberate: state spans `netbird` (peers, groups, policies,
setup keys), `netbird_events` (audit log) and `netbird_idp` (local users and IdP
connectors), and dumping them one by one invites forgetting one.

Restore into an empty instance:

```bash
docker compose down
docker volume rm netbird_netbird_pgdata
docker compose up -d postgres
gunzip -c ~/netbird-backups/netbird-db-YYYY-MM-DD.sql.gz \
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

Run `./deploy.py validate` first; most failures name their own fix.

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

then `./deploy.py`. Note the flag is positive: `local_auth: false` renders
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

**NetBird Proxy / CrowdSec.** Deliberately omitted: they add attack surface and
need a `*.netbird` wildcard CNAME. See the
[reverse-proxy guide](https://docs.netbird.io/selfhosted/migration/enable-reverse-proxy)
if you want them later.

---

## Appendix: unattended first run

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
