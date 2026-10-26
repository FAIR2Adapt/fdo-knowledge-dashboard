"""Delivery and QA contracts as pydantic models: validation at the HTTP boundary and the source of the JSON schemas under
listing/schema/ (scripts/export_schemas.py). The ResourceRecord schema (record/1) is hand-written and frozen."""
from __future__ import annotations

import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

QUERY_MAX, LIMIT_DEFAULT, LIMIT_MAX = 500, 24, 200
MAX_FACET_VALUES, MAX_VALUE = 50, 500
LANG = r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$"


def clean(value: str, limit: int) -> str:
    """NFC, no control characters, trimmed, bounded."""
    if len(value) > limit:
        raise ValueError(f"a text value is longer than {limit} characters")
    value = unicodedata.normalize("NFC", value)
    if any(unicodedata.category(c)[0] == "C" and c not in "\t\n\r" for c in value):
        raise ValueError("a text value contains control characters")
    return value.strip()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchRequest(Strict):
    q: str = Field("", description=f"at most {QUERY_MAX} Unicode code points; every whitespace-separated word must occur, accent-insensitive, in title, description, date, keywords, authors or claim texts")
    filters: dict[str, list[str]] = Field(default_factory=dict, description="facet id -> values; OR within a facet, AND across facets; unknown facet -> bad_request")
    sort: Literal["title", "date", "type"] = "title"
    offset: int = Field(0, ge=0, le=10_000_000, strict=True)
    limit: int = Field(LIMIT_DEFAULT, ge=1, le=LIMIT_MAX, strict=True)
    lang: str | None = Field(None, pattern=LANG, max_length=35, description="stored and echoed; records are not translated")

    @field_validator("q")
    @classmethod
    def _q(cls, v: str) -> str:
        return clean(v, QUERY_MAX)

    @field_validator("filters")
    @classmethod
    def _filters(cls, v: dict) -> dict:
        out = {}
        for fid, values in v.items():
            if len(values) > MAX_FACET_VALUES:
                raise ValueError(f"at most {MAX_FACET_VALUES} values per facet")
            out[fid] = sorted({clean(x, MAX_VALUE) for x in values})
        return dict(sorted(out.items()))


class ResourceSummary(Strict):
    pid: str
    canonical_pid: str
    key: str
    title: str
    description: str | None = None
    resource_type: list[str]
    keywords: list[str]
    authors: list[str]
    date: str | None = None
    year: str | None = None
    status: str | None = None
    claims: int
    claim_texts: list[str] = Field(default_factory=list)
    claim_kinds: list[str] = Field(default_factory=list)
    duplicate_title: bool = False
    incomplete: bool = False
    readiness: Literal["usable"] = "usable"
    generation_id: str | None = None
    record: str = Field(description="relative path of the ResourceRecord")


class FacetValue(Strict):
    value: str
    count: int = Field(ge=0)


class Facet(Strict):
    id: str
    label: str
    concept: str
    values: list[FacetValue] = Field(description="counts over the current result with this facet's own selection removed, most frequent first, 'type not stated' last")


class Scope(Strict):
    collection: str | None = None
    source_kind: Literal["collection", "pids", "community", "dashboard"]


class Omissions(Strict):
    not_usable: int
    not_searchable: str


class SearchResponse(Strict):
    schema_: Literal["fdo-knowledge-dashboard/search/1"] = Field(alias="schema")
    generation_id: str | None = None
    scope: Scope
    request: SearchRequest
    status: Literal["ok", "empty"]
    total: int = Field(ge=0)
    offset: int
    limit: int
    items: list[ResourceSummary]
    facets: list[Facet]
    omissions: Omissions


class Distribution(Strict):
    metadata: Literal["public"] = "public"
    files: Literal["open", "restricted", "unknown"]


class ResourceDetail(Strict):
    schema_: Literal["fdo-knowledge-dashboard/resource-detail/1"] = Field(alias="schema")
    generation_id: str | None = None
    pid: str
    canonical_pid: str
    readiness: Literal["usable", "not_usable"]
    data_origin: Literal["real", "synthetic", "experimental", "unknown"]
    distribution: Distribution
    record: dict = Field(description="the ResourceRecord, record/1, unchanged")


class SnapshotItem(Strict):
    pid: str
    canonical_pid: str
    source_uri: str | None = None
    retrieved_at: str | None = None
    hash: str | None = Field(None, description="SHA-256 of the recorded crate bytes")
    status: Literal["recorded", "kept", "carried_forward", "gone", "restricted", "failed", "unknown"] = Field(description="unknown: a manifest is present but does not describe this snapshot")


class Members(Strict):
    listed: int
    usable: int
    not_usable: int


class CommunityRecord(Strict):
    community: str
    search: list[str]
    taken: str
    hits: int
    members_found: int
    members_kept: int | None = None


class SourceSnapshot(Strict):
    schema_: Literal["fdo-knowledge-dashboard/source-snapshot/1"] = Field(alias="schema")
    generation_id: str | None = None
    built_at: str
    retrieved_at: str | None = Field(None, description="latest retrieval time of the snapshot; null for live reads and folders without times")
    source_kind: Literal["collection", "pids", "community", "dashboard"]
    data_origin: Literal["real", "synthetic", "experimental", "unknown"]
    recorded: str | None = None
    members: Members
    items: list[SnapshotItem]
    community: CommunityRecord | None = Field(None, description="for a community source: what was searched and how many members were found and kept")


class ErrorBody(Strict):
    code: Literal["bad_request", "not_found", "uri_too_long", "unavailable", "rate_limited"]
    message: str


class Error(Strict):
    error: ErrorBody


# ---- question answering and discovery (fdo-knowledge-dashboard/qa/2) -------------------------------
class Turn(Strict):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=1000)


class QaScope(Strict):
    collection: str | None = None
    pids: list[str] | None = None


class QaRequest(Strict):
    schema_: Literal["fdo-knowledge-dashboard/qa/2"] = Field(alias="schema")
    question: str = Field(min_length=1, max_length=2000)
    lang: str | None = Field(None, pattern=LANG, max_length=35)
    history: list[Turn] = Field(default_factory=list, max_length=12, description="the previous turns of this conversation, text only, oldest first; never the catalog or browser storage")
    conversation_id: str | None = Field(None, max_length=64, description="chosen by the browser; not a session, not authenticated")
    scope: QaScope
    generation_id: str | None = Field(None, description="the data generation the dashboard shows; the answer should name the one it used")


class Supports(Strict):
    single_turn: bool = False
    history: bool = False
    citations: bool = False
    scope: bool = False
    generation: bool = False


class QaCapabilities(Strict):
    schema_: Literal["fdo-knowledge-dashboard/qa-capabilities/1"] = Field(alias="schema")
    supports: Supports = Field(description="declared by the host configuration (site.qa.capabilities) or by the provider's metadata endpoint, established before the first request; a capability counts only when every source that declares it says true; unknown is unsupported")
    provider: str | None = Field(None, max_length=200)
    mock: bool = Field(False, description="true for a mock service; its answers are labelled as such")


class Evidence(Strict):
    url: str = Field(pattern=r"^https://\S+$", max_length=2048)       # the asserted statement itself: a nanopublication, a Knowledge Loom record
    kind: str = Field(max_length=40)                                  # nanopublication | knowledge-loom | other


class Citation(Strict):
    pid: str
    title: str | None = Field(None, max_length=500)
    passage: str | None = None
    section: str | None = None
    version: str | None = None
    evidence: list[Evidence] = Field(default_factory=list, max_length=5)


class QaResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["ok", "no_answer", "error"]
    answer: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    generation_id: str | None = None
    reason: str | None = None
    provider: str | None = None
    conversation_id: str | None = Field(None, description="echoed or chosen by the provider; the dashboard keeps its own id either way")
    supports: Supports | None = Field(None, description="confirmation only, never a grant")


class DashboardQaState(Strict):
    state: Literal["not_configured", "ok", "no_sources", "no_answer", "timeout", "error"] = Field(description="what the page shows; never an answer without cited resources")


class MockResponse(Strict):
    status: Literal["no_answer", "timeout", "error"]
    mock: Literal[True]
    answer: None = None
    citations: list = Field(default_factory=list, max_length=0)
    related: list[Citation] = Field(default_factory=list, description="local search matches, shown as such; never citations")


class DiscoveryRelation(Strict):
    type: str = Field(max_length=100)
    target: str = Field(max_length=2048)


class DiscoveryEntity(Strict):
    id: str = Field(max_length=2048, description="the provider's identifier of the entity")
    pid: str | None = Field(None, max_length=2048, description="a persistent identifier only when the provider states one")
    title: str = Field(max_length=500)
    type: str | None = Field(None, max_length=100)
    relations: list[DiscoveryRelation] = Field(default_factory=list, max_length=50)
    membership: Literal["unverified"] = Field("unverified", description="external results are never members of the dashboard's collection")


class DiscoveryResponse(Strict):
    schema_: Literal["fdo-knowledge-dashboard/discovery/1"] = Field(alias="schema")
    status: Literal["ok", "error"]
    provider: str = Field(max_length=200)
    mock: bool = False
    query: str = Field(max_length=500)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=50)
    total: int = Field(ge=0)
    items: list[DiscoveryEntity] = Field(max_length=50)


class DiscoverySupports(Strict):
    paging: bool = False
    relations: bool = False
    pids: bool = False


class DiscoveryCapabilities(Strict):
    schema_: Literal["fdo-knowledge-dashboard/discovery-capabilities/1"] = Field(alias="schema")
    supports: DiscoverySupports
    provider: str | None = Field(None, max_length=200)
    mock: bool = False


class DiscoveryItem(Strict):
    pid: str | None = None
    id: str | None = None
    title: str
    description: str | None = None
    access: str | None = None
    type: str | None = None
    modified: str | None = None
    relations: list[DiscoveryRelation] = Field(default_factory=list)
    membership: Literal["unverified"] = "unverified"
    in_dashboard: bool


class DiscoveryResult(Strict):
    status: Literal["not_configured", "ok", "timeout", "error"]
    items: list[DiscoveryItem]
    total: int = 0
    source: str


class Message(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)
    at: str


class Conversation(Strict):
    id: str
    messages: list[Message] = Field(max_length=40)
    created_at: str
    updated_at: str


SEARCH_MODELS = [SearchRequest, SearchResponse, ResourceSummary, ResourceDetail, Facet, SourceSnapshot, Error]
QA_MODELS = [QaRequest, Turn, Citation, QaResponse, QaCapabilities, DashboardQaState, MockResponse, DiscoveryResult, DiscoveryResponse, DiscoveryCapabilities, Conversation]
