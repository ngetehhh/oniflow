import json
import http.cookiejar
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import activation_server


class ActivationServerTests(unittest.TestCase):
    def request(self, endpoint, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{endpoint}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_register_activate_status_and_consume(self):
        with tempfile.TemporaryDirectory() as directory:
            original = activation_server.DATABASE
            activation_server.DATABASE = Path(directory) / "activation.db"
            connection = activation_server.connect()
            connection.execute(
                "INSERT INTO codes(code, days, max_devices, created_at) VALUES (?, ?, ?, ?)",
                ("FRIEND-30D", 30, 1, activation_server.now().isoformat()),
            )
            connection.commit()
            connection.close()
            server = activation_server.ThreadingHTTPServer(("127.0.0.1", 0), activation_server.Handler)
            self.port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                registered = self.request("/register", {"device_id": "device-a", "device_name": "Test PC"})
                self.assertTrue(registered["ok"])
                self.assertEqual(registered["clips_available"], 15)
                activated = self.request(
                    "/activate", {"code": "FRIEND-30D", "device_id": "device-a", "device_name": "Test PC"}
                )
                self.assertTrue(activated["pro"])
                status = self.request("/status", {"device_id": "device-a", "token": activated["token"]})
                self.assertTrue(status["pro"])
                consumed = self.request("/consume", {"device_id": "device-a", "token": activated["token"]})
                self.assertEqual(consumed["clips_used"], 0)
            finally:
                server.shutdown()
                server.server_close()
                activation_server.DATABASE = original

    def test_root_redirects_to_admin_login(self):
        with tempfile.TemporaryDirectory() as directory:
            original = activation_server.DATABASE
            original_password = activation_server.ADMIN_PASSWORD
            activation_server.DATABASE = Path(directory) / "activation.db"
            activation_server.ADMIN_PASSWORD = "test-password"
            server = activation_server.ThreadingHTTPServer(("127.0.0.1", 0), activation_server.Handler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as response:
                    body = response.read().decode("utf-8")
                self.assertIn("Sign in to manage access codes and devices.", body)
            finally:
                server.shutdown()
                server.server_close()
                activation_server.DATABASE = original
                activation_server.ADMIN_PASSWORD = original_password

    def test_admin_dashboard_login_and_create_code(self):
        with tempfile.TemporaryDirectory() as directory:
            original = activation_server.DATABASE
            original_password = activation_server.ADMIN_PASSWORD
            activation_server.DATABASE = Path(directory) / "activation.db"
            activation_server.ADMIN_PASSWORD = "test-password"
            activation_server.ADMIN_SESSIONS.clear()
            activation_server.connect().close()
            server = activation_server.ThreadingHTTPServer(("127.0.0.1", 0), activation_server.Handler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            try:
                login = urllib.request.Request(
                    f"http://127.0.0.1:{port}/admin/login",
                    data=urllib.parse.urlencode({"password": "test-password"}).encode(),
                    method="POST",
                )
                dashboard = opener.open(login, timeout=3).read().decode()
                self.assertIn("Create Access Code", dashboard)
                csrf = activation_server.ADMIN_SESSIONS[next(iter(activation_server.ADMIN_SESSIONS))]
                create = urllib.request.Request(
                    f"http://127.0.0.1:{port}/admin/codes/create",
                    data=urllib.parse.urlencode(
                        {"csrf": csrf, "code": "DASHBOARD-30D", "days": "30", "devices": "2"}
                    ).encode(),
                    method="POST",
                )
                result = opener.open(create, timeout=3).read().decode()
                self.assertIn("DASHBOARD-30D", result)
            finally:
                server.shutdown()
                server.server_close()
                activation_server.DATABASE = original
                activation_server.ADMIN_PASSWORD = original_password
                activation_server.ADMIN_SESSIONS.clear()


if __name__ == "__main__":
    unittest.main()
