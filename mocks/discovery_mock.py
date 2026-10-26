"""Local mock of an external discovery service (contract fdo-knowledge-dashboard/discovery/1) over a built catalog, marked mock.
    python -m mocks.discovery_mock --catalog dist/data/catalog.json --port 8792 --origins http://127.0.0.1:8090
    GET /capabilities   GET /search?q=flood&offset=0&limit=10
Scenario words in q: mock:error, mock:slow, mock:invalid, mock:big."""
from __future__ import annotations

import argparse
import json
import time
import unicodedata
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from mocks.common import MockHandler, serve

ENTITIES: list[dict] = []                                   # entities derived from a built catalog.json (--catalog): its keywords and records


def catalog_entities(path: str) -> list[dict]:
    try:
        cat = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"--catalog: {path} is not a readable catalog.json ({exc})") from exc
    rows = [r for r in cat.get("rows", []) if isinstance(r, dict) and isinstance(r.get("pid"), str) and isinstance(r.get("key"), str)]
    by_keyword: dict[str, list[str]] = {}
    for r in rows:
        for k in r.get("keywords") or []:
            if isinstance(k, str):
                by_keyword.setdefault(k.lower(), []).append(r["pid"])
    concepts = [{"id": f"mock:entity/concept-{i}", "pid": None, "title": f"Concept: {k}", "type": "Concept", "labels": [k],
                 "relations": [{"type": "subjectOf", "target": p} for p in pids[:50]]} for i, (k, pids) in enumerate(sorted(by_keyword.items()))]
    records = [{"id": f"mock:entity/record-{r['key']}", "pid": r["pid"], "title": r.get("title") or r["pid"], "type": "Record",
                "labels": [w for w in (r.get("title") or "").lower().split() if len(w) > 3] + [k.lower() for k in r.get("keywords") or []], "relations": []} for r in rows]
    return concepts + records
PROVIDER = "local discovery mock"
SUPPORTS = {"paging": True, "relations": True, "pids": True}
Q_MAX, LIMIT_MAX = 500, 50


def fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def search(q: str, offset: int, limit: int) -> dict:
    words = fold(q).split()
    found = [e for e in sorted(ENTITIES, key=lambda e: e["id"])
             if words and all(any(w in fold(t) for t in [e["title"], *e["labels"]]) for w in words)]
    items = [{"id": e["id"], "pid": e["pid"], "title": e["title"], "type": e["type"], "relations": e["relations"], "membership": "unverified"}
             for e in found[offset:offset + limit]]
    return {"schema": "fdo-knowledge-dashboard/discovery/1", "status": "ok", "provider": PROVIDER, "mock": True, "query": q,
            "offset": offset, "limit": limit, "total": len(found), "items": items}


class DiscoveryHandler(MockHandler):
    service = "discovery-mock"
    slow_seconds = 10.0

    def do_POST(self):
        self.fail(405, "method_not_allowed", "use GET")

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/capabilities":
            return self.reply(200, {"schema": "fdo-knowledge-dashboard/discovery-capabilities/1", "supports": SUPPORTS, "provider": PROVIDER, "mock": True})
        if url.path != "/search":
            return self.fail(404, "not_found", "unknown path")
        params = parse_qs(url.query, keep_blank_values=True)
        if set(params) - {"q", "offset", "limit"} or any(len(v) > 1 for v in params.values()):
            return self.fail(400, "bad_request", "accepted parameters: q, offset, limit, once each")
        q = (params.get("q") or [""])[0].strip()
        if not q or len(q) > Q_MAX or any(ord(c) < 32 for c in q):
            return self.fail(400, "bad_request", f"q must be 1 to {Q_MAX} characters without control characters")
        try:
            offset = int((params.get("offset") or ["0"])[0]); limit = int((params.get("limit") or ["10"])[0])
        except ValueError:
            return self.fail(400, "bad_request", "offset and limit must be integers")
        if not (0 <= offset <= 10_000 and 1 <= limit <= LIMIT_MAX):
            return self.fail(400, "bad_request", f"offset 0 to 10000, limit 1 to {LIMIT_MAX}")
        lq = q.lower()
        if "mock:error" in lq:
            return self.fail(500, "internal_error", "mock server error")
        if "mock:slow" in lq:
            time.sleep(self.slow_seconds)
        if "mock:invalid" in lq:
            return self.reply(200, "<html>not json</html>", "text/html")
        if "mock:big" in lq:
            return self.reply(200, {**search("flood", 0, 1), "padding": "x" * 1_200_000})
        self.reply(200, search(q, offset, limit))


def main() -> None:
    ap = argparse.ArgumentParser(description="Local mock of an external discovery service over a built catalog.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8792)
    ap.add_argument("--origins", nargs="*", default=[], help="browser origins allowed by CORS")
    ap.add_argument("--slow", type=float, default=10.0, help="seconds the mock:slow scenario waits")
    ap.add_argument("--catalog", required=True, help="a built data/catalog.json: the graph entities are its keywords and records")
    args = ap.parse_args()
    if args.catalog:
        globals()["ENTITIES"] = catalog_entities(args.catalog)
    DiscoveryHandler.slow_seconds = args.slow
    serve(DiscoveryHandler, args.host, args.port, args.origins).serve_forever()


if __name__ == "__main__":
    main()
