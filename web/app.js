// FDO Knowledge Dashboard: data loading, URL state and events; views.js builds the HTML. Every value shown comes from data/catalog.json and data/records/<key>.json.
// Routes: #/   #/resources?q=…&<facet>=…&sort=title|date|type&n=24   #/resource/<encoded PID>   #/about   #/how-it-works
// Document query: ?pid=<PID> opens one resource; ?presentation=embedded hides the site's header and footer (layout only).
import { esc, brandHtml, homeHtml, chatHtml, discoveryHtml, unavailableHtml, pageOn, pageLabel, askOn, fillDates, listHtml, searchErrorHtml, resourceHtml, textPageHtml, compositionHtml, navHtml, footerHtml, missingHtml, loadingHtml, embedStripHtml, pageStep, SORTS, REFRESHED_NOTE } from "./views.js";
import { qaClient, discoveryClient, canonical } from "./services.js";
import { searchProvider } from "./search.js";
import * as chat from "./chat.js";

const $ = (id) => document.getElementById(id);
const DATA = "data/";                       // relative: the same files under a dev server and under GitHub Pages
const PAGE_NAMES = { home: null, list: "Resources", resource: "Resource", about: "About", how: "How it works", ask: "Ask", off: "Not available" };
let catalog = null;
let qa = null, discovery = null;         // partner services behind one client each (services.js); "disabled" unless configured
let search = null;                       // the list page's search provider (search.js): static, or a trusted server's API
let conversation = null, asking = false;
const storage = (() => { try { return window.sessionStorage; } catch { return null; } })();
const records = new Map();                  // key -> record, fetched when a resource page opens
let moreOpen = false;                                   // the "More filters" disclosure, kept across redraws
let lastList = "#/resources";
let lastRoute = null;
let drawSeq = 0;                          // a route change while a record loads must not draw the stale page
let embedded = false;                     // ?presentation=embedded, read once at start; changes the layout only

document.addEventListener("DOMContentLoaded", init);
window.addEventListener("hashchange", draw);

async function loadCatalog() {
  const res = await fetch(`${DATA}catalog.json`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} (${DATA}catalog.json)`);
  return res.json();
}

// A record belongs to the catalog it was listed by; a site swap between the two fetches shows as a different generation.
export const sameGeneration = (cat, rec) => !cat?.generation?.id || !rec?.source?.generation || cat.generation.id === rec.source.generation;

// The skip links point at ids, not pages: "#main" stays on the page shown, "#chatQ" is the composer of the ask page.
export const skipTarget = (hash, last = {}) => hash === "#main" ? { route: last.page === "list" ? last.list : "#/", focus: "main" }
  : hash === "#chatQ" ? { route: "#/ask", focus: "chatQ" } : null;

// ?presentation=embedded (the exact value) shows the pages without the site's own header and footer; any other value is standalone.
export const presentationOf = (search) => (new URLSearchParams(search).get("presentation") === "embedded" ? "embedded" : "standalone");

// The address of the same page outside the frame: path and query without the flag, the current hash.
export function fullSiteHref(loc) {
  const p = new URLSearchParams(loc.search);
  p.delete("presentation");
  const s = p.toString();
  return `${loc.pathname}${s ? `?${s}` : ""}${loc.hash || "#/"}`;
}

// A member by identifier: the catalog's spelling first, then the canonical form the API accepts (host case, trailing slash).
export const memberOf = (list, pid) => { const c = canonical(pid); return list.find((x) => x.pid === pid) || list.find((x) => canonical(x.pid) === c) || null; };

// The providers are built over one catalog; when the site moved on to another generation, they are built again over the new one.
function provide(cat) {
  const site = cat.site || {};
  qa = qaClient(site, cat);
  discovery = discoveryClient(site, cat);
  search = searchProvider(site, cat);
}

export async function reloadCatalog() {
  catalog = await loadCatalog();
  records.clear();
  provide(catalog);
  $("footer").innerHTML = footerHtml(catalog);
  $("live").textContent = REFRESHED_NOTE;
  return catalog;
}

export const current = () => ({ catalog, search, qa, discovery });

async function init() {
  embedded = presentationOf(location.search) === "embedded";
  document.documentElement.dataset.presentation = embedded ? "embedded" : "standalone";
  try {
    catalog = await loadCatalog();
  } catch (err) {
    $("main").innerHTML = `<div class="state error" role="alert"><h1>The collection could not be loaded</h1><p>${esc(err.message)}</p></div>`;
    return;
  }
  const site = catalog.site || {};
  provide(catalog);
  qa.ready().then(() => { if (route().page === "ask" && !asking) drawChat(); });
  conversation = chat.load(storage, chat.collectionOf(catalog)) || chat.newConversation(chat.collectionOf(catalog));
  document.title = site.title || "FDO Knowledge Dashboard";
  $("brand").innerHTML = brandHtml(site);
  $("brand").setAttribute("aria-label", `${site.title || "FDO Knowledge Dashboard"}, home`);
  $("nav").innerHTML = navHtml(site);
  $("footer").innerHTML = footerHtml(catalog);
  const notice = site.demo_notice || site.source_notice;                                  // synthetic banner, or the source statement
  if (notice) { $("notice").textContent = fillDates(notice, catalog); $("notice").hidden = false; }
  applyTheme(site);
  $("skip").addEventListener("click", (e) => { e.preventDefault(); $("main").focus(); });        // no hash change: the page stays
  document.addEventListener("click", (e) => closeFacets((d) => !d.contains(e.target)));           // a click elsewhere closes a dropdown
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeFacets(() => true, true); });
  document.addEventListener("focusout", (e) => { if (e.relatedTarget) closeFacets((d) => !d.contains(e.relatedTarget)); });
  const asked = new URLSearchParams(location.search).get("pid");        // ?pid= opens one resource
  if (asked && !location.hash) location.hash = `#/resource/${encodeURIComponent(memberOf([...catalog.rows, ...catalog.not_usable], asked)?.pid ?? asked)}`;
  draw();
}

function closeFacets(when, focusSummary) {
  document.querySelectorAll("details.facet[open]").forEach((d) => {
    if (d.closest(".facet-side") || !when(d)) return;                                  // the sidebar's facets are not dropdowns
    d.open = false;
    if (focusSummary) d.querySelector("summary")?.focus();
  });
}

// ---- state in the URL ---------------------------------------------------------
export function route() {
  const h = location.hash || "#/";
  const m = h.match(/^#\/resource\/([^?]+)$/);
  if (m) {
    try { return { page: "resource", pid: decodeURIComponent(m[1]) }; } catch { return { page: "resource", pid: null }; }
  }
  const site = (catalog && catalog.site) || {};                                     // the unit tests route without a catalog
  if (h === "#/about") return pageOn(site, "about") ? { page: "about" } : { page: "off", label: pageLabel(site, "about") };
  if (h === "#/how-it-works") return pageOn(site, "how") ? { page: "how" } : { page: "off", label: pageLabel(site, "how") };
  if (h.startsWith("#/ask")) return askOn(site) ? { page: "ask", q: (new URLSearchParams(h.split("?")[1] || "").get("q") || "").trim() } : { page: "off", label: pageLabel(site, "ask") };
  if (!h.startsWith("#/resources")) return { page: "home" };
  const params = new URLSearchParams(h.split("?")[1] || "");
  const filters = {};
  for (const f of catalog.facets) filters[f.id] = new Set(params.getAll(f.id));
  const o = parseInt(params.get("o") || "0", 10);                                   // carousel offset
  return { page: "list", q: (params.get("q") || "").trim(), filters, sort: SORTS[params.get("sort")] ? params.get("sort") : "title",
           o: Number.isFinite(o) && o > 0 ? o : 0 };
}

export function listHash(st) {
  const p = new URLSearchParams();
  if (st.q) p.set("q", st.q);
  for (const [id, set] of Object.entries(st.filters)) for (const v of set) p.append(id, v);
  if (st.sort !== "title") p.set("sort", st.sort);
  if (st.o > 0) p.set("o", String(st.o));
  const s = p.toString();
  return s ? `#/resources?${s}` : "#/resources";
}

const go = (st) => { location.hash = listHash(st); };
const emptyFilters = () => Object.fromEntries(catalog.facets.map((f) => [f.id, new Set()]));
const sameQuery = (a, b) => a && b && a.page === "list" && b.page === "list" && a.q === b.q && a.sort === b.sort &&
  JSON.stringify(Object.fromEntries(Object.entries(a.filters).map(([k, v]) => [k, [...v].sort()]))) ===
  JSON.stringify(Object.fromEntries(Object.entries(b.filters).map(([k, v]) => [k, [...v].sort()])));

// ---- drawing ---------------------------------------------------------------------
async function draw() {
  if (!catalog) return;
  const skip = skipTarget(location.hash, { page: lastRoute?.page, list: lastList });
  if (skip) {                                           // a skip link's target, reached without JS: no page change
    history.replaceState(null, "", skip.route);
    if (lastRoute && $(skip.focus)) { $(skip.focus).focus(); return; }
  }
  const seq = ++drawSeq;
  const r = route();
  const openFacet = document.querySelector("details.facet[open]")?.dataset.facet || null;   // kept across the redraw
  const keep = document.activeElement?.id && r.page === "list" && lastRoute?.page === "list" ? document.activeElement.id : null;
  const paged = sameQuery(r, lastRoute) && r.o !== lastRoute.o;                                 // only the carousel moved
  const site = catalog.site || {};
  document.title = PAGE_NAMES[r.page] ? `${PAGE_NAMES[r.page]} – ${site.title || "FDO Knowledge Dashboard"}` : (site.title || "FDO Knowledge Dashboard");
  document.body.dataset.page = r.page;
  if (embedded) ($("embed") || $("notice").insertAdjacentElement("afterend", Object.assign(document.createElement("p"), { className: "embed-strip", id: "embed" }))).innerHTML = embedStripHtml(catalog, fullSiteHref(location));
  document.querySelectorAll("#nav a[data-page]").forEach((a) => {
    const current = a.dataset.page === r.page || (a.dataset.page === "list" && r.page === "resource");
    current ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current");
  });
  if (!["list", "resource"].includes(r.page) && $("live")) $("live").textContent = "";                // the count belongs to the list and record pages
  if (r.page === "home") $("main").innerHTML = homeHtml(catalog);
  else if (r.page === "about") $("main").innerHTML = textPageHtml(pageLabel(site, "about"), site.about, compositionHtml(catalog));
  else if (r.page === "how") $("main").innerHTML = textPageHtml(pageLabel(site, "how"), site.how_it_works);
  else if (r.page === "off") $("main").innerHTML = unavailableHtml(r.label);
  else if (r.page === "ask") { await drawAsk(r.q, seq); if (seq !== drawSeq) return; }
  else if (r.page === "resource") { await drawResource(r.pid, seq); if (seq !== drawSeq) return; }
  else { lastList = location.hash; await drawList(r, openFacet, seq); if (seq !== drawSeq) return; }
  const kept = keep && $(keep);
  if (paged) {                                                                                  // the arrow keeps focus; at an end, the other one
    const used = kept && !kept.disabled ? kept : ($("next")?.disabled ? $("prev") : $("next"));
    used?.focus({ preventScroll: true });
  } else if (kept && (kept.checkVisibility ? kept.checkVisibility() : kept.offsetParent !== null)) {
    kept.focus({ preventScroll: true });                                                              // a filter change keeps focus
  } else if (kept && kept.closest("details.facet")) {
    kept.closest("details.facet").querySelector("summary").focus({ preventScroll: true });
  } else if (skip && $(skip.focus)) { $(skip.focus).focus({ preventScroll: true });
  } else if (embedded && !lastRoute) {                                                          // first draw inside a host page: its focus and scroll position stay
  } else { $("main").focus({ preventScroll: true }); window.scrollTo(0, 0); }
  lastRoute = r;
  wire(r);
}

async function drawList(st, openFacet, seq) {
  if (search.mode === "api") $("main").innerHTML = loadingHtml("#/");
  const found = await search.run(st);
  if (seq !== drawSeq) return;
  if (found.status !== "ok") { $("main").innerHTML = searchErrorHtml(found, search); return; }
  if (found.generation_id && catalog.generation?.id && found.generation_id !== catalog.generation.id && !st.reloaded) {   // the server moved on: take its catalog
    await reloadCatalog();
    return drawList({ ...st, reloaded: true }, openFacet, seq);
  }
  $("main").innerHTML = listHtml(catalog, st, found.rows, found.counts, openFacet, moreOpen, { ...found, refreshed: Boolean(st.reloaded) });
  $("live").textContent = `${st.reloaded ? `${REFRESHED_NOTE} ` : ""}${found.total} of ${catalog.counts.usable} resources`;
  if (st.q && discovery.mode !== "disabled" && $("discoverOut")) {                   // the same words go to the external graph search
    const external = await discovery.discover(st.q);
    if (seq === drawSeq && $("discoverOut")) $("discoverOut").innerHTML = discoveryHtml(external);
  }
}

async function drawAsk(q, seq) {
  drawChat();
  if (q && !asking) {                                           // a question in the address is asked once; the address then drops it
    history.replaceState(null, "", "#/ask");
    await send(q);
  }
}

function drawChat() {
  $("main").innerHTML = chatHtml(catalog, conversation, { mode: qa.mode, transport: qa.transport, label: qa.label, capabilities: qa.resolved, capabilities_source: qa.capabilities_source }, { pending: asking, stored: Boolean(storage) });
  document.querySelector("a.skip-inline")?.addEventListener("click", (e) => { e.preventDefault(); $("chatQ")?.focus(); });   // no hash change: the page stays
  $("chatForm")?.addEventListener("submit", (e) => { e.preventDefault(); const text = $("chatQ").value.trim(); if (text) send(text); });
  $("newConv")?.addEventListener("click", () => { conversation = chat.newConversation(chat.collectionOf(catalog)); chat.save(conversation, storage); drawChat(); $("chatQ")?.focus(); });
  $("clearConv")?.addEventListener("click", () => { chat.clear(storage); conversation = chat.newConversation(chat.collectionOf(catalog)); drawChat(); $("chatQ")?.focus(); });
  document.querySelectorAll("[data-retry]").forEach((b) => b.addEventListener("click", () => {
    const i = Number(b.dataset.retry), user = conversation.messages[i - 1];
    if (user?.role === "user" && conversation.messages[i]?.role === "assistant") { conversation.messages.splice(i); answer(user.content); }
  }));
}

// One turn: the question goes into the conversation, the local matches are found, the service (if any) is asked with the
// bounded prior turns, and its answer or status becomes the assistant turn.
async function send(text) {
  if (asking || !chat.addUser(conversation, text)) return;
  await answer(text);
}

async function answer(text) {
  const prior = chat.historyOf(conversation).slice(0, -1);                     // the turns before this question
  asking = true;
  drawChat();
  const found = qa.mode === "disabled" ? null : await search.run({ q: text, filters: emptyFilters(), sort: "date" });   // the list page's provider, static or api
  const hits = (found?.status === "ok" ? found.rows : []).slice(0, 6).map((r) => ({ pid: r.pid, title: r.title, in_dashboard: true }));
  let result;
  try {
    result = qa.mode === "disabled" ? { status: "not_configured", answer: null, citations: [] } : await qa.ask(text, hits, { lang: document.documentElement.lang || null, history: prior, conversation_id: conversation.id });
  } catch (err) {
    result = { status: "error", answer: null, citations: [], reason: "the request failed" };
  }
  if (!result.citations?.length && qa.mode !== "disabled") result.related = result.related?.length ? result.related : hits;
  chat.addAssistant(conversation, result);
  chat.save(conversation, storage);
  asking = false;
  if (route().page === "ask") { drawChat(); $("chatQ")?.focus(); }
}

async function drawResource(pid, seq, reloaded = false) {
  const row = pid && memberOf(catalog.rows, pid);
  const rejected = pid && memberOf(catalog.not_usable, pid);
  const key = (row || rejected || {}).key;
  if (!key) { $("main").innerHTML = missingHtml(lastList); return; }
  if (!records.has(key)) {
    $("main").innerHTML = loadingHtml(lastList);
    try {
      const res = await fetch(catalog.records.replace("{key}", key));
      if (!res.ok) throw new Error(`record ${key}: ${res.status}`);
      const rec = await res.json();
      if (!sameGeneration(catalog, rec)) {                  // the site was replaced meanwhile: take the new catalog once, then this record again
        if (reloaded) throw new Error("the record belongs to another data generation than the catalog");
        await reloadCatalog();
        return drawResource(pid, seq, true);
      }
      records.set(key, rec);
    } catch (err) {
      if (seq === drawSeq) $("main").innerHTML = `<div class="state error" role="alert"><h1>The record could not be loaded</h1><p>${esc(err.message)}</p></div>`;
      return;
    }
  }
  if (seq === drawSeq) $("main").innerHTML = resourceHtml(catalog, records.get(key), lastList);
}

// Deployment colours and background, set as CSS variables; values were validated by the build (hex, contrast, path).
function applyTheme(site) {
  const names = { primary: "--green", deep: "--deep", sage: "--sage", orange: "--orange", blue: "--blue", purple: "--purple" };
  for (const [colour, value] of Object.entries(site.theme || {})) if (names[colour] && /^#[0-9a-f]{6}$/i.test(value)) document.documentElement.style.setProperty(names[colour], value);
  const image = site.background?.image;
  if (image && /^[A-Za-z0-9_][A-Za-z0-9_./-]*$/.test(image) && !image.includes("..")) document.documentElement.style.setProperty("--hero-image", `url("${image}")`);
}

// ---- events ------------------------------------------------------------------------
function wire(r) {
  $("homeSearch")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("homeQ").value.trim();
    if (!askOn(catalog.site || {}) || !q) go({ q, filters: emptyFilters(), sort: "title", o: 0 });      // the same condition labels the bar
    else location.hash = `#/ask?q=${encodeURIComponent(q)}`;
  });
  if (r.page !== "list") return;
  $("retrySearch")?.addEventListener("click", () => draw());
  if (!$("searchForm")) return;
  $("searchForm").addEventListener("submit", (e) => { e.preventDefault(); const s = route(); s.q = $("q").value.trim(); s.o = 0; go(s); });
  $("sort").addEventListener("change", () => { const s = route(); s.sort = $("sort").value; go(s); });
  for (const [id, step] of [["prev", -pageStep(catalog)], ["next", pageStep(catalog)]])
    $(id)?.addEventListener("click", () => { const s = route(); s.o = Math.max(0, s.o + step); history.replaceState(null, "", listHash(s)); draw(); });
  $("moreFilters")?.addEventListener("toggle", (e) => { moreOpen = e.target.open; });
  const clear = () => go({ q: "", filters: emptyFilters(), sort: route().sort, o: 0 });
  document.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", clear));
  document.querySelectorAll(".chip[data-remove]").forEach((chip) => chip.addEventListener("click", () => {
    const s = route();
    if (chip.dataset.remove === "q") s.q = ""; else s.filters[chip.dataset.remove].delete(chip.dataset.value);
    s.o = 0; go(s);
  }));
  document.querySelectorAll("button.facet-value").forEach((b) => b.addEventListener("click", () => {
    if (b.getAttribute("aria-disabled") === "true") return;
    const s = route(); const set = s.filters[b.dataset.facet];
    set.has(b.dataset.value) ? set.delete(b.dataset.value) : set.add(b.dataset.value);
    s.o = 0; go(s);
  }));
}
