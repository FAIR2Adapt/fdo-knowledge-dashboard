"""The capabilities declaration: what the software implements, what this deployment configures and what is experimental,
generated from the code's constants, the contracts, the maps and the configuration."""
from __future__ import annotations

from pathlib import Path

import yaml

from . import __version__
from .composition import TRUSTED_VIEWS
from .config import DISCOVERY_CAPABILITIES, DISCOVERY_MODES, FACET_CONCEPTS, ORIGINS, QA_CAPABILITIES, QA_MODES, SEARCH_PROVIDERS, SOURCE_KINDS
from .delivery import LIMIT_MAX, QUERY_MAX, SEARCH_SCHEMA
from .reader import maps_known
from .validate import MAX_FACET_VALUES, MAX_PARAMS, MAX_PID, MAX_TARGET, PID_SCHEMES

SCHEMA = "fdo-knowledge-dashboard/capabilities/1"
MOCK_TRUTH = ("in the page: generates nothing and cites nothing, returns search matches as related resources; "
              "local HTTP mock: placeholder answers labelled as such, citing the site's records with the evidence their records state; "
              "never scientific grounding")
UNSUPPORTED = ["server-side storage other than the build directory", "a second search index (SQLite, Solr)", "plugin code loaded from a URL",
               "user accounts, editing or publishing", "resolving or validating FDOs beyond fdo-consume", "scientific verification of any statement"]


def contracts(root: Path, cfg: dict) -> list[dict]:
    """The consumer contracts with their levels as the files state them (must = required, should/may = optional)."""
    out = []
    for name in cfg["reading"]["contracts"].values():
        doc = yaml.safe_load((root / cfg["reading"]["contracts_dir"] / f"{name}.yaml").read_text(encoding="utf-8"))
        needs = doc.get("needs") or []
        out.append({"id": doc.get("contract_id", name), "version": doc.get("version"), "owner": "this repository",
                    "required": [n["term"] for n in needs if n.get("level") == "must"], "optional": [n["term"] for n in needs if n.get("level") in ("should", "may")],
                    "entities": sorted({e for n in needs for e in (n.get("entities") or [])})})
    return out


def declaration(root: Path, cfg: dict, catalog: dict) -> dict:
    site, source = cfg["site"], cfg["source"]
    qa, search, discovery = site.get("qa") or {}, site.get("search") or {}, site.get("discovery") or {}
    qa_mode = qa.get("mode", "disabled")
    qa_caps = {k: qa.get("capabilities", {}).get(k, False) is True for k in QA_CAPABILITIES} if qa_mode == "remote" else None
    configured, endpoint = qa_mode == "remote" and qa.get("capabilities") is not None, qa_mode == "remote" and bool(qa.get("capabilities_endpoint"))
    caps_source = "configuration+endpoint" if configured and endpoint else "configuration" if configured else "endpoint" if endpoint else None
    return {
        "schema": SCHEMA, "software": {"name": "fdo-knowledge-dashboard", "version": __version__}, "reader": catalog["reader"],
        "generation": catalog["generation"],
        "data_origins": {"implemented": list(ORIGINS), "configured": catalog["generation"]["data_origin"]},
        "source_kinds": {"implemented": list(SOURCE_KINDS), "experimental": ["dashboard"], "configured": source["kind"]},
        "profile_maps": [{**m, "implemented": True, "normative": m["status"] == "published"} for m in maps_known(root, cfg)],
        "fallback_map": cfg["reading"].get("fallback_map"), "overlay": cfg["reading"].get("profile_overlay"),
        "consumer_contracts": contracts(root, cfg),
        "record": {"schema": "fdo-knowledge-dashboard/record/1", "readiness": ["usable", "not_usable"], "statuses_carried": ["resolution", "validation", "compatibility", "delivery"],
                   "claim_kinds": ["claim", "statement", "nanopublication", "linked_nanopublication"], "inferred_flag": True},
        "views": [{"kind": view["view"], "version": view["version"], "plugin_pid": pid, "implemented": True, "experimental": True, "note": "placeholder plugin identifier; composition from a Dashboard FDO is an experiment"}
                  for pid, view in TRUSTED_VIEWS.items()],
        "facets": {"concepts": list(FACET_CONCEPTS), "configured": [f["id"] for f in cfg["facets"]],
                   "semantics": {"within_facet": "OR", "across_facets": "AND", "counts": "over the result with the facet's own selection removed"}},
        "search": {"schema": SEARCH_SCHEMA, "providers": {"static": {"implemented": True, "where": "browser"}, "api": {"implemented": True, "where": "server", "route": "/api/v1/search"}},
                   "configured": search.get("provider", "static"), "endpoint": search.get("endpoint") if search.get("provider") == "api" else None,
                   "limits": {"query_chars": QUERY_MAX, "limit_max": LIMIT_MAX, "facet_values_per_facet": MAX_FACET_VALUES, "parameters": MAX_PARAMS, "target_chars": MAX_TARGET}},
        "resource_detail": {"schema": "fdo-knowledge-dashboard/resource-detail/1", "routes": ["/api/v1/resources/<key>", "/api/v1/resources?pid="], "pid_schemes": list(PID_SCHEMES), "pid_max_chars": MAX_PID, "dereference_at_request_time": False},
        "qa": {"contract": "fdo-knowledge-dashboard/qa/2", "modes": {"disabled": {"implemented": True}, "mock": {"implemented": True, "truth": MOCK_TRUTH},
                                                               "remote": {"implemented": True, "requires": "site.qa.capabilities or site.qa.capabilities_endpoint; unknown is unsupported"}},
               "configured": qa_mode, "capabilities": qa_caps, "capabilities_source": caps_source, "capability_keys": list(QA_CAPABILITIES),
               "capabilities_rule": "the capabilities are the configured values; a declared endpoint may only narrow them, and an endpoint that cannot be read leaves every capability unsupported"},
        "discovery": {"modes": list(DISCOVERY_MODES), "configured": discovery.get("mode", "disabled"), "capability_keys": list(DISCOVERY_CAPABILITIES),
                      "membership": "external results are never members of the collection"},
        "deployment": {"targets": ["github-pages", "server", "container"], "served_routes": ["/data/*", "/api/v1/health", "/api/v1/generation", "/api/v1/capabilities", "/api/v1/search", "/api/v1/facets", "/api/v1/resources"]},
        "unsupported": UNSUPPORTED,
    }
