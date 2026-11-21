"""Backend runner for Stoat Server TUI (local or SSH with ControlMaster)."""

from __future__ import annotations

import json
import os
import re
import secrets
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CONFIG_PATH = Path.home() / ".config" / "ss-tui" / "config.json"


def load_saved_config() -> dict[str, Any]:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text())
    except Exception:
        pass
    return {}


@dataclass
class StoatBackend:
    host: str = ""
    stoat_dir: str = ""
    local_mode: bool = False

    def __post_init__(self) -> None:
        saved = load_saved_config()
        if not self.host:
            self.host = os.environ.get("STOAT_SSH_HOST") or saved.get("host") or ""
        if not self.stoat_dir:
            self.stoat_dir = (
                os.environ.get("STOAT_DIR")
                or saved.get("stoat_dir")
                or str(Path.home() / "stoat")
            )
        if os.environ.get("STOAT_LOCAL") == "1" or saved.get("local"):
            self.local_mode = True
        elif not self.host or Path(self.stoat_dir, "compose.yml").exists():
            self.local_mode = True

    @property
    def target_label(self) -> str:
        return "local" if self.local_mode else self.host

    def _run(self, script: str, timeout: int = 25) -> tuple[int, str, str]:
        if self.local_mode:
            cmd = ["bash", "-s"]
        else:
            ctl_path = f"/tmp/ss-tui-ssh-{self.host.replace('/', '_')}"
            cmd = [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=6",
                "-o", "ControlMaster=auto",
                "-o", f"ControlPath={ctl_path}",
                "-o", "ControlPersist=120",
                "-T",
                self.host,
                "bash -s",
            ]
        try:
            proc = subprocess.run(
                cmd,
                input=script,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return 124, "", f"Command timed out after {timeout}s"
        except Exception as exc:
            return 1, "", str(exc)

    def _mongosh(self, js: str, timeout: int = 15) -> tuple[int, str, str]:
        script = f"""
docker exec -i stoat-database-1 mongosh revolt --quiet --file /dev/stdin <<'MONGO_EOF'
{js}
MONGO_EOF
"""
        return self._run(script, timeout=timeout)

    # ------------------------------------------------------------------
    # Dashboard / Overview
    # ------------------------------------------------------------------
    def fetch_overview(self) -> dict[str, Any]:
        script = f"""
cd {shlex.quote(self.stoat_dir)} || exit 1
echo "===PS==="
docker compose ps --format json 2>/dev/null || true
echo "===API==="
curl -s -m 4 http://127.0.0.1:8880/api/ 2>/dev/null || echo "{{}}"
echo ""
echo "===DISK==="
df -h {shlex.quote(self.stoat_dir)} | tail -n 1
echo "===MEM==="
free -h | awk '/^Mem:/ {{print $3 " / " $2 " (avail " $7 ")"}}'
echo "===DB==="
docker exec stoat-database-1 mongosh revolt --quiet --eval '
  print(JSON.stringify({{
    accounts: db.accounts.countDocuments(),
    users: db.users.countDocuments(),
    sessions: db.sessions.countDocuments(),
    channels: db.channels.countDocuments(),
    messages: db.messages.countDocuments(),
    servers: db.servers.countDocuments()
  }}));
' 2>/dev/null || echo "{{}}"
echo "===FUNNEL==="
tailscale funnel status 2>/dev/null || echo "Unavailable"
"""
        rc, out, err = self._run(script, timeout=20)
        if rc != 0 and not out:
            raise RuntimeError(err.strip() or f"Failed to reach {self.target_label}")

        sections: dict[str, str] = {}
        current = None
        buf: list[str] = []
        for line in out.splitlines():
            if line.startswith("===") and line.endswith("==="):
                if current is not None:
                    sections[current] = "\n".join(buf).strip()
                current = line.strip("=")
                buf = []
            else:
                buf.append(line)
        if current is not None:
            sections[current] = "\n".join(buf).strip()

        services: list[dict[str, Any]] = []
        for line in sections.get("PS", "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                services.append(json.loads(line))
            except json.JSONDecodeError:
                pass

        try:
            api_info = json.loads(sections.get("API", "{}") or "{}")
        except json.JSONDecodeError:
            api_info = {}

        try:
            db_stats = json.loads(sections.get("DB", "{}") or "{}")
        except json.JSONDecodeError:
            db_stats = {}

        disk_parts = sections.get("DISK", "").split()
        disk_str = (
            f"{disk_parts[2]} / {disk_parts[1]} ({disk_parts[4]} used, {disk_parts[3]} free)"
            if len(disk_parts) >= 5
            else sections.get("DISK", "—")
        )

        return {
            "services": services,
            "api": api_info,
            "db": db_stats,
            "disk": disk_str,
            "mem": sections.get("MEM", "—"),
            "funnel": sections.get("FUNNEL", "—"),
        }

    # ------------------------------------------------------------------
    # Docker Services
    # ------------------------------------------------------------------
    def service_action(self, service: str, action: str) -> str:
        svc = shlex.quote(service) if service else ""
        if action == "restart":
            cmd = f"docker compose restart {svc}"
        elif action == "start":
            cmd = f"docker compose start {svc}"
        elif action == "stop":
            cmd = f"docker compose stop {svc}"
        elif action == "recreate":
            cmd = f"docker compose up -d --force-recreate {svc}"
        elif action == "restart_all":
            cmd = "docker compose restart"
        else:
            raise ValueError(f"Unknown action: {action}")

        rc, out, err = self._run(f"cd {shlex.quote(self.stoat_dir)} && {cmd}", timeout=60)
        if rc != 0:
            raise RuntimeError((err or out).strip() or f"{cmd} failed (exit {rc})")
        return (out or err).strip() or "OK"

    def fetch_logs(self, service: str, lines: int = 120, hide_otel: bool = True) -> str:
        svc = shlex.quote(service)
        cmd = f"cd {shlex.quote(self.stoat_dir)} && docker compose logs --tail {int(lines)} --no-color {svc} 2>&1"
        rc, out, err = self._run(cmd, timeout=15)
        if rc != 0 and not out:
            raise RuntimeError(err.strip() or f"Failed to fetch logs for {service}")
        if hide_otel:
            filtered = [
                ln for ln in out.splitlines()
                if "OpenTelemetry" not in ln and "opentelemetry" not in ln
            ]
            return "\n".join(filtered)
        return out

    # ------------------------------------------------------------------
    # Users & Accounts (MongoDB + Authifier)
    # ------------------------------------------------------------------
    def fetch_users(self) -> list[dict[str, Any]]:
        js = """
const accounts = db.accounts.find({}).toArray();
const usersById = {};
db.users.find({}).toArray().forEach(u => { usersById[u._id] = u; });
const sessCounts = {};
db.sessions.aggregate([{ $group: { _id: "$user_id", n: { $sum: 1 } } }]).toArray().forEach(s => {
  sessCounts[s._id] = s.n;
});
const msgCounts = {};
db.messages.aggregate([{ $group: { _id: "$author", n: { $sum: 1 } } }]).toArray().forEach(m => {
  msgCounts[m._id] = m.n;
});
const out = accounts.map(a => {
  const u = usersById[a._id] || {};
  return {
    id: a._id,
    email: a.email || "",
    username: u.username || "(no profile)",
    discriminator: u.discriminator || "",
    disabled: !!a.disabled,
    locked: !!a.lockout,
    sessions: sessCounts[a._id] || 0,
    messages: msgCounts[a._id] || 0,
    friends: Array.isArray(u.relations) ? u.relations.filter(r => r.status === "Friend").length : 0
  };
});
print(JSON.stringify(out));
"""
        rc, out, err = self._mongosh(js)
        if rc != 0:
            raise RuntimeError(err.strip() or "Failed to query MongoDB")
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("["):
                return json.loads(line)
        return []

    def reset_password(self, user_id: str, email: str, new_password: str | None = None) -> str:
        pw = new_password or f"Stoat{secrets.token_hex(4).capitalize()}!"
        tmp_email = f"tmpreset_{secrets.token_hex(4)}@stoat.lan"
        payload_create = json.dumps({"email": tmp_email, "password": pw})
        payload_login = json.dumps({"email": email, "password": pw, "friendly_name": "ss-tui-verify"})

        script = f"""
set -e
CODE=$(curl -s -o /dev/null -w "%{{http_code}}" -X POST "http://127.0.0.1:8880/api/auth/account/create" \
  -H "Content-Type: application/json" \
  -d {shlex.quote(payload_create)})
if [ "$CODE" != "204" ] && [ "$CODE" != "200" ]; then
  echo "ERROR: create temp account failed with HTTP $CODE" >&2
  exit 1
fi

docker exec -i stoat-database-1 mongosh revolt --quiet <<'MONGO_EOF'
const tmp = db.accounts.findOne({{ email: {json.dumps(tmp_email)} }});
if (!tmp || !tmp.password) {{
  print("ERROR: temp account hash missing");
  quit(1);
}}
db.accounts.updateOne(
  {{ _id: {json.dumps(user_id)} }},
  {{ $set: {{ password: tmp.password, password_reset: null, lockout: null, disabled: false }} }}
);
db.accounts.deleteOne({{ _id: tmp._id }});
MONGO_EOF

LOGIN_RESP=$(curl -s -X POST "http://127.0.0.1:8880/api/auth/session/login" \
  -H "Content-Type: application/json" \
  -d {shlex.quote(payload_login)})
RESULT=$(echo "$LOGIN_RESP" | jq -r '.result // empty')
SESS_ID=$(echo "$LOGIN_RESP" | jq -r '._id // empty')
if [ -n "$SESS_ID" ]; then
  docker exec stoat-database-1 mongosh revolt --quiet --eval "db.sessions.deleteOne({{ _id: \\"$SESS_ID\\" }})" >/dev/null
fi
if [ "$RESULT" != "Success" ]; then
  echo "ERROR: verification login returned $LOGIN_RESP" >&2
  exit 1
fi
echo "OK"
"""
        rc, out, err = self._run(script, timeout=25)
        if rc != 0:
            raise RuntimeError((err or out).strip() or "Password reset failed")
        return pw

    def unlock_account(self, user_id: str) -> None:
        js = f"""
db.accounts.updateOne(
  {{ _id: {json.dumps(user_id)} }},
  {{ $set: {{ lockout: null, disabled: false }} }}
);
"""
        rc, _, err = self._mongosh(js)
        if rc != 0:
            raise RuntimeError(err.strip() or "Failed to unlock account")

    def toggle_disable_account(self, user_id: str, disabled: bool) -> None:
        js = f"""
db.accounts.updateOne(
  {{ _id: {json.dumps(user_id)} }},
  {{ $set: {{ disabled: {"true" if disabled else "false"} }} }}
);
"""
        rc, _, err = self._mongosh(js)
        if rc != 0:
            raise RuntimeError(err.strip() or "Failed to update disabled status")

    def revoke_sessions(self, user_id: str) -> int:
        js = f"""
const res = db.sessions.deleteMany({{ user_id: {json.dumps(user_id)} }});
print(res.deletedCount);
"""
        rc, out, err = self._mongosh(js)
        if rc != 0:
            raise RuntimeError(err.strip() or "Failed to revoke sessions")
        try:
            return int(out.strip().splitlines()[-1])
        except Exception:
            return 0

    def delete_account(self, user_id: str) -> None:
        js = f"""
const id = {json.dumps(user_id)};
db.accounts.deleteOne({{ _id: id }});
db.users.deleteOne({{ _id: id }});
db.sessions.deleteMany({{ user_id: id }});
db.channels.deleteMany({{ user: id }});
db.user_settings.deleteMany({{ _id: id }});
db.users.updateMany({{}}, {{ $pull: {{ relations: {{ _id: id }} }} }});
"""
        rc, _, err = self._mongosh(js)
        if rc != 0:
            raise RuntimeError(err.strip() or "Failed to delete account")

    def auto_mesh_friends(self) -> int:
        js = """
const users = db.users.find({}, { _id: 1 }).toArray().map(u => u._id);
users.forEach(u1 => {
  const friendList = users.filter(u2 => u2 !== u1).map(u2 => ({ _id: u2, status: "Friend" }));
  db.users.updateOne({ _id: u1 }, { $set: { relations: friendList } });
});
print(users.length);
"""
        rc, out, err = self._mongosh(js)
        if rc != 0:
            raise RuntimeError(err.strip() or "Failed to auto-mesh friends")
        try:
            return int(out.strip().splitlines()[-1])
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Config & Limits (Revolt.toml, .env.web, inject.js)
    # ------------------------------------------------------------------
    def fetch_config(self) -> dict[str, Any]:
        script = f"""
cd {shlex.quote(self.stoat_dir)} || exit 1
echo "===TOML==="
cat Revolt.toml
echo "===ENVWEB==="
cat .env.web 2>/dev/null || true
echo "===API==="
curl -s -m 4 http://127.0.0.1:8880/api/ 2>/dev/null || echo "{{}}"
"""
        rc, out, err = self._run(script, timeout=15)
        if rc != 0 and not out:
            raise RuntimeError(err.strip() or "Failed to read config")

        sections: dict[str, str] = {}
        current = None
        buf: list[str] = []
        for line in out.splitlines():
            if line.startswith("===") and line.endswith("==="):
                if current is not None:
                    sections[current] = "\n".join(buf).strip()
                current = line.strip("=")
                buf = []
            else:
                buf.append(line)
        if current is not None:
            sections[current] = "\n".join(buf).strip()

        toml_text = sections.get("TOML", "")
        try:
            api_info = json.loads(sections.get("API", "{}") or "{}")
        except json.JSONDecodeError:
            api_info = {}

        limits = api_info.get("features", {}).get("limits", {})
        default_up = limits.get("default", {}).get("file_upload_size_limits", {})
        global_lim = limits.get("global", {})
        default_lim = limits.get("default", {})

        rows = [
            ("body_limit_size", "Global Body Limit", global_lim.get("body_limit_size", "—"), "bytes"),
            ("attachments", "Attachments Max Size", default_up.get("attachments", "—"), "bytes"),
            ("avatars", "Avatars Max Size", default_up.get("avatars", "—"), "bytes"),
            ("banners", "Banners Max Size", default_up.get("banners", "—"), "bytes"),
            ("backgrounds", "Backgrounds Max Size", default_up.get("backgrounds", "—"), "bytes"),
            ("icons", "Icons Max Size", default_up.get("icons", "—"), "bytes"),
            ("emojis", "Emojis Max Size", default_up.get("emojis", "—"), "bytes"),
            ("message_length", "Max Message Length", default_lim.get("message_length", "—"), "chars"),
            ("message_attachments", "Max Attachments / Msg", default_lim.get("message_attachments", "—"), "files"),
        ]

        return {
            "rows": rows,
            "toml": toml_text,
            "env_web": sections.get("ENVWEB", ""),
            "api": api_info,
        }

    def update_limit(self, key: str, value_int: int) -> None:
        if not re.fullmatch(r"[a-z_]+", key):
            raise ValueError(f"Invalid key: {key}")
        val_str = str(int(value_int))
        py_patch = f"""
import re
from pathlib import Path

p = Path("Revolt.toml")
text = p.read_text()
pattern = re.compile(r'^({key}\\s*=\\s*)[0-9_]+', re.MULTILINE)
new_text, count = pattern.subn(r'\\g<1>{val_str}', text)
if count == 0:
    raise SystemExit("Key {key} not found in Revolt.toml")
p.write_text(new_text)

if {json.dumps(key)} == "attachments":
    envp = Path(".env.web")
    if envp.exists():
        et = envp.read_text()
        et = re.sub(r'^VITE_CFG_MAX_FILE_SIZE=.*$', 'VITE_CFG_MAX_FILE_SIZE={val_str}', et, flags=re.MULTILINE)
        envp.write_text(et)
    injp = Path("inject.js")
    if injp.exists():
        it = injp.read_text()
        it = re.sub(r'const UPLOAD_SIZE_LIMIT = "[^"]+";', 'const UPLOAD_SIZE_LIMIT = "{val_str}";', it)
        injp.write_text(it)
"""
        script = f"""
set -e
cd {shlex.quote(self.stoat_dir)}
python3 - <<'PY_EOF'
{py_patch}
PY_EOF
docker compose up -d --force-recreate autumn api web >/dev/null 2>&1
"""
        rc, out, err = self._run(script, timeout=60)
        if rc != 0:
            raise RuntimeError((err or out).strip() or "Failed to update limit")

    def rerun_inject(self) -> str:
        script = f"""
cd {shlex.quote(self.stoat_dir)} && docker exec stoat-web-1 node /app/inject.js && docker compose restart caddy
"""
        rc, out, err = self._run(script, timeout=30)
        if rc != 0:
            raise RuntimeError((err or out).strip() or "Failed to run inject.js")
        return (out or "Injection complete.").strip()
