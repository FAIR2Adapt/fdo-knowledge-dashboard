"""Serve the FDO Knowledge Dashboard and its optional HTTP API."""
from __future__ import annotations

import argparse
import http.server
import json
import logging
import os
import re
import sys
import tempfile
from functools import partial
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from listing import validate  # noqa: E402
from listing.api import API, Api, client_of, error, preflight  # noqa: E402

log = logging.getLogger("fdo-knowledge-dashboard")
LOOPBACK = ("127.0.0.1", "::1")
NOT_READY = {"error": {"code": "unavailable", "message": "no site has been built into this server's directory yet"}}
NOT_REBUILT = {"error": {"code": "unavailable", "message": "the site could not be rebuilt; the previous build stays; see the server log"}}
BAD_PATH = error("bad_request", "the request path is not valid")
JSON = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-cache"}
SECURITY = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "strict-origin-when-cross-origin",
            "Content-Security-Policy": "frame-ancestors 'none'"}
HTML_PATHS = ("/", "/index.html")
FRAME_ANCESTOR = re.compile(r"^(https://[A-Za-z0-9.-]+(:\d+)?|http://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?)$")


def check_frame_ancestors(values) -> list[str]:
    for value in values:
        if not isinstance(value, str) or not FRAME_ANCESTOR.match(value):
            raise ValueError(f"--frame-ancestors takes https origins without a path (or http loopback origins for a local host page), not {value!r}")
    return list(values)


def security_headers(path: str, ancestors=()) -> dict:
    """Return security headers with configured HTML framing restrictions."""
    if ancestors and path.split("?", 1)[0] in HTML_PATHS:
        return {**{k: v for k, v in SECURITY.items() if k != "X-Frame-Options"}, "Content-Security-Policy": f"frame-ancestors {' '.join(ancestors)}"}
    return SECURITY


class Site:
    """Serve a consistent generation of catalog and resource records."""

    refreshable = False

    def __init__(self, dist: Path, origins=(), rate: int = 120, behind_proxy: bool = False, frame_ancestors=()):
        self.dist, self.origins, self.rate, self.behind_proxy = Path(dist), list(origins), rate, behind_proxy
        self.frame_ancestors = check_frame_ancestors(frame_ancestors)
        self.stamp, self.api = None, None
        self.load()

    def load(self) -> None:
        data = self.dist / "data"
        try:
            stamp = (data / "generation.json").stat().st_mtime_ns
            if stamp == self.stamp:
                return
            generation = json.loads((data / "generation.json").read_text(encoding="utf-8"))
            catalog = json.loads((data / "catalog.json").read_text(encoding="utf-8"))
            records = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (data / "records").glob("*.json")}
            capabilities = json.loads((data / "capabilities.json").read_text(encoding="utf-8")) if (data / "capabilities.json").is_file() else None
        except (FileNotFoundError, ValueError):
            return
        wanted = generation.get("generation_id")
        keys = {r["key"] for r in catalog.get("rows", [])} | {r["key"] for r in catalog.get("not_usable", [])}
        if not (wanted and catalog.get("generation", {}).get("id") == wanted and keys == set(records)
                and all(r.get("source", {}).get("generation") == wanted for r in records.values())
                and (capabilities is None or capabilities.get("generation", {}).get("id") == wanted)):
            return
        self.api, self.stamp = Api(catalog, records, generation, capabilities=capabilities, allowed_origins=self.origins, rate_per_minute=self.rate), stamp

    def handle(self, method: str, path: str, query: dict, client: str, origin: str | None):
        self.load()
        if self.api is None:
            headers, refused = preflight(method, self.origins, origin)
            return refused or (503, {**headers, "Retry-After": "30"}, NOT_READY)
        return self.api.handle(method, path, query, client, origin)

    def rebuild(self) -> bool:
        return False


class DevSite(Site):
    """Development: the configuration is built into a temporary directory, which is then served like any build."""

    refreshable = True

    def __init__(self, config_path: str | None, origins=(), rate: int = 120, behind_proxy: bool = False, frame_ancestors=()):
        self.config_path = config_path
        self.tmp = tempfile.TemporaryDirectory(prefix="fdo-knowledge-dashboard-")
        super().__init__(Path(self.tmp.name) / "dist", origins, rate, behind_proxy, frame_ancestors)
        self.rebuild()

    def rebuild(self) -> bool:
        """Build again; a failure is logged and leaves the previous build in service."""
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            from build_site import build
            from listing import config
            cfg = config.load(ROOT, self.config_path)
            build(self.dist, cfg)
            self.origins, self.rate, self.behind_proxy = cfg["api"]["allowed_origins"], cfg["api"]["rate_per_minute"], cfg["api"]["behind_proxy"]
        except SystemExit as exc:
            log.warning("the site was not rebuilt: %s", exc)
            return False
        except Exception:
            log.exception("the site could not be built")
            return False
        self.load()
        return True


class Handler(http.server.SimpleHTTPRequestHandler):
    site: Site = None

    default_request_version = "HTTP/1.0"                      # a refused request line still gets a status line

    def version_string(self):
        return "fdo-knowledge-dashboard"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.site.dist), **kwargs)

    def refused(self, parsed) -> bool:
        """A target over the bound (414) or a NUL in the path (400) is answered before any lookup."""
        try:
            validate.target(parsed.path, parsed.query)
        except Exception:
            self.reply(414, JSON, error("uri_too_long", "the request target is too long"))
            return True
        if "\x00" in parsed.path or "%00" in parsed.path:
            self.reply(400, JSON, BAD_PATH)
            return True
        return False

    def is_api(self, parsed) -> bool:
        return parsed.path.startswith(API) or parsed.path in ("/api", "/api/v1")

    def do_GET(self):
        parsed = urlparse(self.path)
        if self.refused(parsed):
            return
        if self.is_api(parsed):
            return self.api("GET", parsed)
        if self.site.refreshable and parsed.path == "/data/catalog.json" and "refresh=1" in parsed.query and self.client_address[0] in LOOPBACK:
            if not self.site.rebuild() and self.site.api is not None:
                return self.reply(409, JSON, NOT_REBUILT)
        self.site.load()
        if self.site.api is None:
            return self.reply(503, {**JSON, "Retry-After": "30"}, NOT_READY)
        return super().do_GET()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        if self.refused(parsed):
            return
        if self.is_api(parsed):
            return self.api("HEAD", parsed)
        self.site.load()
        if self.site.api is None:
            return self.reply(503, {**JSON, "Retry-After": "30"}, NOT_READY)
        return super().do_HEAD()

    def do_OPTIONS(self):
        parsed = urlparse(self.path)
        if self.refused(parsed):
            return
        if self.is_api(parsed):
            return self.api("OPTIONS", parsed)
        self.reply(405, {**JSON, "Allow": "GET, HEAD"}, error("bad_request", "GET only"))

    def do_POST(self):
        parsed = urlparse(self.path)
        if self.refused(parsed):
            return
        if self.is_api(parsed):
            return self.api(self.command, parsed)
        self.reply(405, {**JSON, "Allow": "GET, HEAD"}, error("bad_request", "GET only"))

    do_PUT = do_DELETE = do_PATCH = do_POST

    def list_directory(self, path):
        self.send_error(404, "Not Found")
        return None

    def api(self, method: str, parsed) -> None:
        client = client_of(self.client_address[0], self.headers, self.site.behind_proxy)
        status, headers, body = self.site.handle(method, parsed.path, parse_qs(parsed.query, keep_blank_values=True), client, self.headers.get("Origin"))
        self.reply(status, headers, body)

    def reply(self, status: int, headers: dict, body) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b""
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def send_response(self, code, message=None):
        self.cache_control_sent = False
        super().send_response(code, message)

    def send_header(self, keyword, value):
        if keyword.lower() == "cache-control":
            self.cache_control_sent = True
        super().send_header(keyword, value)

    def end_headers(self):
        path = getattr(self, "path", "")
        if not path.startswith(API) and not getattr(self, "cache_control_sent", False):
            self.send_header("Cache-Control", "no-cache" if path.startswith("/data/") else "public, max-age=60")
        for name, value in security_headers(path, self.site.frame_ancestors).items():
            self.send_header(name, value)
        super().end_headers()

    def log_request(self, code="-", size="-"):
        line = self.requestline.split("?", 1)[0]
        if API in line or "/data/" in line:
            self.log_message('"%s" %s %s', line, str(code), str(size))

    def log_message(self, fmt, *args):
        log.info(fmt, *args)


def serve(site: Site, host: str, port: int) -> http.server.ThreadingHTTPServer:
    handler = type("SiteHandler", (Handler,), {"site": site})
    return http.server.ThreadingHTTPServer((host, port), partial(handler))


def create_app(site: Site):
    """The same routes through FastAPI (optional dependency)."""
    from fastapi import FastAPI, Request, Response
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="fdo-knowledge-dashboard", docs_url=None, redoc_url=None, openapi_url=None)

    @app.api_route(API + "/{rest:path}", methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH"])
    def api(rest: str, request: Request) -> Response:
        query = {}
        for name, value in request.query_params.multi_items():
            query.setdefault(name, []).append(value)
        client = client_of(request.client.host if request.client else "-", {"X-Forwarded-For": request.headers.get("x-forwarded-for")}, site.behind_proxy)
        status, headers, body = site.handle(request.method, f"{API}/{rest}", query, client, request.headers.get("origin"))
        return Response(json.dumps(body, ensure_ascii=False) if body is not None else b"", status_code=status, headers=headers)

    @app.middleware("http")
    async def not_ready(request: Request, call_next):
        site.load()
        if site.api is None and not request.url.path.startswith(API):
            return Response(json.dumps(NOT_READY), status_code=503, media_type="application/json")
        return await call_next(request)

    @app.middleware("http")
    async def hygiene(request: Request, call_next):
        response = await call_next(request)
        for name, value in security_headers(request.url.path, site.frame_ancestors).items():
            response.headers.setdefault(name, value)
        return response

    app.mount("/", StaticFiles(directory=str(site.dist), html=True, check_dir=False), name="site")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a built fdo-knowledge-dashboard site, or build and serve a configuration.")
    parser.add_argument("--dist", default=None, help="a built directory; without it the configuration is built into a temporary directory")
    parser.add_argument("--config", default=os.environ.get("LISTING_CONFIG"), help="configuration for the development build (default config/portugal-dashboard.yaml)")
    parser.add_argument("--host", default=os.environ.get("APP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "8010")))
    parser.add_argument("--origins", nargs="*", default=os.environ.get("DASHBOARD_ORIGINS", "").split(), help="browser origins allowed to call the API")
    parser.add_argument("--rate", type=int, default=int(os.environ.get("DASHBOARD_RATE", "120")), help="requests per client per minute")
    parser.add_argument("--behind-proxy", action="store_true", default=os.environ.get("DASHBOARD_BEHIND_PROXY") == "1",
                        help="rate-limit by the address the reverse proxy appended to X-Forwarded-For; only when the port is reachable through the proxy alone")
    parser.add_argument("--frame-ancestors", nargs="*", default=os.environ.get("DASHBOARD_FRAME_ANCESTORS", "").split(),
                        help="origins whose pages may frame the HTML document (https, or http on loopback); data and API answers are never framable")
    parser.add_argument("--fastapi", action="store_true", help="serve through FastAPI and uvicorn (pip install -r requirements-server.txt)")
    args = parser.parse_args()
    try:
        check_frame_ancestors(args.frame_ancestors)
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    site = (Site(Path(args.dist).resolve(), args.origins, args.rate, args.behind_proxy, args.frame_ancestors) if args.dist
            else DevSite(args.config, args.origins, args.rate, args.behind_proxy, args.frame_ancestors))
    if args.dist is None and site.api is None:
        raise SystemExit("the configuration could not be built; see the log above")
    print(f"FDO Knowledge Dashboard at http://{args.host}:{args.port} from {site.dist}", flush=True)
    if args.fastapi:
        import uvicorn
        uvicorn.run(create_app(site), host=args.host, port=args.port, log_level="info")
        return
    try:
        serve(site, args.host, args.port).serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
