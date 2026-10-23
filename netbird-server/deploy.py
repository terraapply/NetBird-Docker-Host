#!/usr/bin/env python3
"""Provision, update and validate the self-hosted NetBird stack.

Reads netbird.yaml, which holds all configuration and all secrets, renders
config.yaml, dex/config.yaml and .env from it, brings the stack up, then
validates it end to end.

  ./deploy.py              provision (default): render, up, wait, validate
  ./deploy.py update       pull the images named in netbird.yaml, recreate
  ./deploy.py validate     run the checks only, change nothing
  ./deploy.py status       compose ps plus a health summary
  ./deploy.py config       print the resolved config, secrets redacted
  ./deploy.py compose -- logs --tail=50 dex
                           docker compose with the right project name

netbird.yaml is the only file you edit. It holds all configuration and all
secrets, is gitignored, and everything else is rendered from it:

  template/config.yaml.tmpl     -> config.yaml
  template/dex.config.yaml.tmpl -> dex/config.yaml
                                -> .env  (what docker compose interpolates)

Exit codes:
  0  success
  1  usage or internal error
  2  preflight or config error   -- nothing was mutated
  3  provisioning error          -- the stack may be partially up
  4  validation failure          -- the stack is up, checks failed

Style: lowercase "error:" to stderr, no colour, and
every failure that has a known fix prints it.
"""

import argparse
import base64
import hashlib
import http.client
import json
import os
import random
import shutil
import socket
import ssl
import string
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from urllib.parse import quote

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "error: PyYAML is not installed\n"
        "       install with: apt-get install -y python3-yaml\n"
    )
    raise SystemExit(2) from None

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_VERSION = 1

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"


# --------------------------------------------------------------- output

def err(msg, *hints):
    sys.stderr.write("error: %s\n" % msg)
    for h in hints:
        sys.stderr.write("       %s\n" % h)


def info(msg):
    sys.stdout.write("%s\n" % msg)
    sys.stdout.flush()


@dataclass
class Result:
    id: str
    status: str
    summary: str
    hints: list = field(default_factory=list)


# --------------------------------------------------------------- config

class Config:
    """Typed view of netbird.yaml. Reports every schema problem at once."""

    def __init__(self, raw, path):
        self.path = path
        problems = []

        def need(dotted, default=None):
            node = raw
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    if default is None:
                        problems.append(dotted)
                        return None
                    return default
                node = node[part]
            return node

        version = raw.get("schema_version", 1)
        # bool is an int subclass, and a quoted "1" would crash the comparison.
        if not isinstance(version, int) or isinstance(version, bool):
            problems.append("schema_version must be an integer, not %r"
                            % (version,))
        elif version > SCHEMA_VERSION:
            problems.append(
                "schema_version %s is newer than this script understands (%s)"
                % (version, SCHEMA_VERSION))

        self.project = need("project.name", "netbird")
        self.netbird_domain = need("domains.netbird")
        self.dex_domain = need("domains.dex")
        self.acme_email = need("acme.email")
        self.github_org = need("github.org")
        self.github_client_id = need("github.client_id")
        self.github_client_secret = need("github.client_secret")
        self.images = need("images") or {}
        self.pg_user = need("postgres.user", "netbird")
        self.pg_password = need("postgres.password", "")
        self.pg_databases = need("postgres.databases", []) or []
        self.oidc_client_id = need("oidc.client_id", "netbird")
        self.oidc_client_secret = need("oidc.client_secret", "")
        self.local_auth = need("server.local_auth", True)
        self.relay_auth_secret = need("server.relay_auth_secret", "")
        self.session_cookie_key = need("server.session_cookie_key", "")
        self.store_encryption_key = need("server.store_encryption_key", "")
        self.reach = need("validation.reach", "both")
        self.checks = need("validation.checks", {}) or {}
        self.timeouts = need("timeouts", {}) or {}
        self.preflight = need("preflight", {}) or {}

        self.oidc_redirect_uri = (raw.get("oidc") or {}).get("redirect_uri")
        if not self.oidc_redirect_uri and self.netbird_domain:
            self.oidc_redirect_uri = (
                "https://%s/oauth2/callback" % self.netbird_domain)

        for key in ("traefik", "netbird_server", "dashboard", "dex", "postgres"):
            if key not in self.images:
                problems.append("images.%s" % key)

        if problems:
            err("%s is missing or invalid: %s" % (path, ", ".join(problems)),
                "compare against the committed netbird.example.yaml")
            raise SystemExit(2)

    def timeout(self, name, scale=1.0):
        defaults = {
            "pull": 600, "services_ready": 180, "postgres_ready": 90,
            "tls_ready": 180, "http": 20, "stun": 3,
        }
        return int(self.timeouts.get(name, defaults[name]) * scale)

    def dsn(self, database):
        """One credential, three connection strings composed from it.

        The password is percent-encoded: an unescaped '@' or '/' silently
        reparses the host half of the URL.
        """
        return ("postgres://%s:%s@postgres:5432/%s?sslmode=disable"
                % (self.pg_user, quote(self.pg_password, safe=""), database))

    def template_vars(self):
        """Explicit map from netbird.yaml to template placeholders.

        Deliberately not auto-flattened: domains.netbird -> NETBIRD_DOMAIN is
        not derivable by rule, and this table is the only place a reader can
        see what a placeholder means.
        """
        dbs = self.pg_databases + ["netbird", "netbird_events", "netbird_idp"]
        return {
            "NETBIRD_DOMAIN": self.netbird_domain,
            "DEX_DOMAIN": self.dex_domain,
            "GITHUB_ORG": self.github_org,
            "GITHUB_CLIENT_ID": self.github_client_id,
            "GITHUB_CLIENT_SECRET": self.github_client_secret,
            "OIDC_CLIENT_ID": self.oidc_client_id,
            "OIDC_REDIRECT_URI": self.oidc_redirect_uri,
            "NETBIRD_OIDC_CLIENT_SECRET": self.oidc_client_secret,
            # Inverted, and lowercased: netbird's flag is negative, and Go's
            # yaml wants true/false rather than Python's True/False.
            "LOCAL_AUTH_DISABLED": "false" if self.local_auth else "true",
            "NETBIRD_RELAY_AUTH_SECRET": self.relay_auth_secret,
            "NETBIRD_SESSION_COOKIE_KEY": self.session_cookie_key,
            "NETBIRD_STORE_ENCRYPTION_KEY": self.store_encryption_key,
            "NETBIRD_STORE_DSN": self.dsn(dbs[0]),
            "NETBIRD_ACTIVITY_DSN": self.dsn(dbs[1]),
            "NETBIRD_IDP_DSN": self.dsn(dbs[2]),
        }

    def env_file_vars(self):
        """Exactly what docker-compose.yml interpolates. Nothing more."""
        return {
            "COMPOSE_PROJECT_NAME": self.project,
            "NETBIRD_DOMAIN": self.netbird_domain,
            "DEX_DOMAIN": self.dex_domain,
            "LETSENCRYPT_EMAIL": self.acme_email,
            "TRAEFIK_IMAGE": self.images["traefik"],
            "NETBIRD_SERVER_IMAGE": self.images["netbird_server"],
            "DASHBOARD_IMAGE": self.images["dashboard"],
            "DEX_IMAGE": self.images["dex"],
            "POSTGRES_IMAGE": self.images["postgres"],
            "POSTGRES_PASSWORD": self.pg_password,
        }

    def service_images(self):
        """Compose service name -> image. Used to assert the running tag."""
        return {
            "traefik": self.images["traefik"],
            "netbird-server": self.images["netbird_server"],
            "dashboard": self.images["dashboard"],
            "dex": self.images["dex"],
            "postgres": self.images["postgres"],
        }

    def secrets(self):
        return {
            "postgres.password": self.pg_password,
            "oidc.client_secret": self.oidc_client_secret,
            "server.relay_auth_secret": self.relay_auth_secret,
            "server.session_cookie_key": self.session_cookie_key,
            "server.store_encryption_key": self.store_encryption_key,
            "github.client_secret": self.github_client_secret,
            "github.client_id": self.github_client_id,
        }


def load_config(path):
    if not os.path.exists(path):
        err("%s not found" % path, "expected next to deploy.py")
        raise SystemExit(2)
    with open(path) as fh:
        try:
            raw = yaml.safe_load(fh) or {}
        except yaml.YAMLError as e:
            err("%s is not valid yaml: %s" % (path, e),
                "compare against the committed netbird.example.yaml")
            raise SystemExit(2) from None
    if not isinstance(raw, dict):
        err("%s must be a mapping at the top level" % path,
            "compare against the committed netbird.example.yaml")
        raise SystemExit(2)
    return Config(raw, path)


# --------------------------------------------------------------- render

# (template, output, mode). Modes differ for a reason:
#   config.yaml     0600 -- netbird-server runs as root, so it can read it
#   dex/config.yaml 0644 -- dex runs as UID 1001 and would get EACCES on 0600.
#                           dex/ is chmod 0700 instead, which gives identical
#                           protection on the host: the container resolves the
#                           path in its own namespace and never traverses ours.
TEMPLATES = (
    ("template/config.yaml.tmpl", "config.yaml", 0o600),
    ("template/dex.config.yaml.tmpl", "dex/config.yaml", 0o644),
)
DEX_DIR_MODE = 0o700


def _render_one(src, dst, variables):
    """Render one template. Returns the text; does not write anything yet."""
    with open(os.path.join(HERE, src)) as fh:
        raw = fh.read()
    try:
        # substitute(), never safe_substitute(): a missing placeholder must be
        # a loud failure, not a literal ${FOO} shipped into a live config.
        text = string.Template(raw).substitute(variables)
    except KeyError as e:
        err("%s uses ${%s}, which netbird.yaml does not define"
            % (src, e.args[0]),
            "add it to Config.template_vars() or fix the template")
        raise SystemExit(2) from None
    except ValueError as e:
        err("%s is not a valid template: %s" % (src, e),
            "a bare '$' must be written '$$'")
        raise SystemExit(2) from None

    for bad in ("${", "{{"):
        if bad in text:
            line = next((i + 1 for i, row in enumerate(text.splitlines())
                         if bad in row), 0)
            err("%s still contains %s after rendering (line %d)"
                % (dst, bad, line),
                "a value substituted in must not itself contain a placeholder")
            raise SystemExit(2)
    try:
        yaml.safe_load(text)
    except yaml.YAMLError as e:
        err("%s is not valid yaml after rendering: %s" % (dst, e))
        raise SystemExit(2) from None
    return text


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def write_env_file(cfg, shas=None):
    lines = [
        "# Generated by deploy.py from netbird.yaml. Do not edit.",
        "# Only what docker-compose.yml interpolates; everything else is",
        "# rendered directly into config.yaml and dex/config.yaml.",
        "",
    ]
    values = dict(cfg.env_file_vars())
    values.update(shas or {})
    for k in sorted(values):
        lines.append("%s=%s" % (k, values[k]))
    return "\n".join(lines) + "\n"


def phase_render(ctx):
    """Render every output before starting anything.

    All-or-nothing on purpose: a failure halfway through must not leave a
    half-written config next to a running stack.
    """
    cfg = ctx.cfg
    variables = cfg.template_vars()

    pending = [(dst, _render_one(src, dst, variables), mode)
               for src, dst, mode in TEMPLATES]

    # Exposed to compose as labels; without them `up -d` sees no change when
    # only file *content* changed and silently leaves the old container running.
    shas = {
        "CONFIG_YAML_SHA": _sha(pending[0][1]),
        "DEX_CONFIG_SHA": _sha(pending[1][1]),
    }
    pending.append((".env", write_env_file(cfg, shas), 0o600))

    dexdir = os.path.join(HERE, "dex")
    if not os.path.isdir(dexdir):
        os.makedirs(dexdir, mode=DEX_DIR_MODE, exist_ok=True)
    os.chmod(dexdir, DEX_DIR_MODE)

    for dst, text, mode in pending:
        full = os.path.join(HERE, dst)
        parent = os.path.dirname(full)
        # A bind-mount whose host path is missing makes Docker create a
        # DIRECTORY there; this project has been bitten by exactly that.
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, mode=0o755, exist_ok=True)
        if os.path.isdir(full):
            err("%s is a directory, not a file" % dst,
                "docker created it when the file was missing",
                "fix: docker compose down && rmdir %s" % dst)
            raise SystemExit(2)
        # Create with the mode, rather than chmod after writing: otherwise a
        # world-readable file holding the store key exists for a moment.
        tmp = os.path.join(os.path.dirname(full),
                           ".%s.tmp" % os.path.basename(full))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, full)
        info("rendered %s (mode %o)" % (dst, mode))

    try:
        with open(os.path.join(HERE, "config.yaml")) as fh:
            ctx.rendered = yaml.safe_load(fh)
    except Exception:
        ctx.rendered = None


# --------------------------------------------------------------- process

class Ctx:
    def __init__(self, cfg, args):
        self.cfg = cfg
        self.args = args
        self.scale = args.timeout_scale
        # No injection: .env is generated, so compose and any bare
        # `docker compose` invocation see the same values.
        self.env = dict(os.environ)
        self.rendered = None

    def timeout(self, name):
        return self.cfg.timeout(name, self.scale)


def run(argv, ctx, timeout=60, check=False, stream=False):
    try:
        if stream:
            p = subprocess.run(argv, cwd=HERE, env=ctx.env, timeout=timeout)
            return p.returncode, "", ""
        p = subprocess.run(
            argv, cwd=HERE, env=ctx.env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except subprocess.TimeoutExpired:
        if check:
            err("timed out after %ss: %s" % (timeout, " ".join(argv)))
            raise SystemExit(3) from None
        return 124, "", "timeout"
    except FileNotFoundError:
        err("command not found: %s" % argv[0])
        raise SystemExit(2) from None
    if check and p.returncode != 0:
        err(
            "%s failed" % " ".join(argv[:3]),
            *(p.stderr or p.stdout or "").strip().splitlines()[-8:]
        )
        raise SystemExit(3)
    return p.returncode, p.stdout, p.stderr


def compose(ctx, *args, **kw):
    base = [
        "docker", "compose",
        "--env-file", ".env",
        "-p", ctx.cfg.project,
        "-f", "docker-compose.yml",
    ]
    return run(base + list(args), ctx, **kw)


# --------------------------------------------------------------- preflight

def phase_preflight(ctx, resources=True, need_rendered=False):
    """Config consistency always; resource headroom only before mutating."""
    cfg = ctx.cfg
    problems = []

    for rel in ("docker-compose.yml", "template/config.yaml.tmpl",
                "template/dex.config.yaml.tmpl"):
        if not os.path.exists(os.path.join(HERE, rel)):
            problems.append("missing file: %s" % rel)
    if need_rendered and not os.path.exists(os.path.join(HERE, ".env")):
        problems.append(".env has not been generated yet -- run ./deploy.py first")
    if problems:
        for x in problems:
            err(x)
        raise SystemExit(2)

    # netbird.yaml now holds secrets: it must never be committed. A host
    # without git cannot commit it either, so a missing git only warns.
    name = os.path.basename(cfg.path)
    if shutil.which("git") is None:
        info("warn: git not found, skipping the check that %s is not committed"
             % name)
    else:
        rc, _, _ = run(["git", "ls-files", "--error-unmatch", name],
                       ctx, timeout=15)
        if rc == 0:
            err("%s is tracked by git but now contains secrets" % name,
                "fix: git rm --cached %s" % name,
                "and confirm it is listed in .gitignore")
            raise SystemExit(2)

    mode = os.stat(cfg.path).st_mode & 0o777
    if mode != 0o600:
        info("warn: %s is mode %o, expected 600 (chmod 600 %s)"
             % (os.path.basename(cfg.path), mode, os.path.basename(cfg.path)))

    # Report every bad secret at once rather than one per run.
    if not isinstance(cfg.local_auth, bool):
        err("server.local_auth must be true or false, not %r" % (cfg.local_auth,),
            "it is a boolean: true keeps local email/password login working")
        raise SystemExit(2)
    if not cfg.local_auth:
        info("warn: server.local_auth is false -- local email/password login is")
        info("      disabled, so github is the only way in. a github outage or an")
        info("      expired client secret will lock out everyone, including you.")

    mistyped = sorted("%s (%s)" % (k, type(v).__name__)
                      for k, v in cfg.secrets().items()
                      if v is not None and not isinstance(v, str))
    if mistyped:
        err("these must be quoted strings in %s: %s"
            % (os.path.basename(cfg.path), ", ".join(mistyped)),
            "yaml turns an unquoted all-digit or yes/no value into a number",
            "or a boolean, which is not the credential you generated",
            'fix: wrap the value in double quotes')
        raise SystemExit(2)

    unsafe = sorted(k for k, v in cfg.secrets().items()
                    if isinstance(v, str)
                    and (v != v.strip() or "\n" in v or '"' in v
                         or "\\" in v or "$" in v))
    if unsafe:
        err("these contain characters that break the generated files: %s"
            % ", ".join(unsafe),
            "leading/trailing spaces, quotes, backslashes and '$' are unsafe",
            "in yaml and in .env; regenerate with openssl rand -hex 32")
        raise SystemExit(2)

    blank = sorted(k for k, v in cfg.secrets().items()
                   if not v or str(v).startswith("replace_me")
                   or str(v).endswith("_replace_me"))
    if blank:
        err("unset in %s: %s" % (os.path.basename(cfg.path), ", ".join(blank)),
            "each field in netbird.example.yaml carries its openssl command",
            "for example: openssl rand -hex 32")
        raise SystemExit(2)

    key = cfg.store_encryption_key
    if not key.endswith("="):
        err("server.store_encryption_key must keep its base64 '=' padding",
            "go decodes it with base64.StdEncoding, which rejects unpadded input",
            "regenerate with: openssl rand -base64 32")
        raise SystemExit(2)
    try:
        if len(base64.b64decode(key, validate=True)) != 32:
            raise ValueError
    except Exception:
        err("server.store_encryption_key must decode to exactly 32 bytes",
            "regenerate with: openssl rand -base64 32")
        raise SystemExit(2) from None

    clashing = []
    for k, v in cfg.env_file_vars().items():
        if k in os.environ and os.environ[k] != str(v):
            clashing.append("%s (shell=%s, netbird.yaml=%s)"
                            % (k, os.environ[k], v))
    if clashing:
        err("exported shell variables would override the generated .env:",
            *clashing + ["docker compose reads the process environment before",
                         "--env-file, so the exported value wins",
                         "fix: unset them"])
        raise SystemExit(2)

    if not resources:
        return

    free_mb = shutil.disk_usage(HERE).free // (1024 * 1024)
    need_mb = cfg.preflight.get("min_free_disk_mb", 1500)
    if free_mb < need_mb:
        err("only %d MB free disk, need at least %d MB" % (free_mb, need_mb),
            "reclaim with: docker image prune -af")
        raise SystemExit(2)

    avail = _mem_available_mb()
    min_mem = cfg.preflight.get("min_free_mem_mb", 300)
    if avail is not None and avail < min_mem:
        info("warn: only %d MB memory available (want %d MB); postgres may be "
             "OOM-killed" % (avail, min_mem))


def _mem_available_mb():
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


# --------------------------------------------------------------- state

def volume_exists(ctx, name):
    full = "%s_%s" % (ctx.cfg.project, name)
    rc, out, _ = run(["docker", "volume", "ls", "-q", "-f", "name=^%s$" % full],
                     ctx, timeout=20)
    return rc == 0 and out.strip() != ""


def probe_setup_required(ctx):
    """None when the server did not answer."""
    try:
        resp = https_get(ctx, ctx.cfg.netbird_domain, "/api/instance",
                         timeout=ctx.timeout("http"))
    except Exception:
        return None
    if resp.status != 200:
        return None
    try:
        return bool(json.loads(resp.body).get("setup_required"))
    except Exception:
        return None


# --------------------------------------------------------------- http

class Resp:
    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self.body = body


def _request(host, connect_host, method, path, timeout, headers=None, body=None):
    ctxs = ssl.create_default_context()
    # The loopback path deliberately trusts any certificate: it is testing that
    # Traefik routes and terminates, not the chain. The tls check inspects the
    # certificate properly and separately.
    ctxs.check_hostname = False
    ctxs.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(
        connect_host, 443, timeout=timeout, context=ctxs)
    try:
        h = {"Host": host}
        if headers:
            h.update(headers)
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read().decode("utf-8", "replace")
        return Resp(r.status, dict(r.getheaders()), data)
    finally:
        conn.close()


def https_get(ctx, host, path, timeout=None, method="GET",
              headers=None, body=None):
    timeout = timeout or ctx.timeout("http")
    connect = "127.0.0.1" if ctx.cfg.reach in ("loopback", "both") else host
    return _request(host, connect, method, path, timeout, headers, body)


def peer_cert(host, connect_host, timeout):
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    with socket.create_connection((connect_host, 443), timeout=timeout) as sock:
        with c.wrap_socket(sock, server_hostname=host) as ss:
            return ss.getpeercert(), ss.getpeercert(binary_form=False)


# --------------------------------------------------------------- stun

def stun_binding(host, port, timeout):
    """RFC 5389 binding request. Returns the reflexive address, or None.

    Replaces `nc -vzu`, which proves nothing: UDP is connectionless, so nc
    reports success whenever no ICMP unreachable comes back -- including when
    the packet was silently dropped.
    """
    txid = bytes(random.getrandbits(8) for _ in range(12))
    packet = struct.pack("!HHI", 0x0001, 0, 0x2112A442) + txid
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(packet, (host, port))
            deadline = time.time() + timeout
            while time.time() < deadline:
                data, _ = s.recvfrom(2048)
                if len(data) < 20:
                    continue
                mtype, mlen, cookie = struct.unpack("!HHI", data[:8])
                if data[8:20] != txid or mtype != 0x0101:
                    continue  # not our response; keep listening
                return _parse_xor_mapped(data[20:20 + mlen]) or "no address"
    except (socket.timeout, OSError):
        return None
    return None


def _parse_xor_mapped(attrs):
    i = 0
    while i + 4 <= len(attrs):
        atype, alen = struct.unpack("!HH", attrs[i:i + 4])
        val = attrs[i + 4:i + 4 + alen]
        if atype in (0x0020, 0x8020) and len(val) >= 8 and val[1] == 0x01:
            port = struct.unpack("!H", val[2:4])[0] ^ 0x2112
            ip = struct.unpack("!I", val[4:8])[0] ^ 0x2112A442
            return "%d.%d.%d.%d:%d" % (
                (ip >> 24) & 0xFF, (ip >> 16) & 0xFF,
                (ip >> 8) & 0xFF, ip & 0xFF, port)
        if atype == 0x0001 and len(val) >= 8:
            return "%d.%d.%d.%d:%d" % (
                val[4], val[5], val[6], val[7],
                struct.unpack("!H", val[2:4])[0])
        i += 4 + alen + ((4 - alen % 4) % 4)
    return None


# --------------------------------------------------------------- checks

def check_services(ctx):
    cfg = ctx.cfg
    want = cfg.service_images()
    deadline = time.time() + ctx.timeout("services_ready")
    last = ""
    # RestartCount is a lifetime counter that never resets while the container
    # exists, so its absolute value says nothing about health -- a container
    # that flapped once at install and has run for weeks still reports it.
    # Only docker's own Restarting flag, or the count rising while we watch,
    # means a live crash loop.
    restarts_seen = {}
    while time.time() < deadline:
        rc, out, _ = compose(ctx, "ps", "--format", "json", timeout=30)
        rows = []
        for line in (out or "").strip().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        if rows and isinstance(rows[0], list):
            rows = rows[0]

        by_service = {r.get("Service"): r for r in rows}
        pending, bad = [], []
        for svc in want:
            r = by_service.get(svc)
            if r is None:
                pending.append("%s not created" % svc)
                continue
            state = (r.get("State") or "").lower()
            health = (r.get("Health") or "").lower()
            if state != "running":
                pending.append("%s is %s" % (svc, state or "?"))
            elif health and health not in ("healthy", ""):
                pending.append("%s is %s" % (svc, health))

            name = r.get("Name")
            if name:
                rc2, insp, _ = run(
                    ["docker", "inspect", name, "--format",
                     "{{.RestartCount}} {{.State.OOMKilled}} {{.State.Restarting}}"],
                    ctx, timeout=20)
                if rc2 == 0 and insp.strip():
                    parts = insp.split()
                    if parts[1] == "true":
                        return Result("services", FAIL,
                                      "%s was OOM-killed" % svc,
                                      ["this vm has little free memory and now runs postgres",
                                       "fix: add swap, or lower shared_buffers on the postgres service"])
                    count = int(parts[0])
                    before = restarts_seen.setdefault(svc, count)
                    if parts[2] == "true":
                        why = "%s is in restart backoff" % svc
                    elif count > before:
                        why = ("%s restarted %d time(s) while waiting"
                               % (svc, count - before))
                    else:
                        why = ""
                    if why:
                        logs = compose(ctx, "logs", "--tail=15", svc, timeout=30)[1]
                        return Result("services", FAIL, why,
                                      logs.strip().splitlines()[-8:] or
                                      ["docker compose logs --tail=100 %s" % svc])

        if not pending:
            for svc, image in want.items():
                r = by_service.get(svc) or {}
                got = r.get("Image") or ""
                if got and got != image:
                    bad.append("%s runs %s, expected %s" % (svc, got, image))
            if bad:
                return Result("services", FAIL, bad[0],
                              ["the container was not recreated after the tag changed",
                               "fix: ./deploy.py update"])
            return Result("services", OK, "%d/%d running, images match"
                          % (len(want), len(want)))
        last = "; ".join(pending)
        time.sleep(3)

    return Result("services", FAIL, "not ready in time: %s" % last,
                  ["inspect with: docker compose logs --tail=100"])


def check_postgres(ctx):
    cfg = ctx.cfg
    deadline = time.time() + ctx.timeout("postgres_ready")
    while time.time() < deadline:
        rc, _, _ = compose(ctx, "exec", "-T", "postgres",
                           "pg_isready", "-U", cfg.pg_user, timeout=30)
        if rc == 0:
            break
        time.sleep(3)
    else:
        return Result("postgres", FAIL, "pg_isready never succeeded",
                      ["docker compose logs --tail=50 postgres"])

    rc, out, _ = compose(ctx, "exec", "-T", "postgres", "psql", "-U",
                         cfg.pg_user, "-d", "postgres", "-Atc",
                         "select datname from pg_database", timeout=30)
    have = set((out or "").split())
    missing = [d for d in cfg.pg_databases if d not in have]
    if missing:
        return Result("postgres", FAIL,
                      "database(s) missing: %s" % ", ".join(missing),
                      ["a missing netbird_events means the audit log is silently not written",
                       "fix: docker compose exec -T postgres createdb -U %s %s"
                       % (cfg.pg_user, missing[0])])
    return Result("postgres", OK, "ready, %d/%d databases present"
                  % (len(cfg.pg_databases), len(cfg.pg_databases)))


def _tls_once(host, connect, timeout):
    cert, _ = peer_cert(host, connect, timeout)
    issuer = ""
    for rdn in cert.get("issuer", ()):
        for k, v in rdn:
            if k == "organizationName" or k == "commonName":
                issuer = v
    return cert, issuer


def check_tls(ctx):
    cfg = ctx.cfg
    deadline = time.time() + ctx.timeout("tls_ready")
    hosts = [cfg.netbird_domain, cfg.dex_domain]
    connect = "127.0.0.1" if cfg.reach in ("loopback", "both") else None
    last = ""
    while time.time() < deadline:
        results = []
        for h in hosts:
            try:
                cert, issuer = _tls_once(h, connect or h, ctx.timeout("http"))
            except Exception as e:
                last = "%s: %s" % (h, e)
                results = None
                break
            if "TRAEFIK DEFAULT CERT" in issuer.upper():
                last = "%s is served traefik's self-signed default" % h
                results = None
                break
            results.append((h, cert))
        if results:
            return Result("tls", OK, "both hosts, issued certificates")
        time.sleep(5)

    return Result("tls", FAIL, last or "no certificate",
                  ["acme has not completed; usual causes are a proxied dns record",
                   "or a blocked port 80/443",
                   "check with: docker compose logs traefik | grep -i acme"])


def _poll(ctx, fn, budget_name="tls_ready", every=5):
    """Retry fn() until it returns an OK/WARN result or the budget runs out.

    netbird-server accepts connections before its migrations complete, so a
    single-shot HTTP check races startup and reports a false failure.
    """
    deadline = time.time() + ctx.timeout(budget_name)
    last = None
    while True:
        last = fn()
        if last.status in (OK, WARN):
            return last
        if time.time() >= deadline:
            return last
        time.sleep(every)


def _discovery(ctx, host, expect_issuer, check_id):
    try:
        r = https_get(ctx, host, "/.well-known/openid-configuration"
                      if check_id == "oidc_dex"
                      else "/oauth2/.well-known/openid-configuration")
    except Exception as e:
        return Result(check_id, FAIL, "%s unreachable: %s" % (host, e))
    if r.status != 200:
        return Result(check_id, FAIL, "discovery returned %d" % r.status)
    try:
        doc = json.loads(r.body)
    except ValueError:
        return Result(check_id, FAIL, "discovery is not json")
    got = doc.get("issuer", "")
    if "$" in got or "{{" in got:
        return Result(check_id, FAIL,
                      "issuer contains an unexpanded template: %s" % got,
                      ["the file was not rendered from its template",
                       "fix: ./deploy.py  (never edit the generated file)"])
    if got != expect_issuer:
        return Result(check_id, FAIL,
                      "issuer is %s, expected %s" % (got, expect_issuer))
    return Result(check_id, OK, "issuer %s" % got)


def check_oidc_netbird(ctx):
    return _poll(ctx, lambda: _discovery(
        ctx, ctx.cfg.netbird_domain,
        "https://%s/oauth2" % ctx.cfg.netbird_domain, "oidc_netbird"))


def check_oidc_dex(ctx):
    return _poll(ctx, lambda: _discovery(
        ctx, ctx.cfg.dex_domain,
        "https://%s" % ctx.cfg.dex_domain, "oidc_dex"))


def _api_401_once(ctx):
    try:
        r = https_get(ctx, ctx.cfg.netbird_domain, "/api/users")
    except Exception as e:
        return Result("api_401", FAIL, "unreachable: %s" % e)
    if r.status == 401:
        return Result("api_401", OK, "/api/users -> 401")
    if r.status == 200:
        return Result("api_401", FAIL, "/api/users returned 200, expected 401",
                      ["the api is not requiring a token -- do not expose this host"])
    if r.status in (404, 502, 503):
        return Result("api_401", FAIL,
                      "/api/users returned %d, expected 401" % r.status,
                      ["traefik router priority collision: the dashboard catch-all is",
                       "matching /api. dashboard must stay priority=1 and the",
                       "netbird-server routers priority=100 in docker-compose.yml"])
    return Result("api_401", FAIL, "/api/users returned %d" % r.status)


def check_api_401(ctx):
    return _poll(ctx, lambda: _api_401_once(ctx))


def check_dex_redirect_uri(ctx):
    cfg = ctx.cfg
    from urllib.parse import urlencode
    q = urlencode({
        "client_id": cfg.oidc_client_id,
        "redirect_uri": cfg.oidc_redirect_uri,
        "response_type": "code",
        "scope": "openid profile email groups",
        "state": "deploycheck",
        "nonce": "deploycheck",
    })
    # Dex validates the redirect_uri at /auth/<connector>, not at /auth: the
    # first hop returns 302 even for a completely unregistered URI. Follow
    # redirects that stay on the Dex host, then judge the final status.
    path = "/auth?" + q
    try:
        for _ in range(3):
            r = https_get(ctx, cfg.dex_domain, path)
            if r.status not in (302, 303):
                break
            loc = r.headers.get("Location", "")
            if not loc:
                break
            if loc.startswith("http"):
                from urllib.parse import urlparse
                u = urlparse(loc)
                if u.netloc != cfg.dex_domain:
                    return Result("dex_redirect_uri", OK,
                                  "accepted, handed off to %s" % u.netloc)
                path = u.path + (("?" + u.query) if u.query else "")
            else:
                path = loc
    except Exception as e:
        return Result("dex_redirect_uri", FAIL, "unreachable: %s" % e)

    if r.status == 200:
        return Result("dex_redirect_uri", OK, "accepted (connector page)")
    if r.status in (302, 303):
        return Result("dex_redirect_uri", OK, "accepted")
    return Result("dex_redirect_uri", FAIL,
                  "dex rejected the redirect_uri (%d)" % r.status,
                  ["sent: %s" % cfg.oidc_redirect_uri,
                   "dex matches redirect uris by exact string; a trailing slash",
                   "or extra path segment is a mismatch",
                   "fix: set oidc.redirect_uri in netbird.yaml, then ./deploy.py",
                   "dex/config.yaml is generated -- editing it is overwritten"])


def check_dex_client_secret(ctx):
    """Catches gomplate failing to expand the secret in dex/config.yaml.

    Both sides read the same .env variable, so they cannot drift by editing.
    What this finds is Dex holding a literal "{{ .Env.NETBIRD_OIDC_CLIENT_SECRET }}"
    as its client secret -- invisible until the first login fails at token
    exchange with an opaque error.
    """
    cfg = ctx.cfg
    secret = cfg.oidc_client_secret
    from urllib.parse import urlencode
    body = urlencode({
        "grant_type": "authorization_code",
        "code": "deploy-check-not-a-real-code",
        "redirect_uri": cfg.oidc_redirect_uri,
    })
    basic = base64.b64encode(
        ("%s:%s" % (cfg.oidc_client_id, secret)).encode()).decode()
    try:
        r = https_get(ctx, cfg.dex_domain, "/token", method="POST", body=body,
                      headers={"Authorization": "Basic " + basic,
                               "Content-Type": "application/x-www-form-urlencoded",
                               "Content-Length": str(len(body))})
    except Exception as e:
        return Result("dex_client_secret", FAIL, "unreachable: %s" % e)
    if r.status == 401:
        return Result("dex_client_secret", FAIL,
                      "dex rejected the client secret",
                      ["dex and the dashboard's identity-provider entry hold",
                       "different secrets. after changing oidc.client_secret you",
                       "must also update settings -> identity providers"])
    return Result("dex_client_secret", OK, "accepted (invalid_grant)")


def check_stun(ctx):
    cfg = ctx.cfg
    port = 3478
    if ctx.rendered:
        ports = (ctx.rendered.get("server") or {}).get("stunPorts") or []
        if ports:
            port = int(ports[0])

    for _ in range(3):
        got = stun_binding(cfg.netbird_domain, port, ctx.timeout("stun"))
        if got:
            return Result("stun", OK, "binding response, reflexive %s" % got)

    for _ in range(2):
        got = stun_binding("127.0.0.1", port, ctx.timeout("stun"))
        if got:
            return Result("stun", WARN,
                          "local ok; no response on %s:%d"
                          % (cfg.netbird_domain, port),
                          ["usually the router not supporting nat hairpinning,",
                           "which does not affect external clients",
                           "confirm from a host outside the lan"])
    return Result("stun", FAIL,
                  "no binding response on 127.0.0.1:%d" % port,
                  ["netbird-server is not serving stun",
                   "check server.stunPorts in config.yaml and the 3478:3478/udp",
                   "publish in docker-compose.yml"])


CHECKS = (
    ("services", check_services, ()),
    ("postgres", check_postgres, ("services",)),
    ("tls", check_tls, ("services",)),
    ("oidc_netbird", check_oidc_netbird, ("services", "tls")),
    ("oidc_dex", check_oidc_dex, ("services", "tls")),
    ("api_401", check_api_401, ("services", "tls")),
    ("dex_redirect_uri", check_dex_redirect_uri, ("services", "tls")),
    ("dex_client_secret", check_dex_client_secret, ("services", "tls")),
    ("stun", check_stun, ("services",)),
)


def run_checks(ctx):
    cfg = ctx.cfg
    only = set(ctx.args.only.split(",")) if ctx.args.only else None
    skip = set(ctx.args.skip.split(",")) if ctx.args.skip else set()

    results, failed = [], set()
    for cid, fn, deps in CHECKS:
        if only is not None and cid not in only:
            continue
        if cid in skip or not cfg.checks.get(cid, True):
            results.append(Result(cid, SKIP, "disabled"))
            continue
        blocked = [d for d in deps if d in failed]
        if blocked:
            # Do not burn a timeout per check on a stack that never came up.
            results.append(Result(cid, SKIP, "%s failed" % blocked[0]))
            continue
        try:
            r = fn(ctx)
        except Exception as e:  # a check must never abort the run
            r = Result(cid, FAIL, "check raised %s: %s" % (type(e).__name__, e))
        if r.status == FAIL:
            failed.add(cid)
        results.append(r)
    return results


# --------------------------------------------------------------- phases

def phase_pull(ctx):
    # Sequential on purpose: compose's parallel pull thrashes a single core and
    # a single spindle, and a failure should name one image.
    for svc, image in ctx.cfg.service_images().items():
        info("pulling %s (%s)" % (svc, image))
        rc, _, e = compose(ctx, "pull", svc, timeout=ctx.timeout("pull"))
        if rc != 0:
            err("pull failed for %s" % image, *(e or "").strip().splitlines()[-5:])
            raise SystemExit(3)


def phase_up(ctx):
    info("starting services")
    compose(ctx, "up", "-d", "--remove-orphans", timeout=600, check=True)


# --------------------------------------------------------------- report

def print_report(cfg, results, mode):
    info("")
    info("%s: %s" % (cfg.netbird_domain, mode))
    info("")
    counts = {OK: 0, WARN: 0, FAIL: 0, SKIP: 0}
    for r in results:
        counts[r.status] += 1
        info("[%-4s] %-18s %s" % (r.status, r.id.replace("_", "-"), r.summary))
        if r.status in (FAIL, WARN):
            for h in r.hints:
                info("         %s" % h)
    info("")
    info("%d checks: %d ok, %d warning, %d failed, %d skipped"
         % (len(results), counts[OK], counts[WARN], counts[FAIL], counts[SKIP]))


def print_onboarding(cfg):
    info("""
first run complete. three things are not automated:

1. create the break-glass admin
   open https://%(nb)s and you will be redirected to /setup.
   set an email, a name and a long password, and store the password in your
   password manager: this is the way back in if github sso breaks.
   /setup stops responding once an owner exists.

2. register dex as an identity provider
   settings -> identity providers -> add identity provider
     type          Generic OIDC
     name          GitHub          (this is the login button label)
     client id     %(cid)s
     client secret oidc.client_secret in netbird.yaml
     issuer        https://%(dex)s

3. approve the first github user
   the first person to log in through the github button arrives pending
   approval. an owner must approve them under settings -> users. only members
   of the %(org)s organisation get that far; everyone else is refused at dex.

back up server.store_encryption_key from netbird.yaml now, somewhere other than
this host. it encrypts user data in postgres and a restored backup without it
is unreadable.""" % {
        "nb": cfg.netbird_domain, "dex": cfg.dex_domain,
        "cid": cfg.oidc_client_id, "org": cfg.github_org})


# --------------------------------------------------------------- commands

def cmd_config(ctx):
    cfg = ctx.cfg
    info("config:      %s" % cfg.path)
    info("project:     %s" % cfg.project)
    info("reach:       %s" % cfg.reach)
    info("")
    info("generated .env:")
    for k, v in sorted(cfg.env_file_vars().items()):
        info("  %-24s %s" % (k, _redact(k, v)))
    info("")
    info("template variables:")
    for k, v in sorted(cfg.template_vars().items()):
        info("  %-30s %s" % (k, _redact(k, v)))
    return 0


def _redact(key, value):
    k = key.lower()
    if any(t in k for t in ("secret", "password", "key", "dsn")):
        return "<redacted>"
    return value


def cmd_compose(ctx, extra):
    if not extra:
        err("usage: ./deploy.py compose -- <docker compose args>",
            "example: ./deploy.py compose -- logs --tail=50 dex")
        return 1
    rc, _, _ = compose(ctx, *extra, timeout=900, stream=True)
    return rc


def cmd_status(ctx):
    phase_preflight(ctx, resources=False, need_rendered=True)
    compose(ctx, "ps", timeout=60, stream=True)
    sr = probe_setup_required(ctx)
    info("")
    if sr is None:
        info("setup: server did not answer /api/instance")
    elif sr:
        info("setup: no owner account yet (visit https://%s)"
             % ctx.cfg.netbird_domain)
    else:
        info("setup: complete")
    return 0


def cmd_validate(ctx, mode="validate", first_run=False):
    if mode == "validate":
        # A .env/netbird.yaml disagreement would make these checks probe a
        # different domain than the stack actually serves.
        phase_preflight(ctx, resources=False, need_rendered=True)
    results = run_checks(ctx)
    print_report(ctx.cfg, results, mode)
    failed = [r for r in results if r.status == FAIL]
    warned = [r for r in results if r.status == WARN]
    if failed:
        return 4
    if warned and ctx.args.strict:
        return 4
    if first_run or ctx.args.show_onboarding:
        print_onboarding(ctx.cfg)
    return 0


def cmd_up(ctx, update=False):
    phase_preflight(ctx)

    # Snapshot before mutating anything: this is the fallback for first-run
    # detection when the server cannot answer.
    pg_volume_before = volume_exists(ctx, "netbird_pgdata")

    phase_render(ctx)
    if update:
        phase_pull(ctx)
    phase_up(ctx)

    setup_required = probe_setup_required(ctx)
    if setup_required is None:
        first_run = not pg_volume_before
        if first_run:
            info("note: /api/instance did not answer; assuming first run")
    else:
        first_run = setup_required

    if update:
        first_run = False  # an update never prints onboarding

    return cmd_validate(ctx, "update" if update else "provision", first_run)


def main(argv):
    p = argparse.ArgumentParser(
        prog="deploy.py", description="provision and validate the netbird stack")
    p.add_argument("command", nargs="?", default="provision",
                   choices=("provision", "update", "validate", "status",
                            "config", "compose"))
    p.add_argument("extra", nargs="*", help="args for `compose` passthrough")
    p.add_argument("--config", default=os.path.join(HERE, "netbird.yaml"),
                   help="path to netbird.yaml")
    p.add_argument("--timeout-scale", type=float, default=1.0,
                   help="multiply every timeout, for a slow day")
    p.add_argument("--only", help="comma-separated checks to run")
    p.add_argument("--skip", help="comma-separated checks to skip")
    p.add_argument("--strict", action="store_true",
                   help="treat warnings as failures")
    p.add_argument("--show-onboarding", action="store_true")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    ctx = Ctx(cfg, args)

    # validate/status read the rendered config for stunPorts if it exists.
    path = os.path.join(HERE, "config.yaml")
    if os.path.exists(path):
        try:
            with open(path) as fh:
                ctx.rendered = yaml.safe_load(fh)
        except Exception:
            pass

    if args.command == "compose":
        return cmd_compose(ctx, args.extra)
    if args.command == "config":
        return cmd_config(ctx)
    if args.command == "status":
        return cmd_status(ctx)
    if args.command == "validate":
        return cmd_validate(ctx)
    return cmd_up(ctx, update=(args.command == "update"))


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(1)
