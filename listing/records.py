"""ResourceRecord: what the site shows for one member, built from the bindings fdo-consume delivered. Every value comes
from the object through fdo-consume; a value the object does not state is null or empty, never filled in."""
from __future__ import annotations

import hashlib
import re

RECORD_SCHEMA = "fdo-knowledge-dashboard/record/1"
LICENCE_LABELS = {"https://creativecommons.org/licenses/by/4.0": "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/legalcode": "CC BY 4.0",   # ROHub links the legal code
                  "https://creativecommons.org/licenses/by-sa/4.0": "CC BY-SA 4.0",
                  "https://creativecommons.org/publicdomain/zero/1.0": "CC0 1.0", "https://spdx.org/licenses/MIT": "MIT",
                  "https://choosealicense.com/no-permission": "no licence granted (all rights reserved)"}
TERM_WORDS = {"title": "title", "description": "description", "date": "publication date", "licence": "licence",
              "identifier": "identifier", "author": "authors", "members": "members", "access_rights": "access rights"}
NOT_READ_FIELDS = {"author": "authors", "access_rights": "access", "title": "title", "date": "date", "licence": "licence", "type": "type",
                   "keywords": "keywords", "description": "description"}                 # contract term -> record field
ROOT_TERMS = ("title", "description", "licence", "date")                                   # read through a map field only; the fdo-consume diagnostic A7 never calls them undefined
NAME_KINDS = ("nanopublication", "linked_nanopublication")                               # the text is the part's registered name
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
HTTP = re.compile(r"^https?://", re.I)


def key_of(pid: str) -> str:
    """A short, file-safe key for a PID; the PID itself stays in the record."""
    return hashlib.sha1(pid.encode("utf-8")).hexdigest()[:16]


def is_pid(value) -> bool:
    """An identifier with a scheme; a crate-local id ("knowledge/", "#node") is not one."""
    return isinstance(value, str) and bool(SCHEME.match(value))


def to_record(pid: str, read: dict, cfg: dict, read_at: str, reader_version: str, source_kind: str, map_fields: dict | None = None) -> dict:
    """The record of one member; usable or not, the record says why through `source`. `map_fields` names the fields each
    profile map defines, so that a root attribute the map in use does not define counts as not read."""
    result, claims = read["record"], read["claims"]
    record = {"schema": RECORD_SCHEMA, "pid": pid, "key": key_of(pid), "title": None, "description": None, "resource_type": [],
              "keywords": [], "authors": [], "author_ids": [], "identifier": None, "date": None, "year": None, "licence": None,
              "access": {"state": "unknown", "conditions": []}, "profiles": [], "status": None, "claims": [], "datasets": [],
              "related": [], "based_on": [], "files": [], "not_read": not_read(result, defined_fields(result, map_fields)),
              "source": {"reader": f"fdo-consume {reader_version}", "read_at": read_at, "kind": source_kind, "usable": result.is_usable,
                         "explanation": None if result.is_usable else explain(result), "record": console(result), "claims": console(claims)}}
    if not result.is_usable:
        return record
    binding = result.binding
    obj, fields = binding["object"], binding["object"]["fields"]
    labels = cfg["reading"].get("profile_labels") or {}
    date = fields.get("date") or obj.get("date")
    names = _list(fields.get("author_name"))            # the Loom map delivers the Person's IRI as `author` and the name apart
    record.update({
        "title": obj["name"], "description": obj.get("description"), "resource_type": _list(fields.get("type")),
        "keywords": keywords_of(fields.get("keywords")),
        "authors": names or _list(fields.get("author")),
        "author_ids": [a for a in _list(fields.get("author")) if HTTP.match(a)] if names else [],
        "identifier": obj.get("identifier") or fields.get("identifier"),
        "date": str(date)[:10] if date else None, "year": str(date)[:4] if date and str(date)[:4].isdigit() else None,
        "licence": _licence(obj.get("licence")),
        "access": {"state": obj["access"]["state"], "conditions": list(obj["access"].get("conditions") or [])},
        "profiles": [{"iri": p, "label": labels.get(p.rstrip("/"))} for p in (obj.get("profiles") or [])],
        "status": fields.get("status"),
        "claims": [_text_kind(c) for c in _claims(claims, obj, binding["related"]) + _linked_nanopublications(result, claims)],
        "datasets": _datasets(binding),
        "related": [{"pid": r["id"], "is_pid": is_pid(r["id"]), "title": r.get("name"), "key": None,
                     "profile": labels.get(str(p).rstrip("/")) or p if (p := (r.get("profiles") or [None])[0]) else None,
                     "readable": bool(r.get("has_map"))} for r in binding["related"]],
        "based_on": [{"pid": b, "is_pid": is_pid(b), "title": None, "key": None} for b in _list(fields.get("based_on"))],
        "files": [_file(r) for r in binding["resources"]],
    })
    return record


def defined_fields(result, map_fields: dict | None) -> set[str] | None:
    """The field names the map and overlay used for this object define; None when they are not known."""
    obj = (result.binding or {}).get("object") or {}
    names = [n for n in (obj.get("map"), obj.get("overlay")) if n]
    if map_fields is None or not names or any(n not in map_fields for n in names):
        return None
    return set().union(*(map_fields[n] for n in names))


def not_read(result, defined: set[str] | None = None) -> list[str]:
    """Record fields the reader could not read because the map in use defines no term for them: the fdo-consume diagnostic
    A7 (required_metadata) "defines no such term", and the root attributes (ROOT_TERMS) that diagnostic leaves out when the
    map defines no field for them. Shown as "not read by this site", distinct from a value the object does not state."""
    terms = []
    for d in result.diagnostics:
        if str(d.get("code", "")).startswith("A7.") and "defines no such term: " in d.get("message", ""):
            terms += [t.strip() for t in d["message"].split("defines no such term: ", 1)[1].split(";", 1)[0].split(",")]
    if defined is not None:
        terms += [t for t in ROOT_TERMS if t not in defined]
    return [NOT_READ_FIELDS[t] for t in dict.fromkeys(terms) if t in NOT_READ_FIELDS]


def _text_kind(claim: dict) -> dict:
    """assertion: the text is the claim or statement itself; name: the text is the registered name of a part, which the
    repository may have cut (text_cut)."""
    name = claim["kind"] in NAME_KINDS
    text = claim.get("text") or ""
    return {**claim, "text_kind": "name" if name else "assertion", "text_cut": name and text.rstrip().endswith(("...", "…"))}


def _asserted_by(values) -> list[dict]:
    """The authors a nanopublication names: IRI and a label (the IRI's tail when no name is delivered)."""
    return [{"iri": v, "label": v.rstrip("/").rsplit("/", 1)[-1] or v} for v in _list(values)]


def _licence(iri) -> dict | None:
    """The licence IRI with a label from a short table (by this site, not by the record); the IRI is always shown."""
    return {"iri": iri, "label": LICENCE_LABELS.get(iri.rstrip("/"))} if iri else None


def _file(resource: dict) -> dict:
    url = resource.get("url")
    return {"path": resource["id"], "media_type": resource.get("media_type"), "access": resource["access"]["state"],
            "url": url if isinstance(url, str) and HTTP.match(url) else None}


def _claims(claims, obj: dict, related: list) -> list:
    """Claims and Loom statements, each with the record that asserts it and the concepts a statement names; titles,
    keys and status of asserting records that are members are filled in by the catalog."""
    if not claims.is_usable:
        return []
    entities = claims.binding["entities"]
    concepts = {e["id"]: e["fields"].get("label") or e["id"] for e in entities if e["type"] == "Concept"}
    names = {r["id"]: r.get("name") for r in related}          # a nested asserting record is named by the object's own related entry
    out = []
    for e in entities:
        if e["type"] == "Claim":
            asserted = e["fields"].get("record")
            out.append({"kind": "claim", "text": e["fields"].get("text"), "concepts": [], "asserted_by": [],
                        "asserted_in": {"pid": asserted, "is_pid": is_pid(asserted), "title": names.get(asserted), "key": None, "status": None} if asserted else None})
        elif e["type"] == "Statement":
            out.append({"kind": "statement", "text": e["fields"].get("label"), "asserted_by": [],
                        "concepts": [concepts.get(c, c) for c in _list(e["fields"].get("concepts"))],
                        "asserted_in": {"pid": obj["pid"], "is_pid": True, "title": obj["name"], "key": key_of(obj["pid"]), "status": obj["fields"].get("status")}})
        elif e["type"] == "Nanopublication":                       # a nanopublication the object lists (map rohub-bibliography-ro)
            url = e["fields"].get("url") or e["id"]
            out.append({"kind": "nanopublication", "text": e["fields"].get("text"), "concepts": [], "asserted_by": _asserted_by(e["fields"].get("author")),
                        "asserted_in": {"pid": url, "is_pid": is_pid(url), "title": None, "key": None, "status": None}})
    return out


NANOPUB_PID = re.compile(r"^https://w3id\.org/sciencelive/np/", re.I)


def _linked_nanopublications(result, claims) -> list:
    """Parts registered as 'Publication' whose link is a nanopublication identifier: listed as `linked_nanopublication`,
    marked inferred, only for objects read with the rohub-bibliography-ro map and only when the map itself found none."""
    # TODO: remove if the export types these parts as nanopub:Nanopublication
    selected = ((result.record.semantics or {}).get("profile") or {}).get("selected")
    if selected != "rohub-bibliography-ro" or not claims.is_usable or any(e["type"] == "Nanopublication" for e in claims.binding["entities"]):
        return []
    return [{"kind": "linked_nanopublication", "inferred": True, "text": r.get("name"), "concepts": [], "asserted_by": [],
             "asserted_in": {"pid": r["url"], "is_pid": True, "title": None, "key": None, "status": None},
             "note": "type inferred from the identifier: registered in ROHub as a publication, linked to a nanopublication identifier"}
            for r in result.binding["resources"] if r.get("url") and NANOPUB_PID.match(r["url"]) and r.get("name")]


def _datasets(binding: dict) -> list:
    """Dataset entities the object states, with access, extent, variables and files as stated; nothing is computed from data."""
    entities, out = binding["entities"], []
    for d in (e for e in entities if e["type"] == "Dataset"):
        variables = [{"name": v["fields"].get("name"), "unit": v["fields"].get("unit_text"), "unit_code": v["fields"].get("unit_code"),
                      "description": v["fields"].get("description")} for v in entities if v["type"] == "Variable" and d["id"] in v["holders"]]
        files = [_file(r) for r in binding["resources"] if d["id"] in r["holders"]]
        out.append({"id": d["id"], "pid": d.get("pid"), "name": d["fields"].get("name"),
                    "access": {"state": d["access"]["state"], "conditions": list(d["access"].get("conditions") or [])},
                    "extent": {"box": d["fields"].get("spatial_box")}, "variables": variables, "files": files})
    return out


def _list(value) -> list:
    return [] if value is None else [str(v) for v in value] if isinstance(value, list) else [str(value)]


def keywords_of(value) -> list:
    """Keywords as a list. RO-Crate allows one comma-separated string, which is split; a list is kept as stated."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return _list(value)


def console(result) -> dict:
    """What fdo-consume answered: contract, usability, the four statuses, the map and overlay it read through, whether a
    profile validator ran, every step that did not pass, structured notes, unexpanded contexts, and the error."""
    record = result.record
    semantics = record.semantics or {}
    binding_object = (result.binding or {}).get("object") or {}
    validation = record.validation or {}
    located = next((s.detail for s in record.steps if s.id == "A2" and s.status == "PASS"), None)
    return {"contract": record.contract_id, "usable": result.is_usable, "outcome": record.outcome, "stopped": record.stopped,
            "error": record.error, "statuses": result.statuses,
            "map": binding_object.get("map") or (semantics.get("profile") or {}).get("selected"),
            "overlay": binding_object.get("overlay"),
            "validator": {"ran": bool((validation.get("validator") or {}).get("ran")),
                          "reason": (validation.get("validator") or {}).get("reason"), "note": validation.get("note")},
            "diagnostics": [dict(d) for d in result.diagnostics], "why": why_of(result),
            "notes": [{"step": n.get("step"), "code": n.get("code"), "terms": list(n.get("terms") or [])} for n in result.notes],
            "unknown_contexts": list(semantics.get("unknown_contexts") or []), "unknown_terms": list(semantics.get("unknown_terms") or []),
            "located": located, "record_sha256": record.record_sha256, "crate_sha256": record.crate_sha256}


def why_of(result) -> list[str]:
    """Every step that was not PASS, one line each."""
    return [f"{s.id} {s.status}: {s.detail}" for s in result.record.steps if s.status != "PASS"]


def explain(result) -> str:
    """A reader-facing sentence for a member that cannot be shown, from fdo-consume's diagnostic codes: the listing's own
    requirement first (A7), then why the object could not be reached or read, then a profile rule. Nothing is added."""
    record = result.record
    if record.outcome == "error":
        code = (record.error or {}).get("code", "error")
        if code.startswith("request."):
            return f"This listing could not request the record ({code}); the listing's configuration needs a look."
        return f"The record could not be processed ({code})."
    found = lambda prefixes, statuses: next((d for d in result.diagnostics if d["code"].startswith(prefixes) and d["status"] in statuses), None)
    if d := found("A7.", ("FAIL",)):
        return f"The record does not state its {_words(_absent(d['message'], 'must'))}, which this listing needs."
    if found(("A2b", "object."), ("FAIL",)):
        return "The record's metadata could not be read."
    if found(("A2.", "resolution.", "transport."), ("FAIL", "INDETERMINATE")):
        return "No copy of this record could be retrieved for its identifier."
    if found("A1.", ("FAIL", "INDETERMINATE")):
        return "The identifier the collection gives is not a persistent identifier (it has no scheme)."
    if found("N1.", ("FAIL", "INDETERMINATE")):
        return "The record's context could not be used, so its terms could not be interpreted."
    if found("O1.", ("FAIL",)):
        return "The record states a different identifier than the one it was listed under."
    if found("O1.", ("INDETERMINATE",)):
        return "The identifier the record states differs from the listed one only in spelling; no rule says they are the same."
    if found("P2.", ("FAIL", "INDETERMINATE")):
        return "The record declares more than one profile this listing can read; none was chosen."
    if d := found("V0.", ("FAIL",)):
        rules = [i for i in _items(d["message"], "must") if i.startswith("rule:")]
        if rules:
            return f"The record breaks a rule of its profile: {rules[0][len('rule:'):].strip()}."
        terms = _absent(d["message"], "must")
        if terms:
            return f"The record does not state its {_words(terms)}, which its profile requires."
    if record.stopped and "no members" in record.stopped:
        return "This collection lists no members."
    return "The record cannot be shown; see the technical details."


def _items(message: str, level: str) -> list[str]:
    """The items after "<level> absent:" in a step message; fdo-consume gives the list as text only."""
    if f"{level} absent: " not in message:
        return []
    part = message.split(f"{level} absent: ", 1)[1].split("; should absent", 1)[0] if level == "must" else message.split(f"{level} absent: ", 1)[1]
    return [i.strip() for i in part.split("; ") if i.strip()]


def _absent(message: str, level: str) -> list[str]:
    return [i for i in _items(message, level) if not i.startswith("rule:")]


def _words(items: list[str]) -> str:
    names = [TERM_WORDS.get(i.split(" <", 1)[0], i.split(" <", 1)[0]) for i in items[:3]] or ["required metadata"]
    return " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
