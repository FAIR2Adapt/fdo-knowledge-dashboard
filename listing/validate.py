"""Input bounds at the HTTP boundary: query parameters, facet values, keys and PIDs are checked here before anything is
looked up. Rejections carry fixed messages; the input is never echoed."""
from __future__ import annotations

import re
import unicodedata

from .delivery import LIMIT_DEFAULT, LIMIT_MAX, QUERY_MAX, SORTS, ContractError

MAX_PARAMS = 100
MAX_FACET_VALUES = 50
MAX_VALUE = 500
MAX_KEY = 64
MAX_PID = 2048
MAX_TARGET = 8192
PID_SCHEMES = ("http", "https", "urn", "doi", "hdl", "ark")
KEY = re.compile(r"^[0-9a-f]{16}$")
SCALARS = ("q", "sort", "offset", "limit", "lang", "pid")


def bad(message: str) -> ContractError:
    return ContractError("bad_request", message)


def text(value, limit: int) -> str:
    """A bounded, NFC-normalised string without control characters."""
    if not isinstance(value, str) or len(value) > limit:
        raise bad(f"a text value is longer than {limit} characters")
    value = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(c)[0] == "C" and c not in "\t\n\r" for c in value):
        raise bad("a text value contains control characters")
    return value.strip()


def integer(raw, default: int, low: int, high: int, name: str) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise bad(f"{name} must be an integer")
    if isinstance(raw, str):
        if not re.fullmatch(r"-?[0-9]{1,9}", raw.strip()):
            raise bad(f"{name} must be an integer")
        raw = int(raw)
    if not low <= raw <= high:
        raise bad(f"{name} must be between {low} and {high}")
    return raw


def key(value) -> str:
    """A record key: 16 hex characters, as the build writes them."""
    if not isinstance(value, str) or len(value) > MAX_KEY or not KEY.match(value):
        raise ContractError("not_found", "no resource with this key")
    return value


def pid(value) -> str:
    """A PID string to look up: bounded, one of the known schemes, never dereferenced."""
    if value is None:
        raise bad("pid is required")
    value = text(value, MAX_PID)
    scheme = value.split(":", 1)[0].lower() if ":" in value else ""
    if not value or scheme not in PID_SCHEMES:
        raise bad("pid must be an identifier with one of the schemes " + ", ".join(PID_SCHEMES))
    return value


def search_request(query: dict, facets: list) -> dict:
    """A SearchRequest from parsed query parameters (name → list of values)."""
    if len(query) > MAX_PARAMS or sum(len(v) for v in query.values()) > MAX_PARAMS:
        raise bad(f"at most {MAX_PARAMS} query parameters")
    known = {f["id"] for f in facets}
    first = lambda name: (query.get(name) or [None])[0]
    request = {"q": text(first("q") or "", QUERY_MAX), "filters": {},
               "offset": integer(first("offset"), 0, 0, 10_000_000, "offset"), "limit": integer(first("limit"), LIMIT_DEFAULT, 1, LIMIT_MAX, "limit")}
    sort = first("sort") or "title"
    if sort not in SORTS:
        raise bad("sort must be one of " + ", ".join(SORTS))
    request["sort"] = sort
    lang = first("lang")
    if lang is not None:
        lang = text(lang, 35)
        if not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", lang):
            raise bad("lang must be a language tag such as en or pt-PT")
    request["lang"] = lang
    for name, values in query.items():
        if name in SCALARS:
            continue
        if not name.startswith("f.") or name[2:] not in known:
            raise bad("unknown query parameter; filters are f.FACET for one of the facets " + ", ".join(sorted(known)))
        if len(values) > MAX_FACET_VALUES:
            raise bad(f"at most {MAX_FACET_VALUES} values per facet")
        request["filters"][name[2:]] = [text(v, MAX_VALUE) for v in values]
    return request


def target(path: str, query_string: str) -> None:
    """The request target as a whole (path and query, Unicode code points): bounded before parsing."""
    if len(path) + len(query_string) > MAX_TARGET:
        raise ContractError("uri_too_long", f"the request target is longer than {MAX_TARGET} characters")
