"""Composition from a Dashboard FDO (experimental): the FDO names the collection, the views (panels → Plugin FDOs) and their
portable settings; the host configuration wins on conflict. Plugin FDOs resolve to local views through an allowlist by
identifier and exact version; nothing is fetched or executed. The result is the build configuration plus a binding report."""
from __future__ import annotations

import copy
import re

from .config import FACET_CONCEPTS, HEX, TEXT_TOKENS, contrast
from .reader import describe_in

REPORT_SCHEMA = "fdo-knowledge-dashboard/composition/1"
TRUSTED_VIEWS = {                                       # plugin PID → the local view that stands for it, one version each
    "https://example.org/fixture/plugin/listing-list": {"view": "list", "version": "0.1.0"},
    "https://example.org/fixture/plugin/listing-record": {"view": "record", "version": "0.1.0"},
    "https://example.org/fixture/plugin/listing-claims": {"view": "claims", "version": "0.1.0"},
}
STYLE_TOKENS = {"primaryColor": "primary", "secondaryColor": "deep"}      # the FDO's style names → the site's validated tokens
NOT_REPRESENTABLE = ["site.brand (logo, flag, mark)", "site.background (image, alt, attribution)", "site.pages labels and visibility beyond 'a question panel exists'",
                     "site.footer (statements, partners)", "site.demo_notice / site.source_notice", "site.hero.highlight and the topic cards", "facet icons, category icons and tones",
                     "source.recorded, source.crate_url (where snapshots live)", "reading.* (contracts, maps, profile)", "language / locale"]
TONES = ("orange", "green", "blue", "purple", "green")


def describe_recorded(root, cfg: dict, source: dict, pid: str):
    """An object of the composition: from the snapshot folder when it was recorded there (a refresh records the dashboard
    and its members by PID), else from the dashboard's own folder (experimental crates, plugins)."""
    folders = [source.get("recorded")] + ([source["dashboard_dir"]] if source.get("dashboard_dir") not in (None, source.get("recorded")) else [])
    rec = None
    for folder in folders:
        rec = describe_in(root, cfg, folder, pid)
        if rec.outcome != "not_resolved":
            return rec
    return rec


class CompositionError(Exception):
    """The Dashboard FDO could not be composed into a listing; the report says why."""


def compose(root, cfg: dict) -> tuple[dict, dict]:
    """The host configuration with the values the Dashboard FDO supplies where the host is silent, and the binding report."""
    source = cfg["source"]
    report = {"schema": REPORT_SCHEMA, "experimental": True, "dashboard": {"pid": source["pid"]}, "panels": [], "values": [],
              "diagnostics": [], "not_representable": NOT_REPRESENTABLE}
    diag = lambda code, status, message, **where: report["diagnostics"].append({"code": code, "status": status, "message": message, **where})
    rec = describe_recorded(root, cfg, source, source["pid"])
    entities = ((rec.descriptor or {}).get("extra") or {}).get("entities", [])
    report["dashboard"].update({"outcome": rec.outcome, "sha256": rec.record_sha256, "map": ((rec.semantics or {}).get("profile") or {}).get("selected"),
                                "steps": [f"{s.id} {s.status}: {s.detail}" for s in rec.steps if s.status != "PASS"]})
    dashboards = [e for e in entities if e["type"] == "Dashboard"]
    if len(dashboards) != 1:
        diag("compose.dashboard_unreadable" if not dashboards else "compose.dashboard_ambiguous", "FAIL", f"{len(dashboards)} Dashboard entities found; one is needed")
        raise CompositionError(report["diagnostics"][-1]["message"])
    dash = dashboards[0]["fields"]
    report["dashboard"].update({"name": dash.get("name"), "status": dash.get("status"), "description": dash.get("description")})
    if "experimental" not in str(dash.get("status") or "").lower():
        diag("dashboard.status_not_experimental", "WARN", "the Dashboard FDO does not say it is experimental; this software composes experiments only")
    panels_by_id = {e["id"]: e for e in entities if e["type"] == "Panel"}
    collections = {e["id"]: e for e in entities if e["type"] == "Collection"}
    values = {e["id"]: e for e in entities if e["type"] in ("Property", "Style")}
    out = copy.deepcopy(cfg)
    out["source"] = {"kind": "pids", "pids": [], "recorded": source["recorded"], "crate_url": source.get("crate_url"), "data_origin": source.get("data_origin")}
    members = None
    for panel in _ordered_panels(dash, panels_by_id, diag):
        entry = _panel(root, cfg, source, panel, collections, values, diag)
        report["panels"].append(entry)
        if entry["view"] == "list" and entry["status"] == "PASS":
            members = entry["bound"]["members"]
    if not members:
        diag("compose.no_members", "FAIL", "no list panel bound a collection with members; nothing to list")
        raise CompositionError(report["diagnostics"][-1]["message"])
    out["source"]["pids"] = list(members)
    report["values"].append({"key": "source.pids", "source": "fdo", "value": f"{len(members)} members by identifier"})
    _portable(out, cfg, dash, values, report, diag)
    lst = next((p for p in report["panels"] if p["view"] == "list" and p["status"] == "PASS"), None)
    if lst:
        _list_settings(out, cfg, lst["settings"], report, diag)
    if not any(p["view"] == "question" for p in report["panels"]) and "ask" not in ((cfg.get("site") or {}).get("pages") or {}):
        out["site"].setdefault("pages", {})["ask"] = {"enabled": False}
        report["values"].append({"key": "site.pages.ask.enabled", "source": "fdo", "value": False, "note": "no question panel in the dashboard"})
    return out, report


def _ordered_panels(dash: dict, panels_by_id: dict, diag) -> list:
    """The dashboard's panels by position, then identifier; parts that are not panels and shared positions are reported."""
    ids = list(dash.get("panels") or [])
    for pid in ids:
        if pid not in panels_by_id:
            diag("compose.part_not_panel", "WARN", f"{pid} is listed by the dashboard but is not a Panel", panel=pid)
    panels = [panels_by_id[p] for p in ids if p in panels_by_id]
    if not panels:
        diag("compose.no_panel", "FAIL", "the dashboard lists no panel")
        raise CompositionError("the dashboard lists no panel")
    positions = {}
    for p in panels:
        pos = _int(p["fields"].get("position"))
        if pos is None:
            diag("order.no_position", "WARN", f"{p['id']} states no position; it is ordered after the positioned panels", panel=p["id"])
        elif pos in positions:
            diag("order.position_shared", "WARN", f"{p['id']} and {positions[pos]} share position {pos}; ordered by identifier", panel=p["id"])
        positions.setdefault(pos, p["id"])
    return sorted(panels, key=lambda p: (_int(p["fields"].get("position")) is None, _int(p["fields"].get("position")) or 0, p["id"]))


def _panel(root, cfg, source, panel, collections, values, diag) -> dict:
    """One panel: its plugin resolved through the allowlist, its inputs bound by count, its settings merged."""
    f = panel["fields"]
    entry = {"id": panel["id"], "name": f.get("name"), "position": _int(f.get("position")), "plugin": f.get("instrument"), "view": None,
             "status": "FAIL", "inputs": [], "settings": {}, "bound": {}}
    trusted = TRUSTED_VIEWS.get(str(entry["plugin"]))
    if not trusted:
        diag("plugin.untrusted", "FAIL", f"{entry['plugin']} is not in the allowlist of local views; the panel is not composed", panel=panel["id"])
        return entry
    prec = describe_recorded(root, cfg, source, entry["plugin"])
    pents = ((prec.descriptor or {}).get("extra") or {}).get("entities", [])
    plugins = [e for e in pents if e["type"] == "Plugin"]
    if len(plugins) != 1:
        diag("plugin.unreadable", "FAIL", f"{entry['plugin']}: {len(plugins)} Plugin entities read; one is needed", panel=panel["id"])
        return entry
    plugin = plugins[0]["fields"]
    entry["plugin_sha256"] = prec.record_sha256
    if str(plugin.get("version")) != trusted["version"]:
        diag("plugin.version_unsupported", "FAIL", f"{entry['plugin']} is version {plugin.get('version')}; this software implements {trusted['version']}", panel=panel["id"])
        return entry
    entry["view"] = trusted["view"]
    by_id = {e["id"]: e for e in pents}
    statuses = []
    for iid in plugin.get("inputs") or []:
        inp = (by_id.get(iid) or {}).get("fields") or {}
        kind, required = str(inp.get("kind")), str(inp.get("required")).lower() == "true"
        row = {"name": inp.get("name"), "kind": kind, "required": required, "status": "FAIL", "bound_to": None}
        if kind == "Collection":
            obj = f.get("object")
            candidates = [c for c in collections.values() if c["id"] == obj] if obj else list(collections.values())
            if len(candidates) > 1:
                row["status"], row["note"] = "INDETERMINATE", f"{len(candidates)} collections could serve; not decided"
                diag("bind.ambiguous", "INDETERMINATE", row["note"], panel=panel["id"], input=row["name"])
            elif not candidates:
                row["note"] = f"{obj or 'no object'} names no Collection entity"
                diag("bind.no_candidate", "FAIL" if required else "PARTIAL", row["note"], panel=panel["id"], input=row["name"])
                if not required:
                    row["status"] = "PARTIAL"
            else:
                members = [m for m in (candidates[0]["fields"].get("members") or []) if isinstance(m, str)]
                if not members:
                    row["note"] = f"{candidates[0]['id']} lists no members"
                    diag("bind.no_members", "FAIL", row["note"], panel=panel["id"], input=row["name"])
                else:
                    row["status"], row["bound_to"] = "PASS", candidates[0]["id"]
                    entry["bound"] = {"collection": candidates[0]["id"], "members": members, "modified": candidates[0]["fields"].get("modified")}
        elif kind in ("Object", "Claim"):
            row["status"], row["bound_to"], row["note"] = "PASS", "selection", "bound when the visitor opens a member of the listed collection"
        else:
            row["note"] = f"input kind {kind} is not one this software binds"
            diag("bind.kind_unknown", "FAIL" if required else "PARTIAL", row["note"], panel=panel["id"], input=row["name"])
        statuses.append(row["status"] if required or row["status"] != "FAIL" else "PARTIAL")
        entry["inputs"].append(row)
    defaults = {(by_id.get(sid) or {}).get("fields", {}).get("name"): (by_id.get(sid) or {}).get("fields", {}).get("default") for sid in (plugin.get("settings") or [])}
    overrides = {v["fields"].get("name"): v["fields"].get("value") for v in values.values() if panel["id"] in (v.get("holders") or [])}
    for name in overrides:
        if name not in defaults:
            diag("settings.undeclared", "WARN", f"setting {name!r} is not declared by {entry['plugin']}; ignored", panel=panel["id"])
    entry["settings"] = {k: overrides.get(k, v) for k, v in defaults.items() if k}
    entry["status"] = "FAIL" if "FAIL" in statuses else "INDETERMINATE" if "INDETERMINATE" in statuses else "PASS"
    return entry


def _portable(out, host, dash, values, report, diag) -> None:
    """Title, lead and style tokens from the Dashboard FDO, unless the host states them."""
    _take(out, host, report, ("site", "title"), dash.get("name"))
    _take(out, host, report, ("site", "hero", "lead"), dash.get("description"))
    for sid in dash.get("style") or []:
        v = (values.get(sid) or {}).get("fields") or {}
        name, value = v.get("name"), str(v.get("value") or "")
        token = STYLE_TOKENS.get(str(name))
        if not token:
            diag("style.unknown_token", "WARN", f"style value {name!r} is not a token this software applies", style=sid)
        elif not HEX.match(value) or (token in TEXT_TOKENS and contrast(value, "#ffffff") < 4.5):
            diag("style.rejected", "WARN", f"style {name}={value!r} is not a readable hex colour; not applied", style=sid)
        else:
            _take(out, host, report, ("site", "theme", token), value)


def _list_settings(out, host, settings: dict, report, diag) -> None:
    """The list plugin's settings as facets and categories, unless the host declares its own."""
    facets, categories = [], []
    for key in sorted(settings):
        value = str(settings[key] or "")
        parts = [p.strip() for p in value.split("|")]
        if key.startswith("facet."):
            if len(parts) < 2 or parts[1] not in FACET_CONCEPTS:
                diag("settings.facet_unknown_field", "WARN", f"{key}: {value!r} names no record field this software reads ({', '.join(FACET_CONCEPTS)})")
                continue
            facets.append({"id": re.sub(r"[^a-z0-9]+", "-", parts[1].lower()).strip("-"), "label": parts[0], "concept": parts[1],
                           "panel": "main" if len(parts) > 2 and parts[2] == "main" else "more"})
        elif key.startswith("category."):
            if len(parts) < 2 or not parts[1]:
                diag("settings.category_unreadable", "WARN", f"{key}: {value!r} is not 'label | type; type'")
                continue
            categories.append({"label": parts[0], "types": [t.strip() for t in parts[1].split(";") if t.strip()], "icon": "▤", "tone": TONES[len(categories) % len(TONES)]})
        elif key == "page_size" and value not in ("", "3"):
            diag("settings.unused", "WARN", f"page_size={value}: this software shows 3 cards per step")
    if facets:
        _take(out, host, report, ("facets",), facets, present=bool(host.get("facets")))
    if categories:
        _take(out, host, report, ("site", "categories"), categories)


def _take(out, host, report, path, value, present=None) -> None:
    """Set `path` from the FDO when the host does not state it; record the origin either way: fdo, agrees (host and FDO
    carry the same value) or host-override (they differ)."""
    if value in (None, "", []):
        return
    node = host
    for key in path[:-1]:
        node = node.get(key) or {} if isinstance(node, dict) else {}
    host_has = present if present is not None else (isinstance(node, dict) and node.get(path[-1]) not in (None, "", {}))
    key = ".".join(path)
    if host_has:
        same = isinstance(node, dict) and node.get(path[-1]) == value
        report["values"].append({"key": key, "source": "agrees" if same else "host-override", "fdo": _short(value)})
        return
    target = out
    for k in path[:-1]:
        target = target.setdefault(k, {})
    target[path[-1]] = value
    report["values"].append({"key": key, "source": "fdo", "value": _short(value)})


def _short(value):
    return value if isinstance(value, (str, int, float, bool)) else f"{len(value)} entries"


def _int(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
