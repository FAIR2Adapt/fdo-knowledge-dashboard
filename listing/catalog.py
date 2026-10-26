"""The catalog: every member as a ResourceRecord, the compact rows the list page needs, the facets and the counts.
catalog.json and records/<key>.json are the whole contract between this code and any frontend."""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

from . import __version__, sources
from .delivery import NOT_STATED, generation_id, ordered, source_snapshot
from .reader import Reader
from .records import key_of, to_record

CATALOG_SCHEMA = "fdo-knowledge-dashboard/catalog/1"
MANIFEST_SCHEMA = "fdo-knowledge-dashboard/snapshot-manifest/1"
TYPE_NOT_STATED = NOT_STATED
SHORT = 220


def build(root: Path, cfg: dict) -> tuple[dict, dict]:
    """The catalog and the records by key, read once through fdo-consume."""
    reader = Reader(root, cfg)
    found = sources.members(reader, cfg, snapshot_index(root, cfg))
    read_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    map_fields = reader.map_fields()
    records = {key_of(pid): to_record(pid, reader.member(pid), cfg, read_at, reader.version, reader.kind, map_fields) for pid in found.pids}
    link_members(records)
    taken = taken_at(root, cfg)
    generation = generation_id(records, taken, CATALOG_SCHEMA)
    for record in records.values():
        record["source"]["generation"] = generation
    usable = [r for r in records.values() if r["source"]["usable"]]
    titles = Counter(r["title"] for r in usable)
    rows = [row_of(r, cfg["facets"], titles[r["title"]] > 1) for r in usable]
    not_usable = [{"key": r["key"], "pid": r["pid"], "explanation": r["source"]["explanation"], "reason": first_failure(r)}
                  for r in records.values() if not r["source"]["usable"]]
    by_type = Counter(t for r in usable for t in (r["resource_type"] or [TYPE_NOT_STATED]))
    site = dict(cfg["site"])
    site["map_notes"] = dict(cfg["reading"].get("map_notes") or {})
    footer = site.get("footer") or {}
    if (cfg["source"].get("data_origin") or "unknown") == "real" and footer.get("partners") and footer.get("partners_confirmed") is not True:
        site["footer"] = {**footer, "partners": []}       # partner names on real data are shown only with site.footer.partners_confirmed: true
        print("partners not confirmed: not shown", file=sys.stderr)
    type_facet = next((f["id"] for f in cfg["facets"] if f["concept"] == "resource_type"), None)
    catalog = {"schema": CATALOG_SCHEMA, "generator": f"fdo-knowledge-dashboard {__version__}", "reader": f"fdo-consume {reader.version}",
               "built_at": read_at, "source_taken": taken, "site": site,
               "generation": {"id": generation, "data_origin": cfg["source"].get("data_origin") or "unknown", "retrieved_at": taken},
               "collection": found.collection or {"pid": None, "usable": None, "title": site.get("title"), "description": None,
                                                  "members_total": found.total, "members_skipped": 0, "stopped": None, "explanation": None, "console": None},
               "source_kind": found.kind, "aliases": [{"pid": pid, "aliases": others} for pid, others in found.aliases.items()],
               "counts": {"listed": len(found.pids), "usable": len(usable), "not_usable": len(not_usable),
                          "multi_typed": sum(len(r["resource_type"]) > 1 for r in usable), "by_type": dict(ordered(by_type.items()))},
               "facets": facets_of(rows, cfg["facets"]), "type_facet": type_facet, "not_stated": TYPE_NOT_STATED,
               "facets_without_source": cfg["facets_without_source"],
               "diagnostics_open": bool(cfg["diagnostics_open"]), "rows": rows, "not_usable": not_usable,
               "records": "data/records/{key}.json"}
    return catalog, records


def snapshot_index(root: Path, cfg: dict) -> dict:
    """The recorded index (pids.json) of the configured source; empty for live reads."""
    recorded = cfg["source"].get("recorded")
    index = root / recorded / "pids.json" if recorded else None
    if not (index and index.is_file()):
        return {}
    try:
        loaded = json.loads(index.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{index} is not a readable pids.json: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{index} is not a readable pids.json: an object of PID -> entry is expected")
    return loaded


def source_snapshot_of(root: Path, cfg: dict, catalog: dict) -> dict:
    """The SourceSnapshot of a build: the recorded index plus the outcomes of the last sync when a manifest exists. A
    manifest that is present but does not describe the index (another shape, other hashes) gives status `unknown`."""
    recorded = cfg["source"].get("recorded")
    path = root / recorded / "manifest.json" if recorded else None
    index = snapshot_index(root, cfg)
    if not (path and path.is_file()):
        snapshot = source_snapshot(catalog, index, recorded)
    else:
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            manifest = None
        snapshot = source_snapshot(catalog, index, recorded, manifest if isinstance(manifest, dict) else None, unknown=not describes(manifest, index))
    community = root / recorded / "community.json"
    if cfg["source"].get("kind") == "community" and community.is_file():
        try:
            record = json.loads(community.read_text(encoding="utf-8"))
        except ValueError:
            record = None
        if isinstance(record, dict) and all(k in record for k in ("community", "search", "taken", "hits", "members_found")):
            snapshot["community"] = {k: record[k] for k in ("community", "search", "taken", "hits", "members_found", "members_kept") if k in record}
    return snapshot


def describes(manifest, index: dict) -> bool:
    """The manifest has the current shape and names every indexed PID with the same crate hash."""
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA or not isinstance(manifest.get("entries"), list):
        return False
    by = {e.get("pid"): e for e in manifest["entries"] if isinstance(e, dict)}
    return all(pid in by and (not e.get("sha256") or by[pid].get("sha256") == e["sha256"]) for pid, e in index.items() if isinstance(e, dict))


def taken_at(root: Path, cfg: dict) -> str | None:
    """When the recorded snapshot was taken (the latest `taken` in its pids.json); None for live reads or old folders."""
    times = [e.get("taken") for e in snapshot_index(root, cfg).values() if isinstance(e, dict) and e.get("taken")]
    return max(times) if times else None


def link_members(records: dict) -> None:
    """A relation that names a member by PID gets that member's title, status and key; nothing is added for others."""
    by_pid = {r["pid"]: r for r in records.values()}
    for record in records.values():
        for relation in [c["asserted_in"] for c in record["claims"] if c["asserted_in"]] + record["related"] + record["based_on"]:
            member = by_pid.get(relation["pid"]) or by_pid.get(str(relation["pid"]).rstrip("/"))
            if member:
                relation["key"] = member["key"]
                relation["title"] = relation.get("title") or member["title"]
                if "status" in relation:
                    relation["status"] = member["status"]


def row_of(record: dict, specs: list, duplicate_title: bool) -> dict:
    """What the list page and the search need from a record; the full record is one more file away."""
    description = record["description"] or ""
    return {"key": record["key"], "pid": record["pid"], "title": record["title"], "duplicate_title": duplicate_title,
            "description": description[:SHORT] + ("…" if len(description) > SHORT else ""),
            "resource_type": record["resource_type"], "keywords": record["keywords"], "authors": record["authors"],
            "date": record["date"], "year": record["year"], "status": record["status"], "claims": len(record["claims"]),
            "claim_texts": [c["text"] for c in record["claims"] if c["text"]], "claim_kinds": [c["kind"] for c in record["claims"] if c["text"]],
            "incomplete": bool(record["source"]["record"]["unknown_terms"]),
            "facet_values": {spec["id"]: facet_values(record, spec) for spec in specs}}


def facet_values(record: dict, spec: dict) -> list:
    """The values of one facet for one record, read from the field the configuration names; a missing resource type
    is 'type not stated' so that it can be counted and filtered, never guessed."""
    concept = spec["concept"]
    raw = [p["label"] or p["iri"] for p in record["profiles"]] if concept == "profile" else record.get(concept)
    values = raw if isinstance(raw, list) else [raw] if raw else []
    if concept == "resource_type" and not values:
        return [TYPE_NOT_STATED]
    return sorted({str(v) for v in values})


def facets_of(rows: list, specs: list) -> list:
    """Per configured facet: its values over the shown records with counts, most frequent first, 'type not stated' last."""
    out = []
    for spec in specs:
        counter = Counter(v for row in rows for v in row["facet_values"].get(spec["id"], []))
        out.append({"id": spec["id"], "label": spec["label"], "description": spec.get("description"), "concept": spec["concept"],
                    "group": spec.get("group", "main"), "icon": spec.get("icon"), "home": bool(spec.get("home")), "panel": spec.get("panel", "more"),
                    "values": [{"value": v, "count": n} for v, n in ordered(counter.items())]})
    return out


def first_failure(record: dict) -> str:
    """The technical line behind an explanation: the first FAIL or INDETERMINATE diagnostic, else the stop or error."""
    source = record["source"]["record"]
    for d in source["diagnostics"]:
        if d["status"] in ("FAIL", "INDETERMINATE"):
            return f"{d['code']} {d['status']}: {d['message']}"
    return source["stopped"] or (source["error"] or {}).get("message") or "not usable"
