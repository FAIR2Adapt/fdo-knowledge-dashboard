"""The listing's own configuration: site texts, where the members come from, how they are read, which facets are shown."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

CONFIG = "config/portugal-dashboard.yaml"
SOURCE_KINDS = ("collection", "pids", "community", "dashboard")   # community: public objects of a ROHub community (scripts/snapshot.py); dashboard: members named by a Dashboard FDO (composition.py)
ORIGINS = ("real", "synthetic", "experimental")           # source.data_origin: what the members are; stated in every build output
FACET_CONCEPTS = ("resource_type", "keywords", "year", "profile", "authors", "date", "status")   # record fields a facet may read
THEME_TOKENS = ("primary", "deep", "sage", "orange", "blue", "purple")                            # the colours a deployment may set
TEXT_TOKENS = ("primary", "deep")                                                                 # used for text on white: 4.5:1 needed
LAYOUTS = ("cards", "catalogue")                                                                  # site.resources_layout
PAGES = ("about", "how", "resources", "ask")                                                      # pages a deployment may hide or relabel
QA_MODES = ("disabled", "mock", "remote")                                                         # site.qa.mode; mock needs a visible label
QA_CAPABILITIES = ("single_turn", "history", "citations", "scope", "generation")                   # what a provider may be declared to support
SEARCH_PROVIDERS = ("static", "api")                                                             # site.search.provider; api needs a trusted endpoint
HTTPS = re.compile(r"^https://[^\s]+$")
LOOPBACK = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(/[^\s]*)?$")   # local mock services only
DISCOVERY_MODES = ("disabled", "mock", "remote")
DISCOVERY_CAPABILITIES = ("paging", "relations", "pids")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
TOPIC_PLACEHOLDERS = tuple({"label": f"Topic {n}", "icon": "◌", "why": "No topic is configured for this deployment yet"} for n in (1, 2, 3))
ASSET = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")                                            # a relative path under web/, no scheme, no ".."
READING = {"contracts": {"collection": "listing-collection-v1", "record": "listing-record-v1", "claims": "listing-claims-v1"},
           "contracts_dir": "config/contracts", "maps_dir": "config/maps", "profile_overlay": None, "profile_labels": {},
           "max_members": 5000, "map_notes": {}}
TEXT_MAX = 300                                                                                     # site.project, site.funding, a map note


def load(root: Path, path: str | None = None) -> dict:
    """Read the configuration; a wrong source or facet is refused at start, never shown as an empty or garbled page."""
    cfg = yaml.safe_load((Path(path) if path else root / CONFIG).read_text(encoding="utf-8")) or {}
    cfg["reading"] = {**READING, **(cfg.get("reading") or {})}
    cfg["reading"]["contracts"] = {**READING["contracts"], **(cfg["reading"].get("contracts") or {})}
    cfg.setdefault("site", {})
    cfg["site"].setdefault("funding", None)
    if isinstance(cfg["site"].get("footer"), dict):
        cfg["site"]["footer"].setdefault("partners_confirmed", False)
    cfg.setdefault("facets", [])
    cfg.setdefault("facets_without_source", [dict(t) for t in TOPIC_PLACEHOLDERS])
    cfg.setdefault("diagnostics_open", False)
    source = cfg.get("source") or {}
    if source.get("kind") not in SOURCE_KINDS:
        raise ValueError(f"source.kind must be one of {SOURCE_KINDS}, not {source.get('kind')!r}")
    if source["kind"] == "collection" and not source.get("pid"):
        raise ValueError("source.kind 'collection' needs source.pid")
    if source["kind"] == "pids" and not source.get("pids"):
        raise ValueError("source.kind 'pids' needs a non-empty source.pids list")
    if source["kind"] == "pids" and not (isinstance(source["pids"], list) and all(isinstance(p, str) and p.strip() for p in source["pids"])):
        raise ValueError("source.pids is a list of identifiers (strings)")
    if source.get("recorded") is not None and not (isinstance(source["recorded"], str) and source["recorded"].strip()):
        raise ValueError("source.recorded is the path of a recorded folder (a string)")
    if source["kind"] == "community":
        if not (isinstance(source.get("community"), str) and source["community"].strip()):
            raise ValueError("source.kind 'community' needs source.community: the ROHub community name as ROHub states it")
        terms = source.get("search")
        if not (isinstance(terms, list) and terms and all(isinstance(t, str) and t.strip() for t in terms)):
            raise ValueError("source.kind 'community' needs source.search: a list of search terms whose public hits are kept when they belong to the community")
        if not source.get("recorded"):
            raise ValueError("source.kind 'community' needs source.recorded: the folder scripts/snapshot.py --community wrote")
        if isinstance(source.get("max_members", 100), bool) or not isinstance(source.get("max_members", 100), int) or source.get("max_members", 100) < 1:
            raise ValueError("source.max_members must be a positive integer")
    if source["kind"] == "dashboard" and not (source.get("pid") and source.get("recorded")):
        raise ValueError("source.kind 'dashboard' needs source.pid (the Dashboard FDO) and source.recorded (where the dashboard and the members are recorded)")
    if source["kind"] == "dashboard":
        source.setdefault("dashboard_dir", source["recorded"])        # plugin and dashboard crates may sit in their own folder
    for n, rule in enumerate(source.get("crate_urls") or [], 1):
        if not isinstance(rule, dict) or not isinstance(rule.get("match"), str) or not isinstance(rule.get("url"), str) or not ("{pid}" in rule["url"] or "{uuid}" in rule["url"]):
            raise ValueError(f"source.crate_urls[{n}] needs match (a regular expression) and url (a template with {{pid}} or {{uuid}})")
        try:
            re.compile(rule["match"])
        except re.error as exc:
            raise ValueError(f"source.crate_urls[{n}].match is not a regular expression: {exc}") from None
    if source.get("data_origin") is not None and source["data_origin"] not in ORIGINS:
        raise ValueError(f"source.data_origin must be one of {ORIGINS}, not {source.get('data_origin')!r}")
    if source.get("data_origin") == "synthetic" and not cfg["site"].get("demo_notice"):
        raise ValueError("source.data_origin 'synthetic' needs site.demo_notice: synthetic records are never shown without a banner")
    if source.get("data_origin") == "real" and cfg["site"].get("demo_notice"):
        raise ValueError("source.data_origin 'real' with site.demo_notice: a demo banner over real records, or real data in a demo; state one")
    check_site(root, cfg["site"])
    notes = cfg["reading"]["map_notes"]
    if notes:
        from .reader import maps_known
        known = {m["id"] for m in maps_known(root, cfg)}
        if not isinstance(notes, dict):
            raise ValueError("reading.map_notes is a map of map id -> sentence")
        for map_id, sentence in notes.items():
            if map_id not in known:
                raise ValueError(f"reading.map_notes names {map_id!r}, which is not a known map; known: {', '.join(sorted(known))}")
            if not isinstance(sentence, str) or not sentence.strip() or len(sentence) > TEXT_MAX:
                raise ValueError(f"reading.map_notes.{map_id} must be a sentence of at most {TEXT_MAX} characters")
    cfg["api"] = {"allowed_origins": [], "rate_per_minute": 120, "behind_proxy": False, **(cfg.get("api") or {})}
    if not isinstance(cfg["api"]["behind_proxy"], bool):
        raise ValueError("api.behind_proxy must be true or false")
    for origin in cfg["api"]["allowed_origins"]:
        if origin != "*" and not (isinstance(origin, str) and re.match(r"^https://[^/]+$", origin)):
            raise ValueError(f"api.allowed_origins entries are https origins without a path, or '*', not {origin!r}")
    if not isinstance(cfg["api"]["rate_per_minute"], int) or cfg["api"]["rate_per_minute"] < 1:
        raise ValueError("api.rate_per_minute must be a positive integer")
    seen = set()
    for n, facet in enumerate(cfg["facets"], 1):
        missing = [k for k in ("id", "label", "concept") if not facet.get(k)]
        if missing:
            raise ValueError(f"facet {n} lacks {', '.join(missing)}")
        if facet["concept"] not in FACET_CONCEPTS:
            raise ValueError(f"facet {facet['id']!r} reads {facet['concept']!r}; a facet reads one of {FACET_CONCEPTS}")
        if facet["id"] in seen:
            raise ValueError(f"facet id {facet['id']!r} is used twice")
        seen.add(facet["id"])
    return cfg


def check_site(root: Path, site: dict) -> None:
    """Deployment choices are checked at start: colours are hex and readable, pages are known, assets exist under web/."""
    theme = site.get("theme") or {}
    for token, value in theme.items():
        if token not in THEME_TOKENS:
            raise ValueError(f"site.theme.{token} is not a theme token; tokens: {THEME_TOKENS}")
        if not isinstance(value, str) or not HEX.match(value):
            raise ValueError(f"site.theme.{token} must be a hex colour like #286d32, not {value!r}")
        if token in TEXT_TOKENS and contrast(value, "#ffffff") < 4.5:
            raise ValueError(f"site.theme.{token} {value} has {contrast(value, '#ffffff'):.1f}:1 contrast on white; 4.5:1 is needed for text")
    if site.get("resources_layout", "cards") not in LAYOUTS:
        raise ValueError(f"site.resources_layout must be one of {LAYOUTS}, not {site.get('resources_layout')!r}")
    for page, spec in (site.get("pages") or {}).items():
        if page not in PAGES:
            raise ValueError(f"site.pages.{page} is not a page; pages: {PAGES}")
        if page == "resources" and isinstance(spec, dict) and spec.get("enabled") is False:
            raise ValueError("site.pages.resources cannot be disabled; the list is the site")
    for key in ("project", "funding"):
        value = site.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > TEXT_MAX or "<" in value):
            raise ValueError(f"site.{key} must be plain text of at most {TEXT_MAX} characters")
    footer = site.get("footer")
    if footer is not None and (not isinstance(footer, dict) or not isinstance(footer.get("partners_confirmed", False), bool)):
        raise ValueError("site.footer.partners_confirmed must be true or false")
    qa = site.get("qa") or {}
    if qa.get("mode", "disabled") not in QA_MODES:
        raise ValueError(f"site.qa.mode must be one of {QA_MODES}, not {qa.get('mode')!r}")
    if qa.get("mode") == "mock" and not qa.get("demo_label"):
        raise ValueError("site.qa.mode 'mock' needs site.qa.demo_label: a mock is always labelled on the page")
    if qa.get("mode") == "remote" and not (isinstance(qa.get("endpoint"), str) and HTTPS.match(qa["endpoint"])):
        raise ValueError("site.qa.mode 'remote' needs an https site.qa.endpoint")
    caps = qa.get("capabilities")
    if caps is not None:
        if not isinstance(caps, dict) or any(k not in QA_CAPABILITIES or not isinstance(v, bool) for k, v in caps.items()):
            raise ValueError(f"site.qa.capabilities is a map of booleans over {QA_CAPABILITIES}")
    if qa.get("mode") == "mock" and qa.get("endpoint") is not None and not (isinstance(qa["endpoint"], str) and LOOPBACK.match(qa["endpoint"])):
        raise ValueError("site.qa.endpoint in mode 'mock' must be a loopback URL of a local mock service (127.0.0.1, localhost)")
    allowed = (HTTPS, LOOPBACK) if qa.get("mode") == "mock" else (HTTPS,)
    if qa.get("capabilities_endpoint") is not None and not (isinstance(qa["capabilities_endpoint"], str) and any(r.match(qa["capabilities_endpoint"]) for r in allowed)):
        raise ValueError("site.qa.capabilities_endpoint must be an https URL (or a loopback URL in mode 'mock')")
    if qa.get("mode") == "remote" and caps is None and not qa.get("capabilities_endpoint"):
        raise ValueError("site.qa.mode 'remote' needs site.qa.capabilities (trusted) or site.qa.capabilities_endpoint; unknown capabilities are unsupported")
    search = site.get("search") or {}
    if search.get("provider", "static") not in SEARCH_PROVIDERS:
        raise ValueError(f"site.search.provider must be one of {SEARCH_PROVIDERS}")
    endpoint = search.get("endpoint")
    if search.get("provider") == "api" and not (isinstance(endpoint, str) and (HTTPS.match(endpoint) or (ASSET.match(endpoint) and ".." not in endpoint))):
        raise ValueError("site.search.provider 'api' needs site.search.endpoint: an https URL of a trusted server, or a path such as api/v1 on the same server")
    discovery = site.get("discovery") or {}
    if discovery.get("mode", "disabled") not in DISCOVERY_MODES:
        raise ValueError(f"site.discovery.mode must be one of {DISCOVERY_MODES}, not {discovery.get('mode')!r}")
    if discovery.get("mode") == "remote" and not (isinstance(discovery.get("endpoint"), str) and HTTPS.match(discovery["endpoint"]) and "{q}" in discovery["endpoint"]):
        raise ValueError("site.discovery.mode 'remote' needs an https site.discovery.endpoint with a {q} placeholder")
    if discovery.get("mode") == "mock" and discovery.get("endpoint") is not None and not (isinstance(discovery["endpoint"], str) and LOOPBACK.match(discovery["endpoint"]) and "{q}" in discovery["endpoint"]):
        raise ValueError("site.discovery.endpoint in mode 'mock' must be a loopback URL of a local mock service with a {q} placeholder")
    dallowed = (HTTPS, LOOPBACK) if discovery.get("mode") == "mock" else (HTTPS,)
    if discovery.get("capabilities_endpoint") is not None and not (isinstance(discovery["capabilities_endpoint"], str) and any(r.match(discovery["capabilities_endpoint"]) for r in dallowed)):
        raise ValueError("site.discovery.capabilities_endpoint must be an https URL (or a loopback URL in mode 'mock')")
    dcaps = discovery.get("capabilities")
    if dcaps is not None and (not isinstance(dcaps, dict) or any(k not in DISCOVERY_CAPABILITIES or not isinstance(v, bool) for k, v in dcaps.items())):
        raise ValueError(f"site.discovery.capabilities is a map of booleans over {DISCOVERY_CAPABILITIES}")
    for name, spec in (site.get("links") or {}).items():
        url = spec.get("url") if isinstance(spec, dict) else spec
        if not isinstance(url, str) or not re.match(r"^https?://", url):
            raise ValueError(f"site.links.{name}.url must be an http(s) URL, not {url!r}")
    for key, path in (("site.background.image", (site.get("background") or {}).get("image")), ("site.brand.logo.image", ((site.get("brand") or {}).get("logo") or {}).get("image"))):
        if path is None:
            continue
        if not isinstance(path, str) or not ASSET.match(path) or ".." in path:
            raise ValueError(f"{key} must be a relative path under web/ such as assets/x.png, not {path!r}")
        if not (root / "web" / path).is_file():
            raise ValueError(f"{key}: web/{path} does not exist")


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio of two hex colours."""
    def lum(h: str) -> float:
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)
