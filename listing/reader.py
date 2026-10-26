"""The one module that calls fdo-consume: the collection head and each member, read for the listing's contracts."""
from __future__ import annotations

from pathlib import Path

from fdo_consume import Limits, __version__ as FDO_CONSUME_VERSION, consume, consume_for_contracts, describe
from fdo_consume.profiles import load_maps


class Reader:
    """Reads objects by PID with the listing's contracts, profile maps and overlay; recorded folder or live PIDs."""

    def __init__(self, root: Path, cfg: dict):
        reading, source = cfg["reading"], cfg["source"]          # reading.fallback_map: the map for objects that declare no profile (ROHub exports)
        recorded = source.get("recorded")
        self.contracts = reading["contracts"]
        self.version = FDO_CONSUME_VERSION
        self.kind = "recorded" if recorded else "live"
        self.options = {"contracts": str(root / reading["contracts_dir"]), "profile_maps": str(root / reading["maps_dir"]),
                        "profile_overlay": reading.get("profile_overlay"), "profile": reading.get("fallback_map"), "source": self.kind,
                        "recorded_dir": str(root / recorded) if recorded else None,
                        "limits": Limits(max_members=int(reading["max_members"]))}     # fdo-consume caps a collection at 1000 by default

    def collection(self, pid: str):
        """The collection object, checked against the collection contract."""
        return consume(pid, self.contracts["collection"], **self.options)

    def member(self, pid: str) -> dict:
        """One member, located once and checked against the record and the claims contract."""
        names = [self.contracts["record"], self.contracts["claims"]]
        found = consume_for_contracts(pid, names, **self.options)
        return {"record": found[names[0]], "claims": found[names[1]]}

    def map_fields(self) -> dict[str, set[str]]:
        """The field names each profile map or overlay defines, by id."""
        return {(m.get("id") or key): set(m.get("fields") or {}) for key, m in load_maps(self.options["profile_maps"]).items()}

def describe_in(root: Path, cfg: dict, recorded: str, pid: str):
    """One object of a recorded folder, read through its profile map and the configured overlay, without a contract:
    the composition reads Dashboard and Plugin FDOs this way (their entities come back in `descriptor.extra.entities`)."""
    reading = cfg["reading"]
    folder = Path(recorded) if Path(recorded).is_absolute() else root / recorded
    return describe(pid, source="recorded", recorded_dir=str(folder), profile_maps=str(root / reading["maps_dir"]),
                    profile_overlay=reading.get("profile_overlay"), limits=Limits(max_members=int(reading["max_members"])))


def maps_known(root: Path, cfg: dict) -> list[dict]:
    """Every profile map fdo-consume would use here: id, status, the profile IRIs it selects, where it comes from."""
    ours = {p.stem for p in (root / cfg["reading"]["maps_dir"]).glob("*.yaml")}
    out = []
    for key, m in load_maps(str(root / cfg["reading"]["maps_dir"])).items():
        mid = m.get("id") or key
        out.append({"id": mid, "status": m.get("status") or "unknown", "selects": list(m.get("selects") or []), "owner": "this repository" if mid in ours else "fdo-consume"})
    return sorted(out, key=lambda m: m["id"])


def members_of(collection) -> tuple[list[str], int, int]:
    """The member PIDs a collection states (within fdo-consume's limits), the total it states, and how many entries
    fdo-consume skipped because they carry no identifier scheme."""
    described = collection.record.descriptor or {}
    return list(described.get("members") or []), int(described.get("members_total") or 0), int(described.get("members_skipped") or 0)
