// The server in Node: a built directory and /api/v1 with the browser's own search module; same routes, limits and headers as server.py.
//   node server.mjs --dist dist [--host 127.0.0.1] [--port 8030] [--origins https://a https://b] [--rate 120] [--behind-proxy] [--frame-ancestors https://host]
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { staticSearch } from "./web/search.js";
import { canonical } from "./web/services.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const API = "/api/v1";
const LIMITS = { query: 500, limit: 200, limitDefault: 24, values: 50, value: 500, params: 100, target: 8192, pid: 2048, clients: 10000 };
const PID_SCHEMES = ["http", "https", "urn", "doi", "hdl", "ark"];
const SORTS = ["title", "date", "type"];
const NOT_STATED = "type not stated";
const STATUS = { bad_request: 400, not_found: 404, uri_too_long: 414 };
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".txt": "text/plain; charset=utf-8", ".ico": "image/x-icon" };
const SECURITY = { "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "strict-origin-when-cross-origin", "Content-Security-Policy": "frame-ancestors 'none'" };
const HTML_PATHS = ["/", "/index.html"];                      // the one document a configured host page may frame; data and API never
const FRAME_ANCESTOR = /^(https:\/\/[A-Za-z0-9.-]+(:\d+)?|http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?)$/;   // scheme, host, optional port; http on loopback only
export const checkFrameAncestors = (values) => { for (const v of values) if (!FRAME_ANCESTOR.test(v)) throw new Error(`--frame-ancestors takes https origins without a path (or http loopback origins for a local host page), not ${JSON.stringify(v)}`); return values; };
const securityHeaders = (pathname, ancestors) => (ancestors.length && HTML_PATHS.includes(pathname)
  ? { ...Object.fromEntries(Object.entries(SECURITY).filter(([k]) => k !== "X-Frame-Options")), "Content-Security-Policy": `frame-ancestors ${ancestors.join(" ")}` } : SECURITY);
const NOT_READY = { error: { code: "unavailable", message: "no site has been built into this server's directory yet" } };
const BAD_PATH = { error: { code: "bad_request", message: "the request path is not valid" } };
const USAGE = `usage: node server.mjs [--dist DIR] [--host HOST] [--port PORT] [--origins ORIGIN ...] [--rate N] [--behind-proxy] [--frame-ancestors ORIGIN ...]

Serve a built fdo-knowledge-dashboard site (web files, data files, /api/v1) from DIR (default: dist).
  --dist DIR          a directory built by scripts/build_site.py; 503 until one exists
  --host HOST         bind address (default 127.0.0.1)
  --port PORT         port (default 8030; 0 picks a free port)
  --origins ORIGIN... browser origins allowed to call the API (or DASHBOARD_ORIGINS)
  --rate N            requests per client per minute (default 120, or DASHBOARD_RATE)
  --behind-proxy      rate-limit by the address the reverse proxy appended to X-Forwarded-For (or DASHBOARD_BEHIND_PROXY=1)
  --frame-ancestors   origins whose pages may frame the HTML document, https or http on loopback (or DASHBOARD_FRAME_ANCESTORS); never data or API
  --help              this text`;

class ContractError extends Error { constructor(code, message) { super(message); this.code = code; } }
const bad = (m) => new ContractError("bad_request", m);
const length = (v) => Array.from(v).length;                 // Unicode code points, as the Python side counts
const text = (v, limit) => {
  if (typeof v !== "string" || length(v) > limit) throw bad(`a text value is longer than ${limit} characters`);
  const n = v.normalize("NFC");
  if (/[\p{Cc}\p{Cf}]/u.test(n.replace(/[\t\n\r]/g, ""))) throw bad("a text value contains control characters");
  return n.trim();
};
const integer = (raw, def, low, high, name) => {
  if (raw == null) return def;
  if (!/^-?[0-9]{1,9}$/.test(String(raw).trim())) throw bad(`${name} must be an integer`);
  const n = Number(raw);
  if (n < low || n > high) throw bad(`${name} must be between ${low} and ${high}`);
  return n;
};

// ---- the built site, taken only when its parts agree ---------------------------------------
class Site {
  constructor(dist) { this.dist = dist; this.stamp = null; this.data = null; }
  load() {
    const data = path.join(this.dist, "data");
    try {
      const stamp = fs.statSync(path.join(data, "generation.json")).mtimeMs;
      if (stamp === this.stamp) return;
      const generation = JSON.parse(fs.readFileSync(path.join(data, "generation.json"), "utf-8"));
      const catalog = JSON.parse(fs.readFileSync(path.join(data, "catalog.json"), "utf-8"));
      const records = Object.fromEntries(fs.readdirSync(path.join(data, "records")).filter((f) => f.endsWith(".json")).map((f) => [f.slice(0, -5), JSON.parse(fs.readFileSync(path.join(data, "records", f), "utf-8"))]));
      const capPath = path.join(data, "capabilities.json");
      const capabilities = fs.existsSync(capPath) ? JSON.parse(fs.readFileSync(capPath, "utf-8")) : null;
      const wanted = generation.generation_id;
      const keys = new Set([...catalog.rows, ...catalog.not_usable].map((r) => r.key));
      const coherent = wanted && catalog.generation?.id === wanted && keys.size === Object.keys(records).length && [...keys].every((k) => records[k]?.source?.generation === wanted) && (!capabilities || capabilities.generation?.id === wanted);
      if (!coherent) return;
      this.data = { generation, catalog, records, capabilities, byCanonical: new Map(Object.entries(records).map(([k, r]) => [canonical(r.pid), k])) };
      this.stamp = stamp;
    } catch { /* a swap in progress or no build: keep what is served */ }
  }
}

// ---- the routes, as listing/api.py answers them ---------------------------------------------
const ordered = (counts) => Object.entries(counts).sort(([va, ca], [vb, cb]) => (va === NOT_STATED) - (vb === NOT_STATED) || cb - ca || (va < vb ? -1 : va > vb ? 1 : 0)).map(([value, count]) => ({ value, count }));
const summary = (row, gen) => ({ pid: row.pid, canonical_pid: canonical(row.pid), key: row.key, title: row.title, description: row.description, resource_type: row.resource_type, keywords: row.keywords, authors: row.authors,
  date: row.date, year: row.year, status: row.status, claims: row.claims, claim_texts: row.claim_texts, claim_kinds: row.claim_kinds || [], duplicate_title: row.duplicate_title, incomplete: row.incomplete, readiness: "usable", generation_id: gen, record: `data/records/${row.key}.json` });
const detail = (record, catalog) => ({ schema: "fdo-knowledge-dashboard/resource-detail/1", generation_id: catalog.generation.id, pid: record.pid, canonical_pid: canonical(record.pid), readiness: record.source.usable ? "usable" : "not_usable",
  data_origin: catalog.generation.data_origin, distribution: { metadata: "public", files: record.access.state }, record });

function searchRequest(query, catalog) {
  const names = Object.keys(query);
  if (names.length > LIMITS.params || names.reduce((n, k) => n + query[k].length, 0) > LIMITS.params) throw bad(`at most ${LIMITS.params} query parameters`);
  const first = (k) => (query[k] || [null])[0];
  const known = new Set(catalog.facets.map((f) => f.id));
  const request = { q: text(first("q") || "", LIMITS.query), filters: {}, sort: first("sort") || "title", offset: integer(first("offset"), 0, 0, 10_000_000, "offset"), limit: integer(first("limit"), LIMITS.limitDefault, 1, LIMITS.limit, "limit"), lang: first("lang") };
  if (!SORTS.includes(request.sort)) throw bad("sort must be one of " + SORTS.join(", "));
  if (request.lang != null && !/^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/.test(text(request.lang, 35))) throw bad("lang must be a language tag such as en or pt-PT");
  for (const name of names) {
    if (["q", "sort", "offset", "limit", "lang", "pid"].includes(name)) continue;
    if (!name.startsWith("f.") || !known.has(name.slice(2))) throw bad("unknown query parameter; filters are f.FACET for one of the facets " + [...known].sort().join(", "));
    if (query[name].length > LIMITS.values) throw bad(`at most ${LIMITS.values} values per facet`);
    request.filters[name.slice(2)] = [...new Set(query[name].map((v) => text(v, LIMITS.value)))].sort();
  }
  request.filters = Object.fromEntries(Object.entries(request.filters).sort());
  return request;
}

function search(site, query) {
  const { catalog } = site.data;
  const request = searchRequest(query, catalog);
  const st = { q: request.q, filters: Object.fromEntries(catalog.facets.map((f) => [f.id, new Set(request.filters[f.id] || [])])), sort: request.sort };
  const found = staticSearch(catalog, st);
  const gen = catalog.generation?.id || null;
  return { schema: "fdo-knowledge-dashboard/search/1", generation_id: gen, scope: { collection: catalog.collection?.pid || null, source_kind: catalog.source_kind }, request, status: found.total ? "ok" : "empty",
    total: found.total, offset: request.offset, limit: request.limit, items: found.rows.slice(request.offset, request.offset + request.limit).map((r) => summary(r, gen)),
    facets: catalog.facets.map((f) => ({ id: f.id, label: f.label, concept: f.concept, values: ordered(found.counts[f.id] || {}) })),
    omissions: { not_usable: catalog.counts.not_usable, not_searchable: "records that could not be read are listed, not searched" } };
}

function route(site, pathname, query) {
  const { catalog, records, generation, capabilities, byCanonical } = site.data;
  if (pathname === `${API}/health`) return { schema: "fdo-knowledge-dashboard/health/1", status: "ok", generation_id: catalog.generation.id, built_at: catalog.built_at, data_origin: catalog.generation.data_origin, records: Object.keys(records).length };
  if (pathname === `${API}/generation`) return generation;
  if (pathname === `${API}/capabilities`) { if (!capabilities) throw new ContractError("not_found", "this build carries no capabilities document"); return capabilities; }
  if (pathname === `${API}/search`) return search(site, query);
  if (pathname === `${API}/facets`) return { schema: "fdo-knowledge-dashboard/search/1", generation_id: catalog.generation.id, facets: search(site, { limit: ["1"] }).facets };
  if (pathname === `${API}/resources`) {
    const raw = (query.pid || [null])[0];
    if (raw == null) throw bad("pid is required");
    const pid = text(raw, LIMITS.pid);
    const scheme = pid.includes(":") ? pid.split(":")[0].toLowerCase() : "";
    if (!pid || !PID_SCHEMES.includes(scheme)) throw bad("pid must be an identifier with one of the schemes " + PID_SCHEMES.join(", "));
    const record = records[byCanonical.get(canonical(pid))];
    if (!record) throw new ContractError("not_found", "no resource with this identifier");
    return detail(record, catalog);
  }
  if (pathname.startsWith(`${API}/resources/`)) {
    const key = pathname.slice(`${API}/resources/`.length);
    const record = /^[0-9a-f]{16}$/.test(key) ? records[key] : null;
    if (!record) throw new ContractError("not_found", "no resource with this key");
    return detail(record, catalog);
  }
  throw new ContractError("not_found", "no such route; routes: health, generation, capabilities, search, facets, resources");
}

// ---- the HTTP layer ---------------------------------------------------------------------------
export function createServer({ dist, origins = [], rate = 120, behindProxy = false, frameAncestors = [] }) {
  checkFrameAncestors(frameAncestors);
  const site = new Site(dist);
  const seen = new Map();
  const allow = (client) => {
    const now = Date.now() / 1000;
    const recent = (seen.get(client) || []).filter((t) => now - t < 60);
    seen.delete(client); seen.set(client, [...recent, now]);
    if (seen.size > LIMITS.clients) { for (const [k, v] of seen) { if (now - v.at(-1) >= 60) seen.delete(k); } while (seen.size > LIMITS.clients) seen.delete(seen.keys().next().value); }
    return recent.length < rate;
  };
  const send = (res, status, headers, body) => {
    const payload = body == null ? "" : JSON.stringify(body);
    res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-cache", "Content-Length": Buffer.byteLength(payload), ...SECURITY, ...headers });
    res.end(payload);
  };
  const notFound = (res) => { res.writeHead(404, { ...SECURITY, "Content-Type": "text/plain" }); res.end("Not Found"); };
  return http.createServer((req, res) => {
    const url = new URL(req.url, "http://local");
    const mark = req.url.indexOf("?");                       // the target is bounded as path + query without the "?"
    if (length(mark < 0 ? req.url : req.url.slice(0, mark) + req.url.slice(mark + 1)) > LIMITS.target) return send(res, 414, {}, { error: { code: "uri_too_long", message: "the request target is too long" } });
    if (url.pathname.includes("%00")) return send(res, 400, {}, BAD_PATH);
    site.load();
    const origin = req.headers.origin;
    const cors = origin && (origins.includes("*") || origins.includes(origin)) ? { "Access-Control-Allow-Origin": origins.includes("*") ? "*" : origin, Vary: "Origin", "Access-Control-Allow-Methods": "GET, OPTIONS" } : {};
    if (url.pathname.startsWith(API) || url.pathname === "/api" || url.pathname === "/api/v1") {
      if (req.method === "OPTIONS") return send(res, 204, cors, null);
      if (req.method !== "GET") return send(res, 405, { ...cors, Allow: "GET, OPTIONS" }, { error: { code: "bad_request", message: "GET only" } });
      if (!site.data) return send(res, 503, { ...cors, "Retry-After": "30" }, NOT_READY);
      const peer = req.socket.remoteAddress || "-";
      const forwarded = behindProxy ? req.headers["x-forwarded-for"] : null;
      const client = forwarded ? forwarded.split(",").at(-1).trim() || peer : peer;
      if (!allow(client)) return send(res, 429, { ...cors, "Retry-After": "60" }, { error: { code: "rate_limited", message: `more than ${rate} requests per minute` } });
      const query = {};
      for (const [k, v] of url.searchParams) if (v !== "" || k === "q") (query[k] ??= []).push(v);   // a blank value counts as absent; q blank is no query
      try { return send(res, 200, cors, route(site, url.pathname, query)); }
      catch (e) { if (e instanceof ContractError) return send(res, STATUS[e.code] || 400, cors, { error: { code: e.code, message: e.message } }); return send(res, 500, cors, { error: { code: "unavailable", message: "the request could not be served" } }); }
    }
    if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, { Allow: "GET, HEAD" }, { error: { code: "bad_request", message: "GET only" } });
    if (!site.data) return send(res, 503, { "Retry-After": "30" }, NOT_READY);
    let file;
    try { file = path.normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, ""); }
    catch { return notFound(res); }
    if (file.includes("\0")) return send(res, 400, {}, BAD_PATH);
    if (file.endsWith("/") || file === "." ) file = path.join(file, "index.html");
    const full = path.join(dist, file);
    if (!full.startsWith(path.resolve(dist)) || !fs.existsSync(full) || fs.statSync(full).isDirectory()) return notFound(res);
    const data = path.sep === "/" ? file.startsWith("/data/") : file.startsWith(`${path.sep}data${path.sep}`);
    res.writeHead(200, { "Content-Type": TYPES[path.extname(full)] || "application/octet-stream", "Cache-Control": data ? "no-cache" : "public, max-age=60", ...securityHeaders(url.pathname, frameAncestors) });
    if (req.method === "HEAD") return res.end();
    fs.createReadStream(full).pipe(res);
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes("--help") || process.argv.includes("-h")) { console.log(USAGE); process.exit(0); }
  const arg = (name, def) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : def; };
  const listOf = (name, env) => { const i = process.argv.indexOf(name); if (i < 0) return (process.env[env] || "").split(/\s+/).filter(Boolean); const out = []; for (let j = i + 1; j < process.argv.length && !process.argv[j].startsWith("--"); j++) out.push(process.argv[j]); return out; };
  const origins = listOf("--origins", "DASHBOARD_ORIGINS");
  let frameAncestors;
  try { frameAncestors = checkFrameAncestors(listOf("--frame-ancestors", "DASHBOARD_FRAME_ANCESTORS")); } catch (e) { console.error(e.message); process.exit(2); }
  const dist = path.resolve(arg("--dist", "dist")), host = arg("--host", "127.0.0.1"), port = Number(arg("--port", "8030"));
  const server = createServer({ dist, origins, rate: Number(arg("--rate", process.env.DASHBOARD_RATE || "120")), behindProxy: process.argv.includes("--behind-proxy") || process.env.DASHBOARD_BEHIND_PROXY === "1", frameAncestors });
  server.on("clientError", (err, socket) => { console.error(`client error: ${err.message}`); if (err.code !== "ECONNRESET" && socket.writable) socket.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n"); else socket.destroy(); });
  process.on("uncaughtException", (err) => console.error(`request failed: ${err.message}`));
  server.listen(port, host, () => console.log(`FDO Knowledge Dashboard (node) at http://${host}:${server.address().port} from ${dist}`));
}
