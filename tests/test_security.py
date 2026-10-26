"""Server hygiene over a socket, the offline refusal of private hosts by the snapshot fetch, and the absence of SQL."""
from __future__ import annotations

import http.client
import json
import logging
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_site import build  # noqa: E402
from listing import config  # noqa: E402
import server  # noqa: E402
import snapshot as snap  # noqa: E402


class ServerHygieneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dist = Path(cls.tmp.name) / "dist"
        build(cls.dist, config.load(ROOT))
        cls.httpd = server.serve(server.Site(cls.dist, [], 1000), "127.0.0.1", 0)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.records = []
        handler = logging.Handler()
        handler.emit = lambda record: cls.records.append(record.getMessage())
        logging.getLogger("fdo-knowledge-dashboard").addHandler(handler)
        logging.getLogger("fdo-knowledge-dashboard").setLevel(logging.INFO)
        cls.handler = handler

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        logging.getLogger("fdo-knowledge-dashboard").removeHandler(cls.handler)
        cls.tmp.cleanup()

    def get(self, path, method="GET", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=30)
        conn.request(method, path, headers=headers or {})
        res = conn.getresponse()
        body = res.read()
        conn.close()
        return res, body

    def test_no_directory_listing_and_no_traversal(self):
        for path in ("/data/", "/data/records/", "/assets/", "/assets/fonts/"):
            self.assertEqual(self.get(path)[0].status, 404, path)
        self.assertEqual(self.get("/%2e%2e/%2e%2e/etc/passwd")[0].status, 404)
        self.assertEqual(self.get("/index.html")[0].status, 200)

    def test_security_headers_on_every_response(self):
        for path in ("/", "/data/catalog.json", "/api/v1/health", "/nothing"):
            res, _ = self.get(path)
            self.assertEqual(res.getheader("X-Content-Type-Options"), "nosniff", path)
            self.assertEqual(res.getheader("X-Frame-Options"), "DENY", path)
            self.assertIn("frame-ancestors", res.getheader("Content-Security-Policy") or "", path)
            self.assertTrue(res.getheader("Referrer-Policy"), path)

    def test_methods_target_length_and_log_privacy(self):
        res, body = self.get("/api/v1/search", method="POST")
        self.assertEqual((res.status, res.getheader("Allow")), (405, "GET, OPTIONS"))
        res, body = self.get("/api/v1/search?q=" + "a" * 9000)
        self.assertEqual((res.status, json.loads(body)["error"]["code"]), (414, "uri_too_long"))
        res, body = self.get("/api/v1/search?f.type=%3Cscript%3E")
        self.assertEqual(res.status, 200)
        res, body = self.get("/api/v1/search?f.nope=secretword")
        self.assertEqual(res.status, 400)
        self.assertNotIn("secretword", body.decode())
        self.get("/api/v1/search?q=personalquestion")
        self.assertTrue(any("/api/v1/search" in line for line in self.records))
        self.assertFalse(any("personalquestion" in line for line in self.records))


class FetchPolicyTest(unittest.TestCase):
    def test_private_and_unsupported_targets_are_refused_before_any_connection(self):
        for url in ("http://127.0.0.1:1/x", "http://localhost/x", "http://169.254.169.254/latest/meta-data", "http://10.0.0.1/x", "http://[::1]/x"):
            with self.assertRaises(snap.AccessError, msg=url) as ctx:
                snap.fetch(url, 0.5)
            self.assertEqual(ctx.exception.code, "request.bad_pid", url)
        for url in ("file:///etc/passwd", "ftp://example.org/x", "javascript:alert(1)"):
            with self.assertRaises(snap.AccessError, msg=url):
                snap.fetch(url, 0.5)

    def test_no_sql_at_runtime(self):
        for path in list((ROOT / "listing").glob("*.py")) + list((ROOT / "scripts").glob("*.py")) + [ROOT / "server.py"]:
            self.assertIsNone(re.search(r"\bsqlite3\b|\bsqlalchemy\b|SELECT .* FROM", path.read_text(encoding="utf-8")), path.name)


if __name__ == "__main__":
    unittest.main()
