#!/usr/bin/env python3
"""Small self-hosted activation server for Oniflow."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


FREE_DAILY_CLIP_LIMIT = 15
DATABASE = Path(os.environ.get("ONIFLOW_ACTIVATION_DB", Path(__file__).with_name("activation.db")))
ADMIN_PASSWORD = os.environ.get("ONIFLOW_ADMIN_PASSWORD", "")
ADMIN_SESSIONS: dict[str, str] = {}


def format_date(value: str | None) -> str:
    if not value:
        return "Never"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value


def page(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} | Oniflow Admin</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#090d18;color:#e2e8f0;font:14px Segoe UI,sans-serif}}
a{{color:#38bdf8;text-decoration:none}} header{{height:70px;background:#101728;border-bottom:1px solid #263552;display:flex;align-items:center;padding:0 28px;gap:18px}}
header strong{{font-size:22px}} header span{{color:#38bdf8;font-weight:700}} header a{{margin-left:auto;color:#94a3b8}}
main{{max-width:1380px;margin:24px auto;padding:0 20px}} .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}
.card{{background:#101728;border:1px solid #263552;border-radius:12px;padding:18px;margin-bottom:16px}} .metric b{{display:block;font-size:28px;color:#38bdf8;margin-top:5px}}
h1,h2{{margin:0 0 14px}} h2{{font-size:17px}} .muted{{color:#94a3b8}} .ok{{color:#22c55e}} .bad{{color:#ef4444}} .warn{{color:#f59e0b}}
table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;padding:10px;border-bottom:1px solid #263552;vertical-align:middle}} th{{color:#94a3b8;font-size:12px;text-transform:uppercase}}
input{{background:#0b1120;color:#e2e8f0;border:1px solid #334155;border-radius:7px;padding:9px;width:100%}} label{{display:block;color:#94a3b8;margin-bottom:5px}}
button{{border:0;border-radius:7px;background:#287bb5;color:white;padding:9px 14px;cursor:pointer}} button.danger{{background:#991b1b}} button.secondary{{background:#334155}}
.form-grid{{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:10px;align-items:end}} form.inline{{display:inline}} .actions{{display:flex;gap:6px;flex-wrap:wrap}}
.login{{max-width:430px;margin:100px auto}} .flash{{padding:12px;border:1px solid #334155;background:#111a2e;border-radius:8px;margin-bottom:14px}}
@media(max-width:900px){{.grid{{grid-template-columns:repeat(2,1fr)}}.form-grid{{grid-template-columns:1fr}}table{{font-size:12px}}}}
</style></head><body>{content}</body></html>"""


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS codes (
            code TEXT PRIMARY KEY,
            days INTEGER NOT NULL,
            max_devices INTEGER NOT NULL DEFAULT 1,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            device_name TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            pro_until TEXT,
            usage_date TEXT NOT NULL,
            clips_used INTEGER NOT NULL DEFAULT 0,
            last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS activations (
            code TEXT NOT NULL,
            device_id TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            PRIMARY KEY (code, device_id)
        );
        """
    )
    return connection


def now() -> datetime:
    return datetime.now(timezone.utc)


def device_status(connection: sqlite3.Connection, device_id: str, token: str) -> dict[str, object]:
    row = connection.execute(
        "SELECT * FROM devices WHERE device_id = ? AND token = ?", (device_id, token)
    ).fetchone()
    if not row:
        raise ValueError("Device access token is invalid.")
    today = date.today().isoformat()
    clips_used = int(row["clips_used"]) if row["usage_date"] == today else 0
    if row["usage_date"] != today:
        connection.execute(
            "UPDATE devices SET usage_date = ?, clips_used = 0 WHERE device_id = ?", (today, device_id)
        )
    expiry = datetime.fromisoformat(row["pro_until"]) if row["pro_until"] else None
    pro = bool(expiry and expiry > now())
    connection.execute("UPDATE devices SET last_seen = ? WHERE device_id = ?", (now().isoformat(), device_id))
    connection.commit()
    return {
        "pro": pro,
        "pro_until": expiry.isoformat() if expiry else "",
        "clips_used": clips_used,
        "clips_available": FREE_DAILY_CLIP_LIMIT if pro else max(0, FREE_DAILY_CLIP_LIMIT - clips_used),
        "daily_limit": FREE_DAILY_CLIP_LIMIT,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "OniflowActivation/1.0"

    def redirect(self, location: str, cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        parsed = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        return {key: values[0] for key, values in parsed.items()}

    def session(self) -> tuple[str, str] | None:
        cookies = self.headers.get("Cookie", "")
        values = {}
        for part in cookies.split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                values[key] = value
        token = values.get("oniflow_admin", "")
        csrf = ADMIN_SESSIONS.get(token)
        return (token, csrf) if csrf else None

    def require_admin(self) -> tuple[str, str] | None:
        session = self.session()
        if not session:
            self.redirect("/admin/login")
            return None
        return session

    @staticmethod
    def admin_form(action: str, csrf: str, label: str, css: str = "secondary", **fields: str) -> str:
        hidden = [f'<input type="hidden" name="csrf" value="{html.escape(csrf)}">']
        hidden.extend(
            f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">'
            for key, value in fields.items()
        )
        return (
            f'<form class="inline" method="post" action="{action}">{"".join(hidden)}'
            f'<button class="{css}" type="submit">{html.escape(label)}</button></form>'
        )

    def admin_login_page(self, error: str = "") -> None:
        flash = f'<div class="flash bad">{html.escape(error)}</div>' if error else ""
        self.send_html(
            200,
            page(
                "Login",
                f"""<main class="login"><section class="card"><h1>Oniflow Admin</h1>
<p class="muted">Sign in to manage access codes and devices.</p>{flash}
<form method="post" action="/admin/login"><label>Admin Password</label>
<input type="password" name="password" autofocus required><br><br>
<button type="submit">Sign In</button></form></section></main>""",
            ),
        )

    def admin_dashboard(self, csrf: str, message: str = "") -> None:
        connection = connect()
        stats = {
            "codes": connection.execute("SELECT COUNT(*) FROM codes").fetchone()[0],
            "enabled": connection.execute("SELECT COUNT(*) FROM codes WHERE enabled = 1").fetchone()[0],
            "devices": connection.execute("SELECT COUNT(*) FROM devices").fetchone()[0],
            "pro": connection.execute(
                "SELECT COUNT(*) FROM devices WHERE pro_until IS NOT NULL AND pro_until > ?", (now().isoformat(),)
            ).fetchone()[0],
        }
        codes = connection.execute(
            """
            SELECT c.*, COUNT(a.device_id) AS used_devices
            FROM codes c LEFT JOIN activations a ON a.code = c.code
            GROUP BY c.code ORDER BY c.created_at DESC
            """
        ).fetchall()
        devices = connection.execute(
            """
            SELECT d.*, COUNT(a.code) AS activation_count
            FROM devices d LEFT JOIN activations a ON a.device_id = d.device_id
            GROUP BY d.device_id ORDER BY d.last_seen DESC
            """
        ).fetchall()
        activations = connection.execute(
            """
            SELECT a.code, d.device_name, a.activated_at
            FROM activations a JOIN devices d ON d.device_id = a.device_id
            ORDER BY a.activated_at DESC LIMIT 50
            """
        ).fetchall()
        connection.close()
        code_rows = []
        for row in codes:
            action = "disable" if row["enabled"] else "enable"
            code_rows.append(
                f"<tr><td><strong>{html.escape(row['code'])}</strong></td><td>{row['days']} days</td>"
                f"<td>{row['used_devices']} / {row['max_devices']}</td>"
                f"<td class=\"{'ok' if row['enabled'] else 'bad'}\">{'Enabled' if row['enabled'] else 'Disabled'}</td>"
                f"<td>{format_date(row['created_at'])}</td><td class=\"actions\">"
                f"{self.admin_form('/admin/codes/toggle', csrf, action.title(), code=row['code'], enabled=str(0 if row['enabled'] else 1))}"
                f"{self.admin_form('/admin/codes/delete', csrf, 'Delete', 'danger', code=row['code'])}</td></tr>"
            )
        device_rows = []
        for row in devices:
            expiry = datetime.fromisoformat(row["pro_until"]) if row["pro_until"] else None
            pro = bool(expiry and expiry > now())
            device_rows.append(
                f"<tr><td><strong>{html.escape(row['device_name'])}</strong><br><span class=\"muted\">{row['device_id'][:14]}...</span></td>"
                f"<td class=\"{'ok' if pro else 'muted'}\">{'Pro' if pro else 'Free'}</td><td>{format_date(row['pro_until'])}</td>"
                f"<td>{row['clips_used']} / {FREE_DAILY_CLIP_LIMIT}</td><td>{row['activation_count']}</td><td>{format_date(row['last_seen'])}</td>"
                f"<td class=\"actions\">{self.admin_form('/admin/devices/revoke', csrf, 'Revoke Pro', device_id=row['device_id'])}"
                f"{self.admin_form('/admin/devices/delete', csrf, 'Delete', 'danger', device_id=row['device_id'])}</td></tr>"
            )
        activation_rows = "".join(
            f"<tr><td>{html.escape(row['code'])}</td><td>{html.escape(row['device_name'])}</td><td>{format_date(row['activated_at'])}</td></tr>"
            for row in activations
        )
        flash = f'<div class="flash ok">{html.escape(message)}</div>' if message else ""
        content = f"""<header><strong>ONIFLOW</strong><span>ADMIN DASHBOARD</span><a href="/admin/logout">Sign Out</a></header>
<main>{flash}<section class="grid">
<div class="card metric">Total Codes<b>{stats['codes']}</b></div><div class="card metric">Enabled Codes<b>{stats['enabled']}</b></div>
<div class="card metric">Registered Devices<b>{stats['devices']}</b></div><div class="card metric">Active Pro Devices<b>{stats['pro']}</b></div>
</section><section class="card"><h2>Create Access Code</h2>
<form class="form-grid" method="post" action="/admin/codes/create"><input type="hidden" name="csrf" value="{csrf}">
<div><label>Custom Code, optional</label><input name="code" placeholder="ONIVEN-FRIEND-30D"></div>
<div><label>Pro Duration</label><input name="days" type="number" min="1" value="30" required></div>
<div><label>Device Limit</label><input name="devices" type="number" min="1" value="1" required></div><button type="submit">Create Code</button></form>
</section><section class="card"><h2>Access Codes</h2><table><thead><tr><th>Code</th><th>Duration</th><th>Devices</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead>
<tbody>{''.join(code_rows) or '<tr><td colspan="6" class="muted">No codes created.</td></tr>'}</tbody></table></section>
<section class="card"><h2>Registered Devices</h2><table><thead><tr><th>Device</th><th>Plan</th><th>Pro Until</th><th>Daily Clips</th><th>Codes</th><th>Last Seen</th><th>Actions</th></tr></thead>
<tbody>{''.join(device_rows) or '<tr><td colspan="7" class="muted">No registered devices.</td></tr>'}</tbody></table></section>
<section class="card"><h2>Recent Activations</h2><table><thead><tr><th>Code</th><th>Device</th><th>Activated</th></tr></thead>
<tbody>{activation_rows or '<tr><td colspan="3" class="muted">No activations.</td></tr>'}</tbody></table></section></main>"""
        self.send_html(200, page("Dashboard", content))

    def send_html(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        if self.path == "/":
            self.redirect("/admin")
        elif self.path == "/admin/login":
            self.admin_login_page()
        elif self.path == "/admin/logout":
            session = self.session()
            if session:
                ADMIN_SESSIONS.pop(session[0], None)
            self.redirect("/admin/login", "oniflow_admin=; HttpOnly; SameSite=Strict; Max-Age=0; Path=/")
        elif self.path.startswith("/admin"):
            session = self.require_admin()
            if session:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                self.admin_dashboard(session[1], query.get("message", [""])[0])
        elif self.path == "/health":
            self.send_json(200, {"ok": True, "service": "Oniflow Activation"})
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_json(404, {"ok": False, "error": "Not found."})

    def do_POST(self) -> None:
        if self.path.startswith("/admin/"):
            self.handle_admin_post()
            return
        try:
            payload = self.read_json()
            if self.path == "/register":
                result = self.register(payload)
            elif self.path == "/activate":
                result = self.activate(payload)
            elif self.path == "/status":
                result = self.status(payload)
            elif self.path == "/consume":
                result = self.consume(payload)
            else:
                self.send_json(404, {"ok": False, "error": "Not found."})
                return
            self.send_json(200, {"ok": True, **result})
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})
        except Exception:
            self.send_json(500, {"ok": False, "error": "Activation server error."})

    def handle_admin_post(self) -> None:
        form = self.read_form()
        if self.path == "/admin/login":
            if ADMIN_PASSWORD and hmac.compare_digest(form.get("password", ""), ADMIN_PASSWORD):
                token = secrets.token_urlsafe(32)
                ADMIN_SESSIONS[token] = secrets.token_urlsafe(24)
                self.redirect(
                    "/admin",
                    f"oniflow_admin={token}; HttpOnly; SameSite=Strict; Path=/",
                )
            else:
                self.admin_login_page("Incorrect admin password.")
            return
        session = self.require_admin()
        if not session:
            return
        if not hmac.compare_digest(form.get("csrf", ""), session[1]):
            self.send_html(403, page("Forbidden", "<main><section class='card'><h1>Invalid request.</h1></section></main>"))
            return
        try:
            connection = connect()
            message = "Dashboard updated."
            if self.path == "/admin/codes/create":
                code = form.get("code", "").strip().upper() or f"ONIFLOW-{secrets.token_hex(4).upper()}"
                days = max(1, int(form.get("days", "30")))
                devices = max(1, int(form.get("devices", "1")))
                connection.execute(
                    "INSERT INTO codes(code, days, max_devices, created_at) VALUES (?, ?, ?, ?)",
                    (code, days, devices, now().isoformat()),
                )
                message = f"Code {code} created."
            elif self.path == "/admin/codes/toggle":
                connection.execute(
                    "UPDATE codes SET enabled = ? WHERE code = ?",
                    (int(form["enabled"]), form["code"]),
                )
                message = f"Code {form['code']} updated."
            elif self.path == "/admin/codes/delete":
                connection.execute("DELETE FROM activations WHERE code = ?", (form["code"],))
                connection.execute("DELETE FROM codes WHERE code = ?", (form["code"],))
                message = f"Code {form['code']} deleted."
            elif self.path == "/admin/devices/revoke":
                connection.execute("UPDATE devices SET pro_until = NULL WHERE device_id = ?", (form["device_id"],))
                message = "Pro access revoked."
            elif self.path == "/admin/devices/delete":
                connection.execute("DELETE FROM activations WHERE device_id = ?", (form["device_id"],))
                connection.execute("DELETE FROM devices WHERE device_id = ?", (form["device_id"],))
                message = "Device deleted."
            else:
                connection.close()
                self.send_html(404, page("Not Found", "<main><section class='card'>Not found.</section></main>"))
                return
            connection.commit()
            connection.close()
            self.redirect(f"/admin?message={urllib.parse.quote(message)}")
        except (ValueError, KeyError, sqlite3.IntegrityError) as exc:
            self.admin_dashboard(session[1], f"Error: {exc}")

    def register(self, payload: dict[str, object]) -> dict[str, object]:
        device_id = str(payload["device_id"])
        device_name = str(payload.get("device_name", "Unknown device"))[:120]
        connection = connect()
        row = connection.execute("SELECT token FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        token = str(row["token"]) if row else secrets.token_urlsafe(32)
        connection.execute(
            """
            INSERT INTO devices(device_id, device_name, token, usage_date, clips_used, last_seen)
            VALUES (?, ?, ?, ?, 0, ?)
            ON CONFLICT(device_id) DO UPDATE SET device_name = excluded.device_name, last_seen = excluded.last_seen
            """,
            (device_id, device_name, token, date.today().isoformat(), now().isoformat()),
        )
        connection.commit()
        result = {"token": token, **device_status(connection, device_id, token)}
        connection.close()
        return result

    def activate(self, payload: dict[str, object]) -> dict[str, object]:
        code = str(payload["code"]).strip().upper()
        device_id = str(payload["device_id"])
        device_name = str(payload.get("device_name", "Unknown device"))[:120]
        connection = connect()
        code_row = connection.execute("SELECT * FROM codes WHERE code = ? AND enabled = 1", (code,)).fetchone()
        if not code_row:
            raise ValueError("The access code is invalid or disabled.")
        existing = connection.execute(
            "SELECT 1 FROM activations WHERE code = ? AND device_id = ?", (code, device_id)
        ).fetchone()
        used = connection.execute("SELECT COUNT(*) FROM activations WHERE code = ?", (code,)).fetchone()[0]
        if not existing and used >= int(code_row["max_devices"]):
            raise ValueError("This access code has reached its device limit.")
        row = connection.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        current_expiry = datetime.fromisoformat(row["pro_until"]) if row and row["pro_until"] else None
        start = current_expiry if current_expiry and current_expiry > now() else now()
        expiry = start + timedelta(days=int(code_row["days"]))
        token = str(row["token"]) if row else secrets.token_urlsafe(32)
        connection.execute(
            """
            INSERT INTO devices(device_id, device_name, token, pro_until, usage_date, clips_used, last_seen)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                device_name = excluded.device_name, token = excluded.token,
                pro_until = excluded.pro_until, last_seen = excluded.last_seen
            """,
            (device_id, device_name, token, expiry.isoformat(), date.today().isoformat(), now().isoformat()),
        )
        connection.execute(
            "INSERT OR IGNORE INTO activations(code, device_id, activated_at) VALUES (?, ?, ?)",
            (code, device_id, now().isoformat()),
        )
        connection.commit()
        result = {"token": token, **device_status(connection, device_id, token)}
        connection.close()
        return result

    def status(self, payload: dict[str, object]) -> dict[str, object]:
        connection = connect()
        result = device_status(connection, str(payload["device_id"]), str(payload["token"]))
        connection.close()
        return result

    def consume(self, payload: dict[str, object]) -> dict[str, object]:
        device_id = str(payload["device_id"])
        token = str(payload["token"])
        connection = connect()
        status = device_status(connection, device_id, token)
        if not status["pro"]:
            if int(status["clips_available"]) <= 0:
                raise ValueError("The daily free clip limit has been reached.")
            connection.execute(
                "UPDATE devices SET clips_used = clips_used + 1 WHERE device_id = ?", (device_id,)
            )
            connection.commit()
        result = device_status(connection, device_id, token)
        connection.close()
        return result

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Oniflow activation server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    if not ADMIN_PASSWORD:
        raise SystemExit(
            "ONIFLOW_ADMIN_PASSWORD is not set. Start the server with jalankan_server_aktivasi.ps1."
        )
    connect().close()
    print(f"Oniflow admin dashboard: http://{args.host}:{args.port}/admin")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
