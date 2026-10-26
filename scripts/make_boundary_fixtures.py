"""Boundary collections for the tests (empty, one member, incomplete members, n members), written to a temporary folder;
every object is named as a test fixture.
    python scripts/make_boundary_fixtures.py --out /tmp/boundary --scale 200"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAND = "https://example.org/synthetic/"
CTX = "https://w3id.org/ro/crate/1.2/context"
PROFILE = "https://w3id.org/cca-crate-profile/0.9"
TYPES = ["dataset", "policy document", "report", "scientific article"]
KEYWORDS = ["flood", "heat", "drought", "coastal", "adaptation", "planning"]


def meta() -> dict:
    return {"@id": "ro-crate-metadata.json", "@type": "CreativeWork", "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"}, "about": {"@id": "./"}}


def member(case: str, n: int, **override) -> tuple[str, dict]:
    pid = f"{STAND}{case}/member-{n:03d}"
    root = {"@id": "./", "@type": "Dataset", "identifier": pid, "conformsTo": {"@id": PROFILE},
            "name": f"Synthetic member {n:03d} ({case})",
            "description": f"SYNTHETIC boundary fixture {n:03d} of the collection '{case}'. Not a real work.",
            "datePublished": f"{2020 + n % 7}-0{1 + n % 9}-1{n % 10}", "license": {"@id": "https://creativecommons.org/publicdomain/zero/1.0/"},
            "additionalType": TYPES[n % len(TYPES)], "keywords": [KEYWORDS[n % 6], KEYWORDS[(n * 5 + 1) % 6]]}
    for key, value in override.items():
        if value is None:
            root.pop(key, None)
        else:
            root[key] = value
    return pid, {"@context": CTX, "@graph": [meta(), root, {"@id": PROFILE, "@type": ["CreativeWork", "Profile"], "name": "CCA-Crate profile 0.9"}]}


def collection(case: str, members: list[str]) -> tuple[str, dict]:
    pid = f"{STAND}{case}/collection"
    root = {"@id": "./", "@type": ["Dataset", "Collection"], "identifier": pid, "conformsTo": {"@id": PROFILE},
            "name": f"Synthetic collection '{case}' ({len(members)} members)", "description": f"SYNTHETIC boundary collection '{case}'. Not a real work.",
            "datePublished": "2026-10-01", "license": {"@id": "https://creativecommons.org/publicdomain/zero/1.0/"},
            "hasPart": [{"@id": m} for m in members]}
    return pid, {"@context": CTX, "@graph": [meta(), root, {"@id": PROFILE, "@type": ["CreativeWork", "Profile"], "name": "CCA-Crate profile 0.9"}]}


def write_case(out: Path, case: str, objects: list[tuple[str, dict]], head: str) -> Path:
    """One recorded folder plus the listing.yaml that points at it; returns the config path."""
    folder = out / case
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "objects").mkdir(parents=True)
    index = {}
    for n, (pid, crate) in enumerate(objects):
        name = pid.rsplit("/", 1)[-1] if pid.rsplit("/", 1)[-1] != "collection" else f"{case}--collection"
        name = f"{case}--{name}" if not name.startswith(case) else name
        (folder / "objects" / name).mkdir(exist_ok=True)
        (folder / "objects" / name / "ro-crate-metadata.json").write_text(json.dumps(crate, indent=1), encoding="utf-8")
        index[pid] = {"fixture": name}
    (folder / "pids.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    config = (f'site: {{title: "SYNTHETIC boundary collection: {case}", demo_notice: "Prototype under development: synthetic boundary fixtures, not from a repository."}}\n'
              f'source: {{kind: collection, pid: "{head}", recorded: "{folder.as_posix()}", data_origin: synthetic}}\n'
              'reading: {profile_overlay: cca-dashboard-additions}\n'
              'facets:\n  - {id: type, label: "Resource type", concept: resource_type}\n  - {id: topic, label: "Topics", concept: keywords}\n'
              '  - {id: year, label: "Year", concept: year}\n')
    (folder / "listing.yaml").write_text(config, encoding="utf-8")
    return folder / "listing.yaml"


def cases(out: Path, scale: int) -> dict:
    """The boundary cases by name -> config path."""
    made = {}
    empty_pid, empty = collection("empty", [])
    made["empty"] = write_case(out, "empty", [(empty_pid, empty)], empty_pid)
    one = [member("one", 1)]
    pid, head = collection("one", [one[0][0]])
    made["one"] = write_case(out, "one", one + [(pid, head)], pid)
    inc = [member("incomplete", 1, name="A synthetic member with a very long title " + "that keeps going " * 12 + "(SYNTHETIC)"),
           member("incomplete", 2), member("incomplete", 3, description=None, datePublished=None),
           member("incomplete", 4, name=None), member("incomplete", 5, name='Synthetic member <b>with markup</b> & "quotes" (SYNTHETIC)'),
           member("incomplete", 6, name="Synthetic member 001 (incomplete)"), member("incomplete", 7, name="Synthetic member 001 (incomplete)")]
    pids = [p for p, _ in inc] + [f"{STAND}incomplete/not-recorded", "local-member"]      # a hasPart entry without a scheme
    pid, head = collection("incomplete", pids)
    made["incomplete"] = write_case(out, "incomplete", inc + [(pid, head)], pid)
    many = [member(f"scale-{scale}", n) for n in range(1, scale + 1)]
    pid, head = collection(f"scale-{scale}", [p for p, _ in many])
    made[f"scale-{scale}"] = write_case(out, f"scale-{scale}", many + [(pid, head)], pid)
    return made


def main() -> None:
    parser = argparse.ArgumentParser(description="Write synthetic boundary collections.")
    parser.add_argument("--out", required=True, help="a folder outside the repository")
    parser.add_argument("--scale", type=int, default=200)
    args = parser.parse_args()
    out = Path(args.out)
    for name, path in cases(out if out.is_absolute() else ROOT / out, args.scale).items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
