// Clients for the partner services: question answering and external discovery. No credential here: endpoints come from the
// site configuration, must be https (loopback only for a local mock) and are written into the page's CSP by the build.
export const QA_SCHEMA = "fdo-knowledge-dashboard/qa/2";
export const CAPABILITIES = ["single_turn", "history", "citations", "scope", "generation"];
const MOCK_CAPABILITIES = { single_turn: true, history: false, citations: false, scope: true, generation: true };
const asCapabilities = (o) => Object.fromEntries(CAPABILITIES.map((k) => [k, o?.[k] === true]));   // unknown is unsupported
const isHttps = (u) => /^https:\/\//i.test(String(u || ""));
export const isLoopback = (u) => /^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|$)/i.test(String(u || ""));
const text = (v) => (typeof v === "string" ? v : null);
export const canonical = (pid) => String(pid || "").trim().replace(/\/+$/, "").replace(/^(https?):\/\/([^/]+)/i, (m, s, h) => `${s.toLowerCase()}://${h.toLowerCase()}`);

const MAX_RESPONSE = 1_000_000;                                   // bytes a partner answer may have
const EVIDENCE_URL = /^https:\/\/\S{1,2040}$/;                      // Evidence.url of the contract: https, no whitespace, at most 2,048 characters
const JSON_TYPE = /^application\/([a-z0-9.+-]+\+)?json\b/;        // media types that count as JSON

// One bounded request: timeout covers the whole body, the body is dropped past MAX_RESPONSE and counts as JSON only with a
// JSON media type. `res` is null when no response arrived; `fail` names why `body` is null: timeout, network, too_large, not_json.
export async function fetchJson(fetchFn, url, init, ms) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const res = await fetchFn(url, { ...init, signal: ctl.signal });
    return { res, ...(await readJson(res)) };
  } catch (err) {
    return { res: null, body: null, fail: err?.name === "AbortError" ? "timeout" : "network" };
  } finally { clearTimeout(timer); }
}

export async function readJson(res) {
  const type = String(res.headers?.get?.("content-type") || "").toLowerCase();
  if (type && !JSON_TYPE.test(type)) return { body: null, fail: "not_json" };
  if (Number(res.headers?.get?.("content-length") || 0) > MAX_RESPONSE) return { body: null, fail: "too_large" };
  let text = "";
  try {
    if (res.body?.getReader) {
      const reader = res.body.getReader(), decoder = new TextDecoder();
      let bytes = 0;
      for (let part = await reader.read(); !part.done; part = await reader.read()) {
        bytes += part.value.byteLength;
        if (bytes > MAX_RESPONSE) { await reader.cancel(); return { body: null, fail: "too_large" }; }
        text += decoder.decode(part.value, { stream: true });
      }
      text += decoder.decode();
    } else {
      text = await res.text();
      if (text.length > MAX_RESPONSE) return { body: null, fail: "too_large" };
    }
  } catch (err) { return { body: null, fail: err?.name === "AbortError" ? "timeout" : "network" }; }
  try { return { body: JSON.parse(text), fail: null }; } catch { return { body: null, fail: "not_json" }; }
}

// The status and sentence of a failed call, from `fail` and the HTTP status; an HTTP error outranks its body.
export function failureOf(fail, res) {
  const reason = { timeout: "no answer within the time limit", network: "the request did not reach the service",
                   too_large: "the answer was larger than this page accepts", not_json: "the answer was not JSON" };
  if (fail === "timeout" || fail === "network") return { status: fail === "timeout" ? "timeout" : "error", reason: reason[fail] };
  if (res && !res.ok) return { status: "error", reason: `the service reported an error (HTTP ${res.status})`, http: res.status };
  return { status: "error", reason: reason[fail] || "the answer was not in the expected shape" };
}

// ---- question answering ------------------------------------------------------------------
// Capabilities come from the configuration (trusted) and, when declared, from the provider's endpoint, before the first
// question; a capability holds only when every source that speaks says so. Mode: mock needs a label, remote an https endpoint.
export const qaMode = (qa = {}) => qa.mode === "mock" && qa.demo_label ? "mock" : qa.mode === "remote" && isHttps(qa.endpoint) ? "remote" : "disabled";

export function qaClient(site, catalog, deps = {}) {
  const qa = site.qa || {};
  const fetchFn = deps.fetch || globalThis.fetch;
  const timeoutMs = deps.timeoutMs ?? 8000;
  const mode = qaMode(qa);
  const httpMock = mode === "mock" && isLoopback(qa.endpoint);              // a local mock HTTP service, labelled like the browser mock
  const target = mode === "remote" || httpMock ? qa.endpoint : null;
  const known = new Map((catalog.rows || []).map((r) => [canonical(r.pid), r]));
  const label = mode === "mock" ? qa.demo_label : mode === "remote" ? (qa.provider_label || "Question answering service") : "";
  const client = { mode, label, transport: target ? "http" : mode === "mock" ? "browser" : "none",
                   resolved: mode === "mock" && !httpMock ? { ...MOCK_CAPABILITIES } : mode === "disabled" ? asCapabilities({}) : null,
                   capabilities_source: target ? null : mode };
  let pending = null;
  client.ready = () => {
    if (client.resolved) return Promise.resolve(client.resolved);
    pending ??= resolveCapabilities(qa, fetchFn, timeoutMs, httpMock).then(({ caps, source }) => { client.capabilities_source = source; return (client.resolved = caps); });
    return pending;
  };
  client.ask = async function ask(question, hits = [], opts = {}) {
    const caps = await client.ready();
    const request = { schema: QA_SCHEMA, question, lang: opts.lang || null, history: [], conversation_id: null,
                      scope: { collection: catalog.collection?.pid || null, pids: null }, generation_id: catalog.generation?.id || null };
    if (mode === "disabled") return { status: "not_configured", mock: false, provider: null, answer: null, citations: [], request, single_turn: true };
    if (mode === "mock" && !httpMock) return mockAnswer(request, hits, known);
    if (!caps.single_turn) return { status: "not_configured", mock: mode === "mock", provider: "remote", answer: null, citations: [], request, single_turn: true,
                                    reason: client.capabilities_source === "failed" ? "the service's capabilities could not be established (the capabilities endpoint did not answer), so no question is sent" : "the service declared no capabilities, so no question is sent" };
    if (!caps.citations) return { status: "not_configured", mock: mode === "mock", provider: "remote", answer: null, citations: [], request, single_turn: !caps.history, reason: "the service does not cite resources, so its answers cannot be shown" };
    if (caps.history) {
      request.history = Array.isArray(opts.history) ? opts.history.slice(-12) : [];
      request.conversation_id = typeof opts.conversation_id === "string" ? opts.conversation_id.slice(0, 64) : null;
    }
    const result = await remoteAnswer(request, target, fetchFn, timeoutMs, known);
    if (mode === "mock") Object.assign(result, { mock: true, provider: "mock-http" });
    const confirmed = result.supports;                                   // a response may confirm a capability, never grant one
    result.single_turn = !caps.history || confirmed?.history === false;
    result.generation_known = caps.generation && confirmed?.generation !== false;
    return result;
  };
  return client;
}

// A declared capabilities endpoint ({schema, supports}) may only narrow the configured values; when it cannot be read, every
// capability is unsupported. `source`: configuration, endpoint, configuration+endpoint, failed, none.
export async function resolveCapabilities(qa, fetchFn, timeoutMs, allowLoopback = false) {
  const configured = qa.capabilities ? asCapabilities(qa.capabilities) : null;
  if (!isHttps(qa.capabilities_endpoint) && !(allowLoopback && isLoopback(qa.capabilities_endpoint))) return { caps: configured || asCapabilities({}), source: configured ? "configuration" : "none" };
  const { res, body } = await fetchJson(fetchFn, qa.capabilities_endpoint, { headers: { Accept: "application/json" } }, timeoutMs);
  const declared = res?.ok && body && typeof body === "object" && body.supports && typeof body.supports === "object" ? asCapabilities(body.supports) : null;
  if (!declared) return { caps: asCapabilities({}), source: "failed" };
  if (!configured) return { caps: declared, source: "endpoint" };
  return { caps: Object.fromEntries(CAPABILITIES.map((k) => [k, configured[k] && declared[k]])), source: "configuration+endpoint" };
}

// Citations as the page may show them: a PID of this dashboard links to its record; another https PID is an external link
// marked as not in the dashboard; anything else is named and not linked. Nothing is added to a citation.
export function checkCitations(citations, known) {
  return (Array.isArray(citations) ? citations : []).filter((c) => c && typeof c.pid === "string").map((c) => {
    const hit = known.get(canonical(c.pid));
    return { pid: c.pid, title: hit ? hit.title : text(c.title)?.slice(0, 500) || null, passage: text(c.passage), section: text(c.section), version: text(c.version),
             evidence: (Array.isArray(c.evidence) ? c.evidence : []).filter((e) => e && typeof e.url === "string" && EVIDENCE_URL.test(e.url) && typeof e.kind === "string").slice(0, 5).map((e) => ({ url: e.url, kind: e.kind.slice(0, 40) })),
             in_dashboard: Boolean(hit), external: !hit && isHttps(c.pid) };
  });
}

// The mock stands in for an absent service: no answer, no citation; the local search hits are returned as `related`
// (search matches, never evidence). Scenarios by a word in the question: mock:empty, mock:unknown, mock:timeout, mock:invalid.
export function mockAnswer(request, hits, known) {
  const q = request.question, base = { mock: true, provider: "mock", request, generation_id: request.generation_id, answer: null, citations: [] };
  if (/mock:timeout/.test(q)) return { ...base, status: "timeout", related: [], reason: "no answer within the time limit" };
  if (/mock:invalid/.test(q)) return { ...base, status: "error", related: [], reason: "invalid response shape" };
  const matches = /mock:empty/.test(q) ? [] : hits.slice(0, 3).map((r) => ({ pid: r.pid }));
  if (/mock:unknown/.test(q)) matches.push({ pid: "urn:example:not-in-this-dashboard" });
  return { ...base, status: "no_answer", related: checkCitations(matches, known), reason: "demonstration: no question-answering service is connected" };
}

export async function remoteAnswer(request, endpoint, fetchFn, timeoutMs, known) {
  const base = { mock: false, provider: "remote", request, answer: null, citations: [] };
  const { res, body, fail } = await fetchJson(fetchFn, endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) }, timeoutMs);
  if (!res || !res.ok || !body || typeof body !== "object") return { ...base, ...failureOf(fail, res) };
  const status = ["ok", "no_answer", "error"].includes(body.status) ? body.status : null;
  if (!status || (status === "ok" && typeof body.answer !== "string")) return { ...base, status: "error", reason: "the answer was not in the expected shape" };
  const citations = checkCitations(body.citations, known);
  const usable = status === "ok" && citations.some((c) => c.in_dashboard);          // an answer is shown only when it cites a resource of this dashboard
  return { ...base, mock: body.mock === true, status: usable ? "ok" : status === "ok" ? "no_sources" : status, answer: usable ? body.answer : null, citations,
           generation_id: text(body.generation_id), reason: status === "ok" && !usable ? "cites no resource of this dashboard" : text(body.reason), conversation_id: text(body.conversation_id),
           supports: body.supports && typeof body.supports === "object" ? body.supports : null };
}

// ---- external discovery ("Discover more in …") -------------------------------------------
// Results stay apart from the collection. Modes: disabled; mock (browser, or a loopback mock service); remote (https endpoint with {q}).
export const DISCOVERY_CAPABILITIES = ["paging", "relations", "pids"];
const asDiscoveryCaps = (o) => Object.fromEntries(DISCOVERY_CAPABILITIES.map((k) => [k, o?.[k] === true]));
export const discoveryMode = (d = {}) => d.mode === "mock" ? "mock" : d.mode === "remote" && isHttps(d.endpoint) && String(d.endpoint).includes("{q}") ? "remote" : "disabled";

export function discoveryClient(site, catalog, deps = {}) {
  const d = site.discovery || {};
  const fetchFn = deps.fetch || globalThis.fetch;
  const timeoutMs = deps.timeoutMs ?? 8000;
  const mode = discoveryMode(d);
  const httpMock = mode === "mock" && isLoopback(d.endpoint) && String(d.endpoint).includes("{q}");
  const target = mode === "remote" || httpMock ? d.endpoint : null;
  const local = new Set((catalog.rows || []).map((r) => canonical(r.pid)));
  const source = mode === "mock" ? (d.demo_label || "Mock discovery (synthetic)") : (d.label || "the repository");
  let caps = null, capsSource = "none";                           // configuration, endpoint, configuration+endpoint, default, failed
  async function capabilities() {
    if (caps) return caps;
    const configured = d.capabilities ? asDiscoveryCaps(d.capabilities) : null;
    const url = d.capabilities_endpoint;
    if (!isHttps(url) && !(httpMock && isLoopback(url))) {
      capsSource = configured ? "configuration" : "default";
      return (caps = configured || asDiscoveryCaps(mode === "mock" && !target ? { relations: true, pids: true } : {}));
    }
    const { res, body } = await fetchJson(fetchFn, url, { headers: { Accept: "application/json" } }, timeoutMs);
    const declared = res?.ok && body && body.supports && typeof body.supports === "object" ? asDiscoveryCaps(body.supports) : null;
    if (!declared) { capsSource = "failed"; return (caps = asDiscoveryCaps({})); }
    capsSource = configured ? "configuration+endpoint" : "endpoint";
    return (caps = configured ? Object.fromEntries(DISCOVERY_CAPABILITIES.map((k) => [k, configured[k] && declared[k]])) : declared);
  }
  async function discover(q) {
    const none = { items: [], total: 0, source, mock: mode === "mock" };
    if (mode === "disabled") return { ...none, status: "not_configured" };
    if (!target) return mockDiscovery(q, local, source);
    const supports = await capabilities();
    const { res, body, fail } = await fetchJson(fetchFn, target.replace("{q}", encodeURIComponent(q)), { headers: { Accept: "application/json" } }, timeoutMs);
    if (!res || !res.ok || !body || typeof body !== "object") return { ...none, ...failureOf(fail, res), capabilities_source: capsSource };
    const items = adaptResults(body).map((it) => ({ ...it, relations: supports.relations ? it.relations : [], in_dashboard: Boolean(it.pid) && local.has(canonical(it.pid)) }));
    const stated = typeof body.total === "number" ? body.total : typeof body.count === "number" ? body.count : items.length;
    const total = Number.isSafeInteger(stated) && stated >= items.length ? stated : items.length;
    return { status: "ok", items, total, source, mock: mode === "mock" || body.mock === true, provider: text(body.provider), capabilities_source: capsSource };
  }
  return { mode, source, transport: target ? "http" : mode === "mock" ? "browser" : "none", label: d.button || `Discover more in ${source}`, discover, capabilities };
}

// The in-browser mock: deterministic synthetic results for a public demonstration; nothing is fetched.
export function mockDiscovery(q, local, source) {
  const base = { source, mock: true, provider: "mock" };
  if (/mock:timeout/.test(q)) return { ...base, status: "timeout", items: [], total: 0, reason: "no answer within the time limit" };
  if (/mock:error/.test(q)) return { ...base, status: "error", items: [], total: 0, reason: "the mock reported an error" };
  if (/mock:empty/.test(q)) return { ...base, status: "ok", items: [], total: 0 };
  const items = [{ id: "mock:entity/concept", pid: null, title: `Mock concept for "${String(q).slice(0, 80)}"`, type: "Concept", relations: [] },
                 { id: "mock:entity/external", pid: "urn:example:mock-external-report", title: "Mock report outside the dashboard", type: "Report", relations: [] }]
    .map((it) => ({ ...it, description: null, access: null, modified: null, membership: "unverified", in_dashboard: Boolean(it.pid) && local.has(canonical(it.pid)) }));
  return { ...base, status: "ok", items, total: items.length };
}

// Provider answers mapped to one shape: fdo-knowledge-dashboard/discovery/1, ROHub's search answer ({count, results}) or a
// plain list of {pid, title}. Hits without title or identifier are dropped; at most MAX_ITEMS items, texts cut at MAX_TEXT.
const MAX_ITEMS = 50, MAX_TEXT = 300, MAX_PID = 2048;
export function adaptResults(body) {
  const list = Array.isArray(body.results) ? body.results : Array.isArray(body.items) ? body.items : [];
  const clip = (v, n = MAX_TEXT) => text(v)?.slice(0, n) || null;
  const relations = (r) => (Array.isArray(r.relations) ? r.relations : []).filter((x) => x && typeof x.type === "string" && typeof x.target === "string")
    .slice(0, 50).map((x) => ({ type: x.type.slice(0, 100), target: x.target.slice(0, MAX_PID) }));
  return list.slice(0, MAX_ITEMS).filter((r) => r && typeof r === "object").map((r) => ({
    id: clip(r.id), pid: clip(r.shared_link, MAX_PID) || clip(r.pid, MAX_PID), title: clip(r.title) || clip(r.name),
    description: clip(r.description, 200), access: clip(r.access_mode)?.toLowerCase() || clip(r.access),
    type: clip(r.type), modified: clip(r.modified, 40) || clip(r.modified_on, 40), relations: relations(r), membership: "unverified" }))
    .filter((r) => r.title && (r.pid || r.id));
}
