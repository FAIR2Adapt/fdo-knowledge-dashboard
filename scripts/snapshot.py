r"""Record PIDs as a folder fdo-consume reads as a recorded source (pids.json + objects/<key>/ro-crate-metadata.json).
A run is staged and promoted whole; the previous folder is kept for --rollback. Outcomes per PID: recorded, gone
(404/410), restricted (401/403), failed (after retries on transient errors; --accept-partial keeps the last copy), kept
(carried from the previous run with --keep-existing). Where a PID's crate is served: --crate-url (default template) and
--crate-rule REGEX TEMPLATE (first matching rule wins); {pid} is the PID, {uuid} its last path segment, applied only when
that segment is UUID-shaped; a PID with a query, a fragment or a ".." segment gets no URL.
    python scripts/snapshot.py --out snapshots/rohub --pid <PID> [--pid ...] --crate-rule '^https://w3id\.org/ro-id/' 'https://api.rohub.org/api/ros/{uuid}/crate/download/'
The fetch is fdo-consume's live source: public hosts only, redirects re-checked, bytes bounded (--max-bytes).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fdo_consume import AccessError, Limits  # noqa: E402
from fdo_consume.sources.live import locate_live  # noqa: E402  (the library's locator; not a public plugin API yet)
from listing.delivery import canonical_pid  # noqa: E402
from listing.records import key_of  # noqa: E402

MANIFEST_SCHEMA = "fdo-knowledge-dashboard/snapshot-manifest/1"
ROHUB_SEARCH = "https://api.rohub.org/api/search/ros/?page_size=100&search={term}"   # ROHub's search; its hits carry `communities` and `access_mode`
PUBLIC_MODES = ("PUBLIC", "OPEN")
SEARCH_PAGES = 20                                                # at most 2,000 hits are read per search term
SEARCH_BYTES = 5_000_000
MAX_BYTES = Limits().max_crate_bytes
TRANSIENT_HTTP = ("HTTP 408", "HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


@contextlib.contextmanager
def locked(path: Path, what: str):
    """An exclusive lock on `path` for the block; a second holder exits with a message instead of writing concurrently."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise SystemExit(f"another build is running ({what} locked by {path.name}); try again when it has finished") from None
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def fetch(url: str, timeout: float, max_bytes: int = MAX_BYTES) -> bytes:
    """The crate at `url` as fdo-consume located it, re-serialised as JSON."""
    located = locate_live(url, {"timeout": timeout}, Limits(max_crate_bytes=max_bytes))
    return json.dumps(located.crate, ensure_ascii=False, indent=1).encode("utf-8")


def fetch_json(url: str, timeout: float, max_bytes: int = SEARCH_BYTES) -> dict:
    """One bounded GET of a JSON document over https (the repository's search API)."""
    import urllib.request
    if not url.startswith("https://"):
        raise ValueError(f"the search URL must be https: {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "fdo-knowledge-dashboard snapshot"}), timeout=timeout) as res:
        body = res.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError(f"the search answer exceeds {max_bytes} bytes")
    return json.loads(body)


def community_pids(name: str, terms: list[str], timeout: float, *, getter=None, max_members: int = 100, search_url: str = ROHUB_SEARCH) -> tuple[list[str], dict]:
    """The PIDs of the public research objects that the repository's search returns for `terms` and that belong to the
    community `name`, each once in order of first appearance, at most `max_members`; plus a record of the search."""
    from urllib.parse import quote
    get = getter or (lambda url: fetch_json(url, timeout))
    host = urlsplit(search_url).netloc
    pids, seen, record = [], set(), {"community": name, "search": list(terms), "taken": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "hits": 0, "members_found": 0}
    for term in terms:
        url = search_url.format(term=quote(term))
        for _ in range(SEARCH_PAGES):
            page = get(url)
            if not isinstance(page, dict) or not isinstance(page.get("results"), list):
                raise ValueError(f"the search answer of {urlsplit(url).netloc} is not an object with a results list")
            for hit in page["results"]:
                if not isinstance(hit, dict):
                    continue
                record["hits"] += 1
                communities = hit.get("communities") if isinstance(hit.get("communities"), list) else []
                pid = f"https://w3id.org/ro-id/{str(hit['identifier']).lower()}" if UUID.match(str(hit.get("identifier"))) else None   # the repository's own identifier scheme, never a free link
                if name in communities and hit.get("access_mode") in PUBLIC_MODES and pid and canonical_pid(pid) not in seen:
                    seen.add(canonical_pid(pid)); pids.append(pid)
            url = page.get("next") if isinstance(page.get("next"), str) and urlsplit(page["next"]).netloc == host and page["next"].startswith("https://") else None
            if not url:
                break
    record["members_found"], record["members_kept"] = len(pids), min(len(pids), max_members)
    return pids[:max_members], record


def resolve_url(pid: str, crate_url: str | None, rules=None) -> str | None:
    """The URL that serves a PID's crate: the first rule whose pattern matches the PID, else the default template; None when
    neither applies, when the PID carries a query or a fragment, or when a {uuid} template meets a tail that is not
    UUID-shaped or a ".." segment. A URL is never guessed for an identifier the rules do not cover."""
    parts = urlsplit(pid)
    if parts.query or parts.fragment:
        return None
    template = next((r["url"] for r in (rules or []) if re.search(r["match"], pid)), crate_url)
    if not template:
        return None
    tail = pid.rstrip("/").rsplit("/", 1)[-1]
    if "{uuid}" in template and (not UUID.match(tail) or ".." in pid.split("/")):
        return None
    return template.format(pid=pid, uuid=tail)


def kind_of(exc: AccessError) -> str:
    """gone (404/410), restricted (401/403), transient (worth a retry) or failed."""
    if exc.code == "resolution.gone":
        return "gone"
    if exc.code == "transport.http_error" and ("HTTP 401" in exc.message or "HTTP 403" in exc.message):
        return "restricted"
    if exc.code in ("transport.timeout", "transport.connection") or any(h in exc.message for h in TRANSIENT_HTTP):
        return "transient"
    return "failed"


def record_one(pid: str, url: str, timeout: float, max_bytes: int, fetcher, attempts: int, backoff: float, sleep) -> dict:
    """One PID, retried on transient errors with exponential backoff; a crate that is not JSON is never recorded."""
    entry = {"pid": pid, "canonical_pid": canonical_pid(pid), "fetched_from": url, "attempts": 0}
    for n in range(1, attempts + 1):
        entry["attempts"] = n
        try:
            data = fetcher(url, timeout, max_bytes)
            json.loads(data.decode("utf-8-sig"))
        except AccessError as exc:
            kind = kind_of(exc)
            entry["reason"] = f"{exc.code}: {exc.message}"
            if kind == "transient" and n < attempts:
                sleep(backoff * 2 ** (n - 1))
                continue
            entry["outcome"] = "failed" if kind == "transient" else kind
            return entry
        except (UnicodeDecodeError, ValueError) as exc:
            entry.update(outcome="failed", reason=f"object.not_json: {exc}")
            return entry
        except Exception as exc:                                  # one bad object never stops the batch
            entry.update(outcome="failed", reason=f"{type(exc).__name__}: {exc}")
            return entry
        entry.update(outcome="recorded", bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), data=data)
        return entry
    return entry


def snapshot(out: Path, pids: list[str], crate_url: str | None, timeout: float, *, fetcher=fetch, attempts: int = 3, backoff: float = 0.5,
             sleep=time.sleep, accept_partial: bool = False, max_bytes: int = MAX_BYTES, rules=None, keep: dict | None = None) -> tuple[dict, dict]:
    """Stage every PID, then promote the staging folder whole. `keep` carries entries of the previous index that this run
    does not record again (their files are copied). Returns the index fdo-consume reads (the previous one when nothing was
    promoted) and the manifest (one entry per PID, `promoted`, `generation`)."""
    out = Path(out)
    staging, previous = out.parent / f".{out.name}.staging", out.parent / f".{out.name}.previous"
    old = json.loads((out / "pids.json").read_text(encoding="utf-8")) if (out / "pids.json").is_file() else {}
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "objects").mkdir(parents=True)
    taken = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    index, entries = {}, []
    wanted = list(dict.fromkeys(p.strip() for p in pids if isinstance(p, str) and p.strip()))
    for pid, previous_entry in (keep or {}).items():
        if pid in wanted or not isinstance(previous_entry, dict):
            continue
        folder = out / "objects" / previous_entry.get("fixture", "-")
        if folder.is_dir():
            shutil.copytree(folder, staging / "objects" / previous_entry["fixture"])
            index[pid] = dict(previous_entry)
            entries.append({"pid": pid, "canonical_pid": canonical_pid(pid), "outcome": "kept", "fixture": previous_entry["fixture"], "sha256": previous_entry.get("sha256"), "taken": previous_entry.get("taken")})
    for pid in wanted:
        url = resolve_url(pid, crate_url, rules)
        if not url:
            entries.append({"pid": pid, "canonical_pid": canonical_pid(pid), "fetched_from": None, "attempts": 0, "outcome": "failed", "reason": "no resolution rule for this identifier", "taken": taken})
            print(f"  {pid} -> failed: no resolution rule", file=sys.stderr)
            continue
        entry = record_one(pid, url, timeout, max_bytes, fetcher, attempts, backoff, sleep)
        entry["taken"] = taken
        key = key_of(pid)
        if entry["outcome"] == "recorded":
            data = entry.pop("data")
            (staging / "objects" / key).mkdir()
            (staging / "objects" / key / "ro-crate-metadata.json").write_bytes(data)
            entry.update(fixture=key, changed=(old.get(pid) or {}).get("sha256") != entry["sha256"])
            index[pid] = {"fixture": key, "fetched_from": url, "sha256": entry["sha256"], "taken": taken}
        elif entry["outcome"] == "failed" and accept_partial and (out / "objects" / (old.get(pid) or {}).get("fixture", "-") / "ro-crate-metadata.json").is_file():
            shutil.copytree(out / "objects" / old[pid]["fixture"], staging / "objects" / old[pid]["fixture"])
            index[pid] = dict(old[pid])
            entry.update(outcome="carried_forward", fixture=old[pid]["fixture"], sha256=old[pid].get("sha256"), carried_from=old[pid].get("taken"))
        entries.append(entry)
        print(f"  {pid} -> {entry['outcome']}" + (f" ({entry['bytes']} bytes)" if entry["outcome"] == "recorded" else f": {entry.get('reason', '')}"), file=sys.stderr)
    counts = Counter(e["outcome"] for e in entries)
    promoted = counts["recorded"] > 0 and (counts["failed"] == 0 or accept_partial)
    generation = hashlib.sha256("\n".join(sorted(f"{p} {v.get('sha256') or ''}" for p, v in index.items())).encode("utf-8")).hexdigest()[:16]
    manifest = {"schema": MANIFEST_SCHEMA, "taken": taken, "crate_url": crate_url, "promoted": promoted, "generation": generation if promoted else None,
                "policy": {"accept_partial": accept_partial, "attempts": attempts, "max_bytes": max_bytes}, "counts": dict(counts), "entries": entries}
    (staging / "pids.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    if not promoted:
        return old, manifest                                      # the live folder is untouched; the staging folder keeps the evidence
    with locked(out.with_name(out.name + ".lock"), "snapshot promotion"):
        if previous.exists():
            shutil.rmtree(previous)
        if out.exists():
            out.replace(previous)
        staging.replace(out)
    return index, manifest


def rollback(out: Path) -> bool:
    """Swap the live folder with the previous one; False when there is no previous folder."""
    out = Path(out)
    previous, swap = out.parent / f".{out.name}.previous", out.parent / f".{out.name}.swap"
    if not previous.is_dir():
        return False
    out.replace(swap)
    previous.replace(out)
    swap.replace(previous)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Record live PIDs into a folder fdo-consume reads as a recorded source.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--pid", action="append", default=[], help="a PID to record; repeat for several")
    parser.add_argument("--community", default=None, help="record the public objects of this ROHub community instead of --pid (the name as ROHub states it)")
    parser.add_argument("--search", action="append", default=[], help="with --community: a search term whose hits are filtered on the community; repeat for several")
    parser.add_argument("--max-members", type=int, default=100, help="with --community: at most this many members")
    parser.add_argument("--crate-url", default="{pid}", help="default template for where a PID's RO-Crate metadata is served")
    parser.add_argument("--crate-rule", nargs=2, action="append", default=[], metavar=("REGEX", "TEMPLATE"), help="template for PIDs matching REGEX; first match wins")
    parser.add_argument("--keep-existing", action="store_true", help="carry the entries of the current folder that are not recorded again")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--accept-partial", action="store_true", help="promote when at least one PID was recorded; failed PIDs keep their last copy")
    parser.add_argument("--manifest", default=None, help="write a copy of the manifest here (it is always in <out>/manifest.json)")
    parser.add_argument("--rollback", action="store_true", help="restore the previous snapshot of --out and exit")
    args = parser.parse_args()
    out = Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out
    if args.rollback:
        done = rollback(out)
        print("rolled back" if done else "no previous snapshot to roll back to")
        sys.exit(0 if done else 2)
    searched = None
    if args.community:
        if not args.search:
            parser.error("--community needs at least one --search term")
        args.pid, searched = community_pids(args.community, args.search, args.timeout, max_members=args.max_members)
        print(f"community '{args.community}': {searched['members_found']} public members among {searched['hits']} hits for {args.search}", flush=True)
    if not args.pid:
        parser.error("at least one --pid, or --community with --search terms that find members")
    keep = json.loads((out / "pids.json").read_text(encoding="utf-8")) if args.keep_existing and (out / "pids.json").is_file() else None
    _, manifest = snapshot(out, args.pid, args.crate_url, args.timeout, accept_partial=args.accept_partial, max_bytes=args.max_bytes,
                           rules=[{"match": m, "url": u} for m, u in args.crate_rule], keep=keep)
    if searched and manifest["promoted"]:
        (out / "community.json").write_text(json.dumps(searched, ensure_ascii=False, indent=1), encoding="utf-8")   # what was searched, beside the members
    if args.manifest:
        Path(args.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = manifest["counts"]
    print(f"snapshot -> {args.out}: {counts} ; {'promoted, generation ' + manifest['generation'] if manifest['promoted'] else 'NOT promoted, previous snapshot kept'}")
    sys.exit(0 if manifest["promoted"] else 2)


if __name__ == "__main__":
    main()
