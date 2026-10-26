// Search providers for the list page: `static` (catalog rows in the browser) and `api` (a trusted /api/v1/search).
// Same result shape (rows, facet counts, total, generation id); no silent fallback between them.
import { failureOf, fetchJson } from "./services.js";

export const SEARCH_SCHEMA = "fdo-knowledge-dashboard/search/1";
export const LIMIT = 200;
const endpointOk = (e) => typeof e === "string" && (/^https:\/\//i.test(e) || (/^[A-Za-z0-9_][A-Za-z0-9_./-]*$/.test(e) && !e.includes("..")));

export function searchProvider(site, catalog, deps = {}) {
  const cfg = site.search || {};
  const fetchFn = deps.fetch || globalThis.fetch;
  const timeoutMs = deps.timeoutMs ?? 8000;
  const mode = cfg.provider === "api" && endpointOk(cfg.endpoint) ? "api" : "static";
  return { mode, endpoint: mode === "api" ? cfg.endpoint : null,
           run: (st) => (mode === "api" ? apiSearch(catalog, cfg.endpoint, st, fetchFn, timeoutMs) : Promise.resolve(staticSearch(catalog, st))) };
}

// ---- static: the rules the browser applies, the same as listing/delivery.py ------------------
export const fold = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// Code-point order (not locale order), so the browser and both servers sort identically.
export function compareCodePoints(a, b) {
  let i = 0, j = 0;
  while (i < a.length && j < b.length) {
    const ca = a.codePointAt(i), cb = b.codePointAt(j);
    if (ca !== cb) return ca < cb ? -1 : 1;
    i += ca > 0xffff ? 2 : 1; j += cb > 0xffff ? 2 : 1;
  }
  return (i < a.length) - (j < b.length);
}

export function matches(row, st, skip) {
  for (const [fid, wanted] of Object.entries(st.filters)) {
    if (fid === skip || !wanted.size) continue;
    const have = new Set(row.facet_values[fid] || []);
    if (![...wanted].some((v) => have.has(v))) return false;
  }
  if (!st.q) return true;
  const hay = fold([row.title, row.description, row.date, ...row.keywords, ...row.authors, ...row.claim_texts].join(" "));
  return fold(st.q).split(/\s+/).every((word) => hay.includes(word));
}

export function sorted(rows, sort) {
  const byTitle = (a, b) => compareCodePoints(fold(a.title), fold(b.title)) || compareCodePoints(a.title || "", b.title || "");
  const cmp = {   // missing values last; ties by title
    title: byTitle,
    date: (a, b) => (!a.date - !b.date) || compareCodePoints(b.date || "", a.date || "") || byTitle(a, b),
    type: (a, b) => (!a.resource_type.length - !b.resource_type.length) || compareCodePoints(fold(a.resource_type[0]), fold(b.resource_type[0])) || byTitle(a, b),
  }[sort];
  return [...rows].sort(cmp);
}

export function staticSearch(catalog, st) {
  const rows = sorted(catalog.rows.filter((row) => matches(row, st)), st.sort);
  const counts = {};        // per facet, counted with that facet's own selection removed, so other values stay reachable
  for (const f of catalog.facets) {
    counts[f.id] = {};
    for (const row of catalog.rows) if (matches(row, st, f.id)) for (const v of row.facet_values[f.id] || []) counts[f.id][v] = (counts[f.id][v] || 0) + 1;
  }
  return { status: "ok", provider: "static", rows, counts, total: rows.length, truncated: false, generation_id: catalog.generation?.id || null };
}

// ---- api: the same request to the server, the same shape back --------------------------------
export function queryOf(st) {
  const p = new URLSearchParams();
  if (st.q) p.set("q", st.q);
  for (const [id, set] of Object.entries(st.filters)) for (const v of set) p.append(`f.${id}`, v);
  p.set("sort", st.sort || "title");
  p.set("limit", String(LIMIT));
  return p.toString();
}

const rowOf = (item) => ({ key: item.key, pid: item.pid, title: item.title, description: item.description || "", resource_type: item.resource_type || [], keywords: item.keywords || [],
                           authors: item.authors || [], date: item.date, year: item.year, status: item.status, claims: item.claims || 0, claim_texts: item.claim_texts || [],
                           claim_kinds: item.claim_kinds || [], duplicate_title: Boolean(item.duplicate_title), incomplete: Boolean(item.incomplete), facet_values: {} });

export async function apiSearch(catalog, endpoint, st, fetchFn, timeoutMs) {
  const base = { provider: "api", rows: [], counts: {}, total: 0, truncated: false, generation_id: null };
  const { res, body, fail } = await fetchJson(fetchFn, `${endpoint.replace(/\/+$/, "")}/search?${queryOf(st)}`, { headers: { Accept: "application/json" } }, timeoutMs);
  if (!res || !res.ok || !body || body.schema !== SEARCH_SCHEMA || !Array.isArray(body.items) || !Array.isArray(body.facets)) return { ...base, ...failureOf(fail, res) };
  const counts = Object.fromEntries(body.facets.map((f) => [f.id, Object.fromEntries((f.values || []).map((v) => [v.value, v.count]))]));
  return { ...base, status: "ok", rows: body.items.map(rowOf), counts, total: body.total, truncated: body.total > body.items.length, generation_id: body.generation_id || null };
}
