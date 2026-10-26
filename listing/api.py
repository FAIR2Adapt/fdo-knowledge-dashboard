"""HTTP routes over a built site (catalog, records, generation): framework-independent, GET only, rate-limited per
client, CORS for configured origins. server.py calls `handle` from the standard-library and the FastAPI path alike."""
from __future__ import annotations

import time

from . import delivery, validate

API = "/api/v1"
HEALTH_SCHEMA = "fdo-knowledge-dashboard/health/1"
MAX_CLIENTS = 10_000                                     # rate-limit state is bounded; the oldest clients are forgotten first
STATUS = {"bad_request": 400, "not_found": 404, "uri_too_long": 414}


def error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def client_of(peer: str, headers, behind_proxy: bool) -> str:
    """The client identity for rate limiting: the socket peer, or behind a trusted reverse proxy the address that proxy
    appended last to X-Forwarded-For. Never trust the header when the server is reachable directly."""
    forwarded = headers.get("X-Forwarded-For") if behind_proxy else None
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        return last or peer
    return peer


def preflight(method: str, origins, origin: str | None):
    """The response headers (JSON, CORS for an allowed origin) and, for OPTIONS or a method other than GET, the whole
    response; None as the second value means the GET goes on. Answered before the site is consulted."""
    headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-cache"}
    if origin and ("*" in origins or origin in origins):
        headers.update({"Access-Control-Allow-Origin": "*" if "*" in origins else origin, "Vary": "Origin", "Access-Control-Allow-Methods": "GET, OPTIONS"})
    if method == "OPTIONS":
        return headers, (204, headers, None)
    if method != "GET":
        return headers, (405, {**headers, "Allow": "GET, OPTIONS"}, error("bad_request", "GET only"))
    return headers, None


def without_blanks(query: dict) -> dict:
    """A blank value counts as an absent parameter; a blank `q` is kept as no query."""
    kept = {name: (values if name == "q" else [v for v in values if v != ""]) for name, values in query.items()}
    return {name: values for name, values in kept.items() if values}


class Api:
    """Routes: health, generation, search, facets, resources/<key>, resources?pid=."""

    def __init__(self, catalog: dict, records: dict, generation: dict, *, capabilities: dict | None = None, allowed_origins=(), rate_per_minute: int = 120, clock=time.monotonic):
        self.catalog, self.records, self.generation, self.capabilities = catalog, records, generation, capabilities
        self.by_canonical = {delivery.canonical_pid(r["pid"]): key for key, r in records.items()}
        self.origins, self.rate, self.clock, self.seen = tuple(allowed_origins), rate_per_minute, clock, {}

    def allow(self, client: str) -> bool:
        """At most `rate` requests per client in a sliding minute; the table never grows past MAX_CLIENTS."""
        now = self.clock()
        recent = [t for t in self.seen.pop(client, []) if now - t < 60]
        self.seen[client] = recent + [now]                   # re-inserted last: insertion order is recency order
        if len(self.seen) > MAX_CLIENTS:
            for key in [k for k, v in self.seen.items() if now - v[-1] >= 60]:
                del self.seen[key]
            while len(self.seen) > MAX_CLIENTS:
                del self.seen[next(iter(self.seen))]
        return len(recent) < self.rate

    def handle(self, method: str, path: str, query: dict, client: str, origin: str | None = None) -> tuple[int, dict, dict | None]:
        headers, refused = preflight(method, self.origins, origin)
        if refused:
            return refused
        if not self.allow(client):
            return 429, {**headers, "Retry-After": "60"}, error("rate_limited", f"more than {self.rate} requests per minute")
        try:
            return 200, headers, self.route(path, without_blanks(query))
        except delivery.ContractError as exc:
            return STATUS.get(exc.code, 400), headers, error(exc.code, str(exc))

    def route(self, path: str, query: dict) -> dict:
        generation = self.catalog["generation"]
        if path == f"{API}/health":
            return {"schema": HEALTH_SCHEMA, "status": "ok", "generation_id": generation["id"], "built_at": self.catalog["built_at"],
                    "data_origin": generation["data_origin"], "records": len(self.records)}
        if path == f"{API}/generation":
            return self.generation
        if path == f"{API}/capabilities":
            if not self.capabilities:
                raise delivery.ContractError("not_found", "this build carries no capabilities document")
            return self.capabilities
        if path == f"{API}/search":
            return delivery.search(self.catalog, validate.search_request(query, self.catalog["facets"]))
        if path == f"{API}/facets":
            return {"schema": delivery.SEARCH_SCHEMA, "generation_id": generation["id"], "facets": delivery.search(self.catalog, {"limit": 1})["facets"]}
        if path == f"{API}/resources":
            pid = validate.pid((query.get("pid") or [None])[0])
            return self.detail(self.by_canonical.get(delivery.canonical_pid(pid)), "no resource with this identifier")
        if path.startswith(f"{API}/resources/"):
            return self.detail(validate.key(path[len(f"{API}/resources/"):]), "no resource with this key")
        raise delivery.ContractError("not_found", "no such route; routes: health, generation, capabilities, search, facets, resources")

    def detail(self, key: str | None, message: str) -> dict:
        record = self.records.get(key) if key else None
        if not record:
            raise delivery.ContractError("not_found", message)
        return delivery.detail_of(record, self.catalog["generation"]["id"], self.catalog["generation"]["data_origin"])
