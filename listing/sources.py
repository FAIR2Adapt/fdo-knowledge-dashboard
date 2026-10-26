"""Where the members come from: a Collection FDO that lists them by PID, an explicit list of PIDs, or the public objects of a
ROHub community as scripts/snapshot.py recorded them. All go through the Reader, so the records have one shape."""
from __future__ import annotations

from dataclasses import dataclass, field

from .delivery import canonical_pid
from .reader import Reader, members_of
from .records import console, explain


@dataclass
class Members:
    kind: str
    pids: list = field(default_factory=list)
    total: int = 0
    collection: dict | None = None      # the collection as the site heads the list with it; None for a PID list
    aliases: dict = field(default_factory=dict)   # kept spelling -> other spellings of the same identifier


def fold(pids) -> tuple[list, dict]:
    """Each identifier once, under its first spelling; spellings that differ only in slash, scheme or host case are aliases."""
    kept, aliases = {}, {}
    for pid in pids:
        if not isinstance(pid, str) or not pid.strip():
            continue
        spelling, key = pid.strip().rstrip("/"), canonical_pid(pid)
        if key not in kept:
            kept[key] = spelling
        elif spelling != kept[key]:
            aliases.setdefault(kept[key], []).append(spelling)
    return list(kept.values()), aliases


def members(reader: Reader, cfg: dict, index: dict | None = None) -> Members:
    """The member PIDs of the configured source, in the source's order, each identifier once. `index` is the recorded
    pids.json; a community's members are exactly the PIDs it holds (the search happened at snapshot time)."""
    source = cfg["source"]
    if source["kind"] == "pids":
        pids, aliases = fold(source["pids"])
        return Members("pids", pids, len(pids), None, aliases)
    if source["kind"] == "community":
        pids, aliases = fold([pid for pid, entry in (index or {}).items() if isinstance(entry, dict) and entry.get("fixture")])
        return Members("community", pids, len(pids), None, aliases)
    head = reader.collection(source["pid"])
    listed, total, skipped = members_of(head)
    pids, aliases = fold(listed)
    binding = head.binding or {}
    stated = head.record.descriptor or {}      # what the collection states, even when its contract is not met
    title = (binding.get("object") or {}).get("name") or stated.get("name")
    notes = []
    if head.record.outcome == "ok" and total == 0:
        notes.append("This collection lists no members.")
    elif not head.is_usable:
        notes.append(explain(head).replace("The record", "The collection"))
    elif not title:
        notes.append("This collection states no title; the site title is used.")
    if len(pids) < total:
        notes.append(f"The collection states {total} members; the first {len(pids)} are shown (reading.max_members).")
    if skipped:
        notes.append(f"The collection lists {skipped} further {'entry' if skipped == 1 else 'entries'} without an identifier scheme; they are not shown.")
    collection = {"pid": source["pid"], "usable": head.is_usable, "title": title,
                  "description": (binding.get("object") or {}).get("description") or stated.get("description"),
                  "members_total": total, "members_skipped": skipped, "stopped": head.record.stopped,
                  "explanation": " ".join(notes) or None, "console": console(head)}
    return Members("collection", pids, total, collection, aliases)
