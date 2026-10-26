"""Delivery of the catalog to browsers and servers: canonical PIDs, the generation id, summaries, details, the source snapshot and
a search with the same semantics as the browser layer (web/app.js). Static and HTTP modes serve these shapes."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from .models import LIMIT_DEFAULT, LIMIT_MAX, QUERY_MAX, SearchRequest

SEARCH_SCHEMA = "fdo-knowledge-dashboard/search/1"
DETAIL_SCHEMA = "fdo-knowledge-dashboard/resource-detail/1"
SNAPSHOT_SCHEMA = "fdo-knowledge-dashboard/source-snapshot/1"
NOT_STATED = "type not stated"
SORTS = ("title", "date", "type")
ORIGINS = ("real", "synthetic", "experimental", "unknown")
FIELD_MESSAGES = {"q": f"q must be a string of at most {QUERY_MAX} characters without control characters", "filters": "a filter must be a list of at most 50 strings",
                  "sort": "sort must be one of title, date, type", "offset": "offset must be an integer", "limit": "limit must be an integer",
                  "lang": "lang must be a language tag such as en or pt-PT"}
RANGE_MESSAGES = {"offset": "offset must be between 0 and 10000000", "limit": f"limit must be between 1 and {LIMIT_MAX}"}
COMBINING = re.compile(r"[̀-ͯ]")


class ContractError(ValueError):
    """A request outside the contract; `code` is bad_request or not_found."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def canonical_pid(pid) -> str | None:
    """One spelling per identifier: trimmed, no trailing slash, http(s) scheme and host in lower case, path kept."""
    if not isinstance(pid, str) or not pid.strip():
        return None
    pid = pid.strip().rstrip("/")
    parts = urlsplit(pid)
    if parts.scheme.lower() in ("http", "https") and parts.netloc:
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, parts.fragment))
    return pid


def generation_id(records: dict, source_taken: str | None, catalog_schema: str) -> str:
    """Deterministic over the data read: every member's PID and crate hash plus the snapshot time; not the build time."""
    lines = sorted(f"{r['pid']} {r['source']['record'].get('crate_sha256') or ''}" for r in records.values())
    return hashlib.sha256("\n".join([catalog_schema, source_taken or ""] + lines).encode("utf-8")).hexdigest()[:16]


def fold(text) -> str:
    return COMBINING.sub("", unicodedata.normalize("NFD", str(text or ""))).lower()


def ordered(items) -> list:
    """Facet values most frequent first, ties by value, 'type not stated' last."""
    return sorted(items, key=lambda kv: (kv[0] == NOT_STATED, -kv[1], kv[0]))


def matches(row: dict, words: list, filters: dict, skip: str | None = None) -> bool:
    """OR within a facet, AND across facets, every query word somewhere in the row's text; `skip` ignores one facet."""
    for fid, wanted in filters.items():
        if fid == skip or not wanted:
            continue
        if not wanted & set(row["facet_values"].get(fid) or []):
            return False
    if not words:
        return True
    hay = fold(" ".join([row["title"] or "", row["description"] or "", row["date"] or "", *row["keywords"], *row["authors"], *row["claim_texts"]]))
    return all(w in hay for w in words)


def sort_rows(rows: list, sort: str) -> list:
    """Code-point order of the folded text, ties by the raw title, missing values last; `type` sorts by the first stated
    type; `date` newest first. web/search.js sorts the same way."""
    title = lambda r: (fold(r["title"]), r["title"] or "")
    if sort == "date":
        return sorted(sorted(rows, key=title), key=lambda r: r["date"] or "", reverse=True)
    keys = {"title": title, "type": lambda r: (not r["resource_type"], fold(r["resource_type"][0]) if r["resource_type"] else "", title(r))}
    return sorted(rows, key=keys[sort])


def validate(request: dict, facet_specs: list) -> dict:
    """A SearchRequest with defaults filled; a value outside the contract raises bad_request with a fixed message."""
    known = {f["id"] for f in facet_specs}
    for fid in request.get("filters") or {}:
        if fid not in known:
            raise ContractError("bad_request", "unknown facet; facets: " + ", ".join(sorted(known)))
    try:
        model = SearchRequest.model_validate({k: v for k, v in request.items() if v is not None or k == "lang"})
    except ValidationError as exc:
        raise ContractError("bad_request", message_of(exc.errors()[0])) from None
    return model.model_dump()


def message_of(err: dict) -> str:
    """One fixed sentence per defect, the same as validate.py states it at the HTTP boundary."""
    field, kind = str((err.get("loc") or ["request"])[0]), err.get("type", "")
    if kind == "value_error":
        return str(err.get("msg", "")).removeprefix("Value error, ") or FIELD_MESSAGES.get(field, "the request is outside the contract")
    if kind in ("greater_than_equal", "less_than_equal") and field in RANGE_MESSAGES:
        return RANGE_MESSAGES[field]
    if kind == "string_too_long" and field == "q":
        return f"a text value is longer than {QUERY_MAX} characters"
    return FIELD_MESSAGES.get(field, "the request is outside the contract")


def summary_of(row: dict, generation: str) -> dict:
    return {"pid": row["pid"], "canonical_pid": canonical_pid(row["pid"]), "key": row["key"], "title": row["title"],
            "description": row["description"], "resource_type": row["resource_type"], "keywords": row["keywords"],
            "authors": row["authors"], "date": row["date"], "year": row["year"], "status": row["status"], "claims": row["claims"],
            "claim_texts": row["claim_texts"], "claim_kinds": row.get("claim_kinds", []), "duplicate_title": row["duplicate_title"],
            "incomplete": row["incomplete"], "readiness": "usable", "generation_id": generation, "record": f"data/records/{row['key']}.json"}


def detail_of(record: dict, generation: str, origin: str) -> dict:
    """The ResourceRecord unchanged inside an envelope that states readiness and delivery; validity is never asserted."""
    return {"schema": DETAIL_SCHEMA, "generation_id": generation, "pid": record["pid"], "canonical_pid": canonical_pid(record["pid"]),
            "readiness": "usable" if record["source"]["usable"] else "not_usable", "data_origin": origin,
            "distribution": {"metadata": "public", "files": record["access"]["state"]}, "record": record}


def search(catalog: dict, request: dict) -> dict:
    """A SearchResponse over the catalog rows: filtered, sorted, paged, with facet counts over the result as the browser
    computes them (each facet counted with its own selection removed)."""
    req = validate(request, catalog["facets"])
    words = fold(req["q"]).split()
    filters = {fid: set(v) for fid, v in req["filters"].items()}
    rows = catalog["rows"]
    hits = sort_rows([r for r in rows if matches(r, words, filters)], req["sort"])
    facets = []
    for spec in catalog["facets"]:
        counter = Counter(v for r in rows if matches(r, words, filters, spec["id"]) for v in r["facet_values"].get(spec["id"], []))
        facets.append({"id": spec["id"], "label": spec["label"], "concept": spec["concept"], "values": [{"value": v, "count": n} for v, n in ordered(counter.items())]})
    generation = (catalog.get("generation") or {}).get("id")
    page = hits[req["offset"]:req["offset"] + req["limit"]]
    return {"schema": SEARCH_SCHEMA, "generation_id": generation, "scope": {"collection": catalog["collection"].get("pid"), "source_kind": catalog["source_kind"]},
            "request": req, "status": "ok" if hits else "empty", "total": len(hits), "offset": req["offset"], "limit": req["limit"],
            "items": [summary_of(r, generation) for r in page], "facets": facets,
            "omissions": {"not_usable": catalog["counts"]["not_usable"], "not_searchable": "records that could not be read are listed, not searched"}}


def source_snapshot(catalog: dict, index: dict, recorded: str | None, manifest: dict | None = None, *, unknown: bool = False) -> dict:
    """SourceSnapshot: what the build read, per PID, from the recorded index (pids.json) and, when a sync manifest exists,
    the PIDs it could not record (gone, restricted, failed); nothing is added for live reads. `unknown`: a manifest is
    present but does not describe this index, so no outcome is claimed."""
    outcomes = {} if unknown else {e["pid"]: e for e in (manifest or {}).get("entries", []) if isinstance(e, dict) and e.get("pid")}
    items = []
    for pid in list(index) + [p for p in outcomes if p not in index]:
        e = index.get(pid) if isinstance(index.get(pid), dict) else {}
        m = outcomes.get(pid, {})
        items.append({"pid": pid, "canonical_pid": canonical_pid(pid), "source_uri": e.get("fetched_from") or m.get("fetched_from"),
                      "retrieved_at": e.get("taken") or m.get("taken"), "hash": e.get("sha256"),
                      "status": "unknown" if unknown else (m.get("outcome", "recorded") if m else "recorded")})
    generation = catalog.get("generation") or {}
    return {"schema": SNAPSHOT_SCHEMA, "generation_id": generation.get("id"), "built_at": catalog["built_at"], "retrieved_at": catalog["source_taken"],
            "source_kind": catalog["source_kind"], "data_origin": generation.get("data_origin", "unknown"), "recorded": recorded,
            "members": {k: catalog["counts"][k] for k in ("listed", "usable", "not_usable")}, "items": items}
