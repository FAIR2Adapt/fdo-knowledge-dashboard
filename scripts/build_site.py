"""Build the static site: web/ plus data/catalog.json and data/records/<key>.json, read once through fdo-consume.
    python scripts/build_site.py --out dist [--config config/portugal-dashboard.yaml] [--refresh]
Exit status 2 and no output when the collection could not be read, so a published site keeps its last version."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from listing import capabilities, catalog as catalog_module, composition, config  # noqa: E402
from listing.config import LOOPBACK  # noqa: E402
from scripts.snapshot import locked  # noqa: E402

MANIFEST_UNKNOWN = "manifest.json does not describe this snapshot; outcomes unknown"


class SourceUnavailable(Exception):
    """The configured source could not be read; nothing is written."""


def build(out_dir: Path, cfg: dict, report: dict | None = None) -> dict:
    """`report` is the binding report of a composition from a Dashboard FDO; it is published next to the catalog.
    One build at a time per output directory: the lock is held from the read to the final swap."""
    mounted = out_dir.is_dir() and os.path.ismount(out_dir)          # a volume cannot be renamed: its contents are swapped instead
    with locked(out_dir / ".lock" if mounted else out_dir.with_name(out_dir.name + ".lock"), "site build"):
        return _build(out_dir, cfg, report, mounted)


def _build(out_dir: Path, cfg: dict, report: dict | None, mounted: bool) -> dict:
    catalog, records = catalog_module.build(ROOT, cfg)
    unavailable(catalog, records, cfg)
    staging = out_dir / ".staging" if mounted else out_dir.with_name(out_dir.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(ROOT / "web", staging)
    (staging / ".nojekyll").write_text("", encoding="utf-8")
    origins = service_origins(cfg["site"])
    if origins:                                            # the page may call exactly the configured service origins
        page = staging / "index.html"
        page.write_text(page.read_text(encoding="utf-8").replace("default-src 'self';", f"default-src 'self'; connect-src 'self' {' '.join(origins)};", 1), encoding="utf-8")
    data = staging / "data"
    (data / "records").mkdir(parents=True)
    if report is not None:
        catalog["composition"] = {"pid": report["dashboard"]["pid"], "keys_from_fdo": [v["key"] for v in report["values"] if v["source"] == "fdo"]}
    (data / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
    generation = catalog_module.source_snapshot_of(ROOT, cfg, catalog)
    if any(item["status"] == "unknown" for item in generation["items"]):
        print(MANIFEST_UNKNOWN, file=sys.stderr)
    (data / "generation.json").write_text(json.dumps(generation, ensure_ascii=False, indent=1), encoding="utf-8")
    (data / "capabilities.json").write_text(json.dumps(capabilities.declaration(ROOT, cfg, catalog), ensure_ascii=False, indent=1), encoding="utf-8")
    if report is not None:
        (data / "composition.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for key, record in records.items():
        (data / "records" / f"{key}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    if mounted:
        swap_contents(staging, out_dir)
    else:
        old = out_dir.with_name(out_dir.name + ".old")
        if old.exists():
            shutil.rmtree(old)
        if out_dir.exists():
            out_dir.replace(old)
        staging.replace(out_dir)                           # the complete site appears in one rename
        if old.exists():
            shutil.rmtree(old)
    return catalog


def swap_contents(staging: Path, out_dir: Path) -> None:
    """Replace the entries of a directory that cannot itself be renamed; `data/` moves last, so catalog, records and
    generation file change together and a server keeps the previous build until then."""
    old = out_dir / ".old"
    if old.exists():
        shutil.rmtree(old)
    old.mkdir()
    for entry in list(out_dir.iterdir()):
        if entry.name not in (".staging", ".old", ".lock"):
            entry.replace(old / entry.name)
    for entry in sorted(staging.iterdir(), key=lambda e: e.name == "data"):
        entry.replace(out_dir / entry.name)
    staging.rmdir()
    shutil.rmtree(old)


def service_origins(site: dict) -> list[str]:
    """The origins of the configured QA and discovery services (https, or loopback for a local mock), for the page's connect-src."""
    out = []
    search = site.get("search") or {}
    if search.get("provider") == "api" and isinstance(search.get("endpoint"), str) and search["endpoint"].startswith("https://"):
        parts = urlsplit(search["endpoint"])
        out.append(f"{parts.scheme}://{parts.netloc}")
    for block, keys in ((site.get("qa") or {}, ("endpoint", "capabilities_endpoint")), (site.get("discovery") or {}, ("endpoint", "capabilities_endpoint"))):
        if block.get("mode") in ("remote", "mock"):
            for key in keys:
                if isinstance(block.get(key), str):
                    parts = urlsplit(block[key])
                    out.append(f"{parts.scheme}://{parts.netloc}")
    return sorted(set(out))


def require_data_origin(cfg: dict, wanted: str | None) -> None:
    """A release names the data origin it expects; a configuration stating another one is refused before anything is read."""
    origin = cfg["source"].get("data_origin") or "unknown"
    if wanted and origin != wanted:
        raise SystemExit(f"build refused: this release requires source.data_origin {wanted!r}; the configuration states {origin!r}")
    site = cfg.get("site") or {}
    mocked = [name for name in ("qa", "discovery") if (site.get(name) or {}).get("mode") == "mock"]
    if wanted == "real" and mocked:
        raise SystemExit(f"build refused: a release with real data shows no mock service; site.{mocked[0]}.mode is 'mock'")
    loopback = [name for name in ("qa", "discovery") for key in ("endpoint", "capabilities_endpoint")
                if LOOPBACK.match(str((site.get(name) or {}).get(key) or ""))]
    if wanted and loopback:
        raise SystemExit(f"build refused: a published build cannot point site.{loopback[0]} at a loopback service; visitors' browsers would call their own machine")


def unavailable(catalog: dict, records: dict, cfg: dict | None = None) -> None:
    """Refuse a build whose source was not read: an unreadable collection, or members of which none can be shown."""
    collection = catalog["collection"]
    if catalog["source_kind"] == "collection":
        console = collection["console"]
        if console["outcome"] == "error" or console["statuses"]["resolution"] in ("FAIL", "INDETERMINATE"):
            raise SourceUnavailable(f"the collection could not be read: {collection['explanation']}")
        if not collection.get("members_total"):
            raise SourceUnavailable(f"the collection {collection.get('pid')} lists no member; nothing to publish")
    if not records and catalog["source_kind"] in ("pids", "community"):
        raise SourceUnavailable(f"no member is recorded under {((cfg or {}).get('source') or {}).get('recorded') or 'the recorded folder'}; record the source first (scripts/snapshot.py)")
    if records and not any(r["source"]["usable"] for r in records.values()):
        first = next(iter(records.values()))
        raise SourceUnavailable(f"none of the {len(records)} members can be shown: {first['source']['explanation']}")


def refresh(cfg: dict, timeout: float, accept_partial: bool = False, fetcher=None, searcher=None) -> dict:
    """Record the source again from the repository: a PID list in one run; a Dashboard FDO in two phases, its own PID
    first, then the members its collection names. A copy of the live folder taken before phase 1 is the rollback target
    of the whole refresh; a refused or failing phase 2 puts it back, so the live folder is never left between the two phases."""
    from scripts.snapshot import community_pids, fetch, snapshot  # noqa: E402  (scripts/ is a plain folder; imported here only)
    source = cfg["source"]
    if source["kind"] not in ("pids", "community", "dashboard") or not (source.get("crate_url") or source.get("crate_urls")) or not source.get("recorded"):
        raise SystemExit("--refresh needs source.kind pids, community or dashboard, with source.crate_url or source.crate_urls and source.recorded")
    folder, rules = ROOT / source["recorded"], source.get("crate_urls")
    record = lambda pids, keep=None: snapshot(folder, pids, source.get("crate_url"), timeout, accept_partial=accept_partial, rules=rules, keep=keep, fetcher=fetcher or fetch)
    if source["kind"] in ("pids", "community"):
        searched = None
        pids = source.get("pids")
        if source["kind"] == "community":
            pids, searched = community_pids(source["community"], source["search"], timeout, max_members=source.get("max_members", 100), getter=searcher)
            if not pids:
                raise SystemExit(f"refresh refused: the search for {source['search']} found no public member of the community {source['community']!r}; the previous snapshot is kept")
        _, manifest = record(pids)
        if not manifest["promoted"]:
            raise SystemExit(f"refresh refused: {manifest['counts']}; the previous snapshot is kept")
        if searched:
            (folder / "community.json").write_text(json.dumps(searched, ensure_ascii=False, indent=1), encoding="utf-8")
        return manifest
    before, previous = folder.with_name(folder.name + ".prerefresh"), folder.parent / f".{folder.name}.previous"
    if before.exists():
        shutil.rmtree(before)
    if folder.is_dir():
        shutil.copytree(folder, before)
    index, manifest = record([source["pid"]], keep=catalog_module.snapshot_index(ROOT, cfg))
    if not manifest["promoted"]:
        if before.exists():
            shutil.rmtree(before)
        raise SystemExit(f"refresh refused: {manifest['counts']}; the previous snapshot is kept")
    def restore() -> None:
        shutil.rmtree(folder)
        if before.is_dir():
            before.replace(folder)
    try:
        composed, report = composition.compose(ROOT, cfg)                 # the dashboard just recorded names the members
        named = {source["pid"], *(p["plugin"] for p in report["panels"] if p.get("plugin"))}
        _, manifest = record(composed["source"]["pids"], keep={pid: e for pid, e in index.items() if pid in named})
    except (Exception, SystemExit) as err:
        restore()
        raise SystemExit(f"refresh refused: {err}; the snapshot before the refresh is kept") from err
    if not manifest["promoted"]:
        restore()
        raise SystemExit(f"refresh refused: {manifest['counts']}; the snapshot before the refresh is kept")
    if before.is_dir():
        if previous.exists():
            shutil.rmtree(previous)
        before.replace(previous)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static (GitHub Pages) site of the listing.")
    parser.add_argument("--out", default="dist")
    parser.add_argument("--config", default=None, help="a configuration under config/ (default config/portugal-dashboard.yaml)")
    parser.add_argument("--refresh", action="store_true", help="record the members again before building: source.pids, or the community search, from source.crate_url into source.recorded")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--accept-partial", action="store_true", help="with --refresh: promote when at least one PID was recorded")
    parser.add_argument("--require-data-origin", choices=config.ORIGINS, default=None, help="refuse a configuration whose source.data_origin differs")
    args = parser.parse_args()
    out = Path(args.out)
    cfg = config.load(ROOT, args.config)
    report = None
    if cfg["source"]["kind"] == "dashboard":                 # a Dashboard FDO names the members and the portable settings
        try:
            cfg, report = composition.compose(ROOT, cfg)
        except composition.CompositionError as exc:
            print(f"build refused: the Dashboard FDO could not be composed: {exc}", file=sys.stderr)
            sys.exit(2)
        config.check_site(ROOT, cfg["site"])
    require_data_origin(cfg, args.require_data_origin)
    if args.refresh:
        refresh(cfg, args.timeout, args.accept_partial)
    try:
        cat = build((out if out.is_absolute() else ROOT / out).resolve(), cfg, report)
    except SourceUnavailable as exc:
        print(f"build refused: {exc}", file=sys.stderr)
        sys.exit(2)
    counts = cat["counts"]
    print(f"site -> {out}: {counts['usable']} records shown, {counts['not_usable']} not usable, {len(cat['facets'])} facets; "
          f"generation {cat['generation']['id']} ({cat['generation']['data_origin']} data)")
    if report:
        panels = ", ".join(f"{p['view'] or p['plugin']} {p['status']}" for p in report["panels"])
        print(f"composition -> {report['dashboard']['pid']}: panels [{panels}]; {sum(v['source'] == 'fdo' for v in report['values'])} values from the FDO, "
              f"{sum(v['source'] == 'agrees' for v in report['values'])} agree with the host, {sum(v['source'] == 'host-override' for v in report['values'])} host overrides, {len(report['diagnostics'])} diagnostics")


if __name__ == "__main__":
    main()
