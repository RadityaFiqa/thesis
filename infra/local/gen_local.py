"""Generate configuration for the LOCAL TEST on Docker Desktop.

Runs inside a throwaway python container (see run-local.ps1) with the deploy
folder mounted at /work. Creates, only if missing:
  nextcloud/.env.local, siem/.env.local          (random secrets, localhost names)
  siem/config/wazuh_cluster/authd.pass
  siem/config/wazuh_dashboard/wazuh.yml
  siem/config/wazuh_indexer/internal_users.yml
Never overwrites existing files.
"""
import os
import re
import secrets
import string

import bcrypt

W = "/work"
ALNUM = string.ascii_letters + string.digits


def pw(n=32):
    return "".join(secrets.choice(ALNUM) for _ in range(n))


def api_pw():
    core = [secrets.choice(string.ascii_uppercase), secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits), ".", "-"] + [secrets.choice(ALNUM) for _ in range(19)]
    secrets.SystemRandom().shuffle(core)
    return "".join(core)


def bhash(p):
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt(12)).decode().replace("$2b$", "$2y$", 1)


def read_env(path):
    out = {}
    for line in open(path, encoding="utf-8"):
        m = re.match(r"^([A-Z_]+)=(.*)$", line.rstrip("\r\n"))
        if m:
            out[m.group(1)] = m.group(2)
    return out


def make_env(project, overrides):
    dst = f"{W}/{project}/.env.local"
    if os.path.exists(dst):
        print(f"  keep {project}/.env.local")
        return read_env(dst)
    lines = []
    for line in open(f"{W}/{project}/.env.example", encoding="utf-8"):
        line = line.rstrip("\r\n")
        m = re.match(r"^([A-Z_]+)=(.*)$", line)
        if m:
            k, v = m.groups()
            if k in overrides:
                v = overrides[k]
            elif v == "CHANGE_ME":
                v = api_pw() if k == "API_PASSWORD" else pw()
            line = f"{k}={v}"
        lines.append(line)
    open(dst, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print(f"  created {project}/.env.local")
    return read_env(dst)


siem = make_env("siem", {"HOST_BIND_IP": "127.0.0.1"})
nc = make_env("nextcloud", {
    "NEXTCLOUD_DOMAIN": "nextcloud.localhost",
    "WAZUH_DOMAIN": "wazuh.localhost",
    "CADDY_TLS": "internal",
    "HTTP_PORT": "8080",
    "HTTPS_PORT": "8443",
    "PUBLIC_PORT_SUFFIX": ":8443",
    "WAZUH_DASHBOARD_UPSTREAM": "host.docker.internal:" + read_env(f"{W}/siem/.env.example")["DASHBOARD_PORT"],
})

authd = f"{W}/siem/config/wazuh_cluster/authd.pass"
if not os.path.exists(authd):
    open(authd, "w", newline="\n").write(nc["WAZUH_REGISTRATION_PASSWORD"] + "\n")
    print("  created authd.pass")
elif open(authd).read().strip() != nc["WAZUH_REGISTRATION_PASSWORD"]:
    raise SystemExit("authd.pass differs from WAZUH_REGISTRATION_PASSWORD in nextcloud/.env.local")

wyml = f"{W}/siem/config/wazuh_dashboard/wazuh.yml"
if not os.path.exists(wyml):
    s = open(wyml + ".template").read().replace("__API_PASSWORD__", siem["API_PASSWORD"])
    open(wyml, "w", newline="\n").write(s)
    print("  created wazuh.yml")

users = f"{W}/siem/config/wazuh_indexer/internal_users.yml"
if not os.path.exists(users):
    s = open(users + ".template").read()
    s = s.replace("__ADMIN_HASH__", bhash(siem["INDEXER_PASSWORD"]))
    s = s.replace("__KIBANASERVER_HASH__", bhash(siem["DASHBOARD_PASSWORD"]))
    while "__RANDOM_HASH__" in s:
        s = s.replace("__RANDOM_HASH__", bhash(secrets.token_urlsafe(32)), 1)
    open(users, "w", newline="\n").write(s)
    print("  created internal_users.yml")

for f in (users, wyml):
    os.chmod(f, 0o644)
print("  config ready")
