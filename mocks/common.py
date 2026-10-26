"""Shared HTTP handling for the local mock services: CORS for listed origins, bounded JSON bodies, constant error messages."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_BODY = 64 * 1024
SECURITY = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class MockHandler(BaseHTTPRequestHandler):
    server_version = "fdo-knowledge-dashboard-mock"
    origins: frozenset = frozenset()
    service = "mock"
    timeout = 10                                              # seconds a connection may stay silent before it is closed
    default_request_version = "HTTP/1.0"                      # a refused request line still gets a status line

    def log_message(self, fmt, *args):                       # method, path without query, status; never the question
        path = urlsplit(getattr(self, "path", "") or "").path
        sys.stderr.write(f"{self.service} {getattr(self, 'command', '-')} {path} {args[1] if len(args) > 1 else ''}\n")

    def cors(self) -> dict:
        origin = self.headers.get("Origin")
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"} if origin and origin in self.origins else {}

    def reply(self, status: int, body: dict | str | bytes | None, content_type: str = "application/json; charset=utf-8") -> None:
        data = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode())
        self.send_response(status)
        for k, v in {**SECURITY, **self.cors(), "Content-Type": content_type, "Content-Length": str(len(data))}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):      # the client went away first
                pass

    def fail(self, status: int, code: str, message: str) -> None:
        self.reply(status, {"error": {"code": code, "message": message}})

    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        if not origin or origin not in self.origins:
            self.send_response(403); self.send_header("Content-Length", "0"); self.end_headers()
            return
        self.send_response(204)
        for k, v in {**self.cors(), "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type",
                     "Access-Control-Max-Age": "600", "Content-Length": "0"}.items():
            self.send_header(k, v)
        self.end_headers()

    def do_PUT(self):
        self.fail(405, "method_not_allowed", "only GET, POST and OPTIONS are accepted")

    do_DELETE = do_PATCH = do_PUT

    def json_body(self) -> dict | None:
        """The request body as a JSON object; None after an error reply."""
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            self.fail(415, "unsupported_media_type", "the body must be application/json")
            return None
        raw_length = self.headers.get("Content-Length") or "0"
        if not raw_length.isdigit():
            self.fail(400, "bad_request", "Content-Length must be a non-negative integer")
            return None
        length = int(raw_length)
        if length > MAX_BODY:
            self.fail(413, "too_large", f"the body must be at most {MAX_BODY} bytes")
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"null")
        except (ValueError, UnicodeDecodeError):
            self.fail(400, "bad_json", "the body is not valid JSON")
            return None
        if not isinstance(body, dict):
            self.fail(400, "bad_request", "the body must be a JSON object")
            return None
        return body


def serve(handler: type[MockHandler], host: str, port: int, origins: list[str]) -> ThreadingHTTPServer:
    """Start the server; prints the address it listens on (port 0 picks a free port)."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("the mock services listen on the loopback interface only")
    handler.origins = frozenset(origins)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"{handler.service} listening on http://{host}:{server.server_address[1]}", flush=True)
    return server
