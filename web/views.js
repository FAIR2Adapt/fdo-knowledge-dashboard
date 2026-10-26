// HTML builders. Pure functions of the catalog and a record: no fetch, no state, every value escaped.
// Visitor-facing words: "resource" for a listed thing. Technical reading details stay in the JSON, not on these screens.
import { qaMode } from "./services.js";
export const SORTS = { title: "Title (A–Z)", date: "Date (newest first)", type: "Resource type" };
export const REFRESHED_NOTE = "The site was updated while you were reading; the list was refreshed.";
export const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
export const fold = (s) => String(s ?? "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const ACCESS = { open: "open", restricted: "restricted", unknown: "not stated" };
const NOT_READ = `<span class="dim">not read by this site</span>`;             // the map defines no term for the field (record.not_read)
const notRead = (rec, field) => Array.isArray(rec.not_read) && rec.not_read.includes(field);
const TONES = ["orange", "green", "blue", "purple"];
const ICONS = { resource_type: "▤", keywords: "♧", year: "◷", authors: "☺", date: "◷", status: "◎", profile: "▣" };
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const isHttp = (s) => /^https?:\/\//i.test(String(s || ""));
const isHttps = (s) => /^https:\/\//i.test(String(s || ""));
const link = (url) => isHttp(url) ? `<a href="${esc(url)}" rel="noopener noreferrer" target="_blank">${esc(url)}</a>` : esc(url);
const paragraphs = (text) => String(text || "").trim().split(/\n\s*\n/).map((p) => `<p>${esc(p.trim())}</p>`).join("");
// A stated description, whitespace collapsed; a heading word the export left at its start ("Abstract", "Resumo", "Summary")
// becomes a label above the text. The record keeps the text as stated.
const DESCRIPTION_LABEL = /^\s*(Abstract|Resumo|Summary)\s*[:.\-–—]?\s+(?=[A-ZÀ-Ý])/;
function descriptionHtml(text) {
  const m = DESCRIPTION_LABEL.exec(String(text));
  const body = (m ? String(text).slice(m[0].length) : String(text)).replace(/\s+/g, " ").trim();
  return `${m ? `<p class="desc-label">${esc(m[1])}</p>` : ""}<p class="lead desc">${esc(body)}</p>`;
}
const tail = (pid) => String(pid).replace(/\/+$/, "").split("/").pop();
const memberHref = (rel) => rel.key ? `#/resource/${encodeURIComponent(rel.pid)}` : null;
const chipsOf = (values, max = 6) => values.length ? `<span class="chips">${values.slice(0, max).map((k) => `<span class="mini">${esc(k)}</span>`).join("")}</span>` : "";
const visibleFacets = (cat) => cat.facets.filter((f) => f.group !== "technical");   // the Profile facet stays in the data, not on the screens
const highlight = (heading, word) => {
  const h = esc(heading || "");
  return word && h.includes(esc(word)) ? h.replace(esc(word), `<em>${esc(word)}</em>`) : h;
};

// ---- chrome ------------------------------------------------------------------------
// Pages a deployment may hide or relabel (site.pages); the list and the record pages are always there.
export const PAGE_DEFAULTS = { about: { label: "About", hash: "#/about", icon: "i" }, how: { label: "How it works", hash: "#/how-it-works", icon: "?" }, resources: { label: "Resources", hash: "#/resources", icon: null }, ask: { label: "Ask a question", hash: null, icon: null } };
export const pageOn = (site, page) => (site.pages || {})[page]?.enabled !== false;
export const pageLabel = (site, page) => (site.pages || {})[page]?.label || PAGE_DEFAULTS[page].label;

export function brandHtml(site) {
  const brand = site.brand || {};
  const lines = brand.lines?.length ? brand.lines : [site.title || "FDO Knowledge Dashboard"];
  const mark = brand.logo?.image
    ? `<img class="brand-logo" src="${esc(brand.logo.image)}" alt="${esc(brand.logo.alt || "")}" width="80" height="80">`
    : `<span class="brand-mark" aria-hidden="true">${brand.flag ? `<small class="flag">${esc(brand.flag)}</small>` : ""}<span class="globe">${esc(brand.mark || "♧")}</span>${brand.gear ? `<small class="gear">${esc(brand.gear)}</small>` : ""}</span>`;
  return `${mark}<span class="brand-text">${lines.map(esc).join("<br>")}</span>`;
}

export function navHtml(site) {
  const fairify = site.links?.fairify;
  const item = (page, dataPage) => pageOn(site, page)
    ? `<a class="nav-link" href="${PAGE_DEFAULTS[page].hash}" data-page="${dataPage}">${PAGE_DEFAULTS[page].icon ? `<span class="nav-ico" aria-hidden="true">${PAGE_DEFAULTS[page].icon}</span>` : ""}${esc(pageLabel(site, page))}</a>` : "";
  return `${isHttp(fairify?.url) ? `<a class="nav-link nav-cta" href="${esc(fairify.url)}" rel="noopener noreferrer" target="_blank"><span class="nav-ico" aria-hidden="true">✓</span>${esc(fairify.label || "FAIRify your resources")}</a>` : ""}
    ${item("about", "about")}
    ${item("how", "how")}
    ${item("resources", "list")}`;
}

export function unavailableHtml(label) {
  return `<section class="content-page"><a class="back" href="#/">‹ Back to home</a><h1 class="page-title">${esc(label)}</h1><div class="info-box"><p>This page is not part of this site.</p></div></section>`;
}

export function footerHtml(cat) {
  const site = cat.site || {};
  const items = (site.footer?.trust || []).slice(0, 3);
  const partners = site.footer?.partners || [];
  const credit = site.background?.attribution;
  const trustText = (text) => !cat.source_taken && text.includes("{taken}") ? `Built ${(cat.built_at || "").slice(0, 10)}; no snapshot time recorded` : fillDates(text, cat);
  return `${items.map((t) => `<div class="trust"><span class="trust-icon" aria-hidden="true">${esc(t.icon || "♢")}</span><div><strong>${esc(t.title)}</strong><small>${esc(trustText(t.text || ""))}</small></div></div>`).join("")}
    ${partners.length ? `<div class="partners"><small>In collaboration with</small>${partners.map((p) => `<strong>${esc(p)}</strong>`).join("")}</div>` : ""}
    ${site.project || site.funding ? `<small class="credit project">${[site.project, site.funding].filter(Boolean).map(esc).join(" · ")}</small>` : ""}
    ${credit ? `<small class="credit">${esc(credit)}</small>` : ""}`;
}

// What this build read: snapshot time, build time, generation id and the stated origin of the data (the embedded strip; data/generation.json has the same).
export function generationHtml(cat) {
  const g = cat.generation || {};
  const origin = { real: "", synthetic: " · synthetic data", experimental: " · experimental composition", unknown: " · data origin not stated" }[g.data_origin || "unknown"] ?? "";
  return `<small class="credit generation">${cat.source_taken ? `Snapshot ${esc(cat.source_taken.slice(0, 16).replace("T", " "))}` : "No snapshot time recorded"} · built ${esc((cat.built_at || "").slice(0, 16).replace("T", " "))}${g.id ? ` · generation ${esc(g.id)}` : ""}${esc(origin)}</small>`;
}

// The embedded presentation hides header and footer: this line keeps the site's name, the provenance line and the way
// out of the frame (a new tab, so a sandboxed host frame without top navigation keeps its page; noopener severs the opener).
export function embedStripHtml(cat, href) {
  return `<strong class="embed-context">${esc((cat.site || {}).title || "FDO Knowledge Dashboard")}</strong>${generationHtml(cat)}<a class="full-site" href="${esc(href)}" target="_blank" rel="noopener noreferrer">Open the full site</a>`;
}

// {date} = when the site was built; {taken} = the year and month the recorded snapshot was taken (or "not recorded" for a live read).
export const fillDates = (text, cat) => text.replace("{date}", (cat.built_at || "").slice(0, 10)).replace("{taken}", cat.source_taken ? cat.source_taken.slice(0, 7) : "not recorded");

// ---- home ------------------------------------------------------------------------------
// The count cards: each configured category sums the stated resource types it names (case-insensitive); nothing stated is 0.
export const askOn = (site) => pageOn(site, "ask") && (site.qa || {}).preview !== false;   // the ask page exists and is wanted

export function categoryCounts(byType, categories) {
  const stated = Object.entries(byType || {});
  return (categories || []).map((c) => {
    const names = (c.types || []).map(fold);
    const matched = stated.filter(([t]) => names.includes(fold(t)));
    return { label: c.label, icon: c.icon || "▤", tone: c.tone || "green", types: matched.map(([t]) => t), n: matched.reduce((s, [, n]) => s + n, 0) };
  });
}

export function homeHtml(cat) {
  const site = cat.site || {}, hero = site.hero || {}, coll = cat.collection, qa = site.qa || {};
  const asks = askOn(site);                                    // the bar leads to the ask page whenever that page is on; without a service it is the preview
  const typeFacet = cat.type_facet, byType = cat.counts.by_type || {};
  const typesHref = (values) => typeFacet && values.length ? `#/resources?${values.map((v) => `${encodeURIComponent(typeFacet)}=${encodeURIComponent(v)}`).join("&")}` : "#/resources";
  const cards = categoryCounts(byType, site.categories);
  const covered = new Set(cards.flatMap((c) => c.types));
  const notStated = byType[cat.not_stated] || 0;
  const outside = cards.length ? Object.entries(byType).filter(([t]) => !covered.has(t) && t !== cat.not_stated).reduce((s, [, n]) => s + n, 0) : 0;   // "outside these groups" needs groups
  const topics = [...(cat.facets_without_source || []).map((m) => ({ label: m.label, icon: m.icon || "♨", why: m.why })),
                  ...visibleFacets(cat).filter((f) => f.home).map((f) => ({ facet: f }))];
  const values = (f) => f.values.length ? f.values.slice(0, 4).map((v) => v.value).join(", ") + (f.values.length > 4 ? ` and ${f.values.length - 4} more` : "") : "no values stated";
  const topicCard = (t, i) => t.facet
    ? `<a class="topic-card ${TONES[i % TONES.length]}" href="#/resources"><span class="bubble" aria-hidden="true">${esc(t.facet.icon || ICONS[t.facet.concept] || "♧")}</span>
        <span class="topic-body"><strong>${esc(t.facet.label)}</strong><small>${esc(values(t.facet))}</small></span><span class="card-arrow" aria-hidden="true">›</span></a>`
    : `<a class="topic-card ${TONES[i % TONES.length]} unavailable" href="#/"><span class="bubble" aria-hidden="true">${esc(t.icon)}</span><span class="topic-body"><strong>${esc(t.label)}</strong><small>${esc(t.why)}</small></span><span class="sr">(not available yet)</span><span class="card-arrow" aria-hidden="true">›</span></a>`;
  const metricCard = (c) => c.n
    ? `<a class="metric ${esc(c.tone)}" href="${typesHref(c.types)}"><span class="bubble" aria-hidden="true">${esc(c.icon)}</span><b>${c.n}</b><span class="label">${esc(c.label)}</span></a>`
    : `<span class="metric ${esc(c.tone)} zero" aria-disabled="true" title="no resource states this type"><span class="bubble" aria-hidden="true">${esc(c.icon)}</span><b>0</b><span class="label">${esc(c.label)}</span></span>`;
  const from = coll.title || coll.pid ? `From the collection <b>${esc(coll.title || tail(coll.pid))}</b>${isHttp(coll.pid) ? ` (${link(coll.pid)})` : ""}: ` : "";
  const countLine = [`<a href="#/resources">${plural(cat.counts.usable, "resource")} in all</a>`,
                     notStated ? `<a href="${typesHref([cat.not_stated])}">${notStated} state no resource type</a>` : "",
                     outside ? `<a href="#/resources">${outside} state a type outside these groups</a>` : "",
                     cat.counts.multi_typed > 0 ? "a resource with several types is counted in each group" : "",
                     cat.counts.not_usable ? `${plural(cat.counts.not_usable, "resource")} of the collection cannot be shown; the list says why` : ""].filter(Boolean);
  const declared = cat.counts.usable - notStated;
  const filled = cards.filter((c) => c.n), empties = cards.filter((c) => !c.n);
  const browse = declared > 0
    ? `${filled.length ? `<div class="metric-grid">${filled.map(metricCard).join("")}</div>` : ""}<p class="count-line">${from}${countLine.join(" · ")}</p>${empties.length ? `<p class="count-line">No resource states the type: ${empties.map((c) => esc(c.label)).join(", ")}.</p>` : ""}`
    : `<div class="summary-box"><p class="summary"><b>${plural(cat.counts.usable, "resource")}</b>${cat.counts.usable ? ` · <a href="${typesHref([cat.not_stated])}">${notStated} without a declared type</a>` : ""}${cat.counts.not_usable ? ` · ${plural(cat.counts.not_usable, "resource")} cannot be shown` : ""}</p>
        <p class="dim small">${cat.counts.usable ? `No resource declares a resource type, so there are no counts by type: ${cards.length ? `the categories (${cards.map((c) => esc(c.label.toLowerCase())).join(", ")})` : "the count cards"} stay empty until a resource states one.` : esc(coll.explanation || "No resource of this collection can be shown.")}</p>
        ${cat.counts.usable ? `<a class="pill-btn" href="#/resources">Browse the resources</a>` : ""}</div>`;
  return `
    <section class="home-hero hero-back">
      <h1>${highlight(hero.heading || site.title || "FDO Knowledge Dashboard", hero.highlight)}</h1>
      ${hero.lead ? `<p class="lead">${esc(hero.lead)}</p>` : ""}
      <form class="ask-form" id="homeSearch" role="search">
        <span class="ask-spark" aria-hidden="true">✦</span>
        <label class="sr" for="homeQ">${asks ? "Ask a question or search the resources" : "Search the resources"}</label>
        <input id="homeQ" type="search" placeholder="${esc(asks ? (qa.placeholder || "Ask a question…") : "Search the resources…")}" autocomplete="off"/>
        <button type="submit" aria-label="${asks ? "Ask" : "Search"}">→</button>
      </form>
    </section>
    <section class="home-section"><h2><span class="section-symbol" aria-hidden="true">♧</span>Explore resources by topic</h2>
      <div class="topic-grid">${topics.map(topicCard).join("")}</div>
    </section>
    <section class="home-section"><h2><span class="section-symbol" aria-hidden="true">▥</span>Browse our resources</h2>
      ${browse}
      ${coll.explanation && declared > 0 ? `<p class="state">${esc(coll.explanation)}</p>` : ""}
    </section>`;
}

// ---- ask: a conversation; each assistant turn shows the service's status and the resources it rests on ----
const MODE_NOTE = { disabled: "No question-answering service is connected: each question is matched against the resources of this dashboard, and nothing is generated.",
                    mock: "Demonstration: no question-answering service is connected; nothing is generated. The matches are search results.",
                    mock_http: "Local mock service, a placeholder for the question answering under development: answers are synthetic, the citations and evidence links show the shape a real answer will have.",
                    remote: "Answers come from the connected service and are shown only with the resources they cite." };

const PREVIEW_NOTE = "Question answering is under development and will be integrated later.";
const EVIDENCE_LABEL = { nanopublication: "nanopublication", "knowledge-loom": "Knowledge Loom record" };
const EVIDENCE_URL = /^https:\/\/\S{1,2040}$/;                      // as in services.js; applied again to what storage returns
const label = (table, key) => (Object.hasOwn(table, key) ? table[key] : key);
const NOT_CONNECTED = "Question answering is under development and will be integrated later; no answer was generated.";
export const LOOM_CONDITION = "if the paper's code and data are available";

// Without a service, the answer turn shows the shape an answer will have: the list, one example record of this dashboard
// (the first with claims), and the Knowledge Loom tag with the condition under which a real answer carries it.
export function placeholderLinksHtml(cat) {
  const rows = cat.rows || [];
  const example = rows.find((r) => r.claims > 0) || rows[0];
  return `<p class="small placeholder-links">An answer will link to: <a href="#/resources">Resources</a>${example ? ` · for example <a href="#/resource/${encodeURIComponent(example.pid)}">${esc(example.title || example.pid)}</a>` : ""} · <span class="loom-tag">${EVIDENCE_LABEL["knowledge-loom"]} · ${LOOM_CONDITION}</span></p>`;
}

export function capabilityNote(caps, source) {
  if (!caps) return "Capabilities not established yet.";
  if (!caps.single_turn) return source === "failed" ? "The service's capabilities could not be established (the capabilities endpoint did not answer): no question is sent."
    : Object.values(caps).some(Boolean) ? "The service does not declare single-turn questions: no question is sent." : "The service declared no capabilities: no question is sent.";
  const parts = [caps.history ? "remembers the conversation" : "answers each question on its own (earlier turns are not sent)",
                 caps.citations ? "cites resources" : "does not cite resources, so answers are not shown",
                 caps.scope ? "scoped to this collection" : "not scoped to this collection", caps.generation ? "names the data generation" : "does not name the data generation"];
  return `Service capabilities: ${parts.join("; ")}.`;
}

// Without a service (mode disabled) the page is a preview: the configured preview_notice, or a constant sentence, is the
// mode note; while the conversation is empty it is shown once, as the empty state.
export function chatHtml(cat, conversation, qa, state = {}) {
  const mode = qa?.mode || "disabled", turns = conversation.messages.filter((m) => m.role === "user").length;
  const badge = mode === "disabled" ? "" : `<span class="qa-badge ${esc(mode)}">${esc(qa.label)}</span>`;
  const usable = Boolean(qa?.capabilities?.single_turn && qa?.capabilities?.citations);
  const caps = (mode === "remote" || qa?.transport === "http") && !usable
    ? `<p class="note">${esc(capabilityNote(qa.capabilities, qa.capabilities_source))}</p>` : "";                 // only while the service cannot be used
  const items = conversation.messages.map((m, i) => messageHtml(cat, m, i, conversation.messages[i - 1]?.role === "user" ? conversation.messages[i - 1].content : "")).join("");
  const pending = state.pending ? `<li class="msg assistant pending"><span class="who" aria-hidden="true">✦</span><div class="bubble-text"><p class="dim">${mode === "disabled" ? "Searching…" : `Asking ${esc(qa.label)}…`}</p></div></li>` : "";
  const note = mode === "disabled" ? (cat.site?.qa?.preview_notice || PREVIEW_NOTE) : mode === "mock" && qa?.transport === "http" ? MODE_NOTE.mock_http : (MODE_NOTE[mode] || MODE_NOTE.disabled);
  const empty = !conversation.messages.length && !state.pending ? `<li class="msg empty"><p class="dim">${mode === "disabled" ? esc(note) : "Ask about the resources of this dashboard, for example a place, a hazard or a policy. Every answer lists the resources it rests on; a question can follow another."}</p></li>` : "";
  return `<section class="content-page chat-page">
    <a class="back" href="#/">‹ Back to home</a>
    <div class="box chat-box">
      <a class="skip-inline" href="#chatQ">Skip to the question box</a>
      <div class="chat-head"><h1 class="page-title">Ask a question</h1>${badge}
        <span class="chat-actions"><button type="button" class="pill-btn" id="newConv">New conversation</button>${state.stored ? `<button type="button" class="link" id="clearConv">Clear history</button>` : ""}</span></div>
      ${mode === "disabled" && empty ? "" : `<p class="note">${esc(note)}</p>`}${caps}
      <ol class="chat" id="chatLog" aria-live="polite" aria-label="Conversation">${empty}${items}${pending}</ol>
      <form class="composer" id="chatForm">
        <label class="sr" for="chatQ">${mode === "disabled" ? "Your words" : "Your question"}</label>
        <input id="chatQ" type="text" maxlength="2000" placeholder="${turns >= 20 ? "This conversation is full; start a new one" : "Ask a question…"}" autocomplete="off"${state.pending || turns >= 20 ? " disabled" : ""}/>
        <button type="submit"${state.pending || turns >= 20 ? " disabled" : ""}>Send</button>
      </form>
      <p class="chat-foot">${state.stored ? "Kept in this browser tab only, until you clear it or close the tab." : "Kept in memory until you leave the page."} · ${turns} of 20 turns</p>
    </div>
  </section>`;
}

function messageHtml(cat, m, i, question = "") {
  if (m.role === "user") return `<li class="msg user"><div class="bubble-text">${paragraphs(m.content)}</div><span class="who" aria-hidden="true">●</span></li>`;
  const evidence = (c) => {                                      // the statements a citation rests on; a mock also names the kinds it has none of
    const shown = (Array.isArray(c.evidence) ? c.evidence : []).filter((e) => e && typeof e.url === "string" && EVIDENCE_URL.test(e.url) && typeof e.kind === "string");
    const links = shown.map((e) => ` <span class="meta">· <a href="${esc(e.url)}" rel="noopener noreferrer" target="_blank">evidence: ${esc(label(EVIDENCE_LABEL, e.kind))}</a></span>`).join("");
    const missing = m.mock ? Object.entries(EVIDENCE_LABEL).filter(([k]) => !shown.some((e) => e.kind === k)).map(([, text]) => ` <span class="meta dim">· ${text} (if evidence available)</span>`).join("") : "";
    return links + missing;
  };
  const cite = (c) => `<li>${c.in_dashboard ? `<a href="#/resource/${encodeURIComponent(c.pid)}">${esc(c.title || c.pid)}</a>`
                         : c.external ? `${link(c.pid)} <span class="warn-text">not in this dashboard</span>` : `<code>${esc(c.pid)}</code> <span class="warn-text">not in this dashboard, not resolvable</span>`}
                         ${c.section ? ` <span class="meta">· ${esc(c.section)}</span>` : ""}${c.version ? ` <span class="meta">· version ${esc(c.version)}</span>` : ""}${evidence(c)}${c.passage ? `<br><q>${esc(c.passage)}</q>` : ""}</li>`;
  const other = m.generation_id && cat.generation?.id && m.generation_id !== cat.generation.id ? `<p class="warn-line">This answer refers to another data generation (${esc(m.generation_id)}); this site shows ${esc(cat.generation.id)}.</p>` : "";
  const line = { not_configured: esc(m.reason || NOT_CONNECTED), no_sources: "The service answered without citing a resource of this dashboard, so no answer is shown.",
                 no_answer: m.mock && (!m.provider || m.provider === "mock") ? "Demonstration: no question-answering service is connected, so nothing was generated."
                          : m.mock ? "The mock service gave no answer for this question (synthetic)." : "The service gave no answer for this question.",
                 timeout: "The question answering service did not answer within the time limit.", error: `The question answering service could not be used${m.reason ? ` (${esc(m.reason)})` : ""}.` }[m.status];
  const mockTag = m.mock && m.status === "ok" ? `<p class="mock-tag">Placeholder answer (mock): question answering is under development; the citations and evidence links show the shape a real answer will have.</p>` : "";
  const body = m.status === "ok" ? `${mockTag}${paragraphs(m.content)}${other}<h3>Sources cited (${m.citations.length})</h3><ul class="citations">${m.citations.map(cite).join("")}</ul>`
             : `${line ? `<p class="notice">${line}</p>` : ""}${m.status === "not_configured" ? placeholderLinksHtml(cat) : ""}${other}`;
  const related = m.status !== "ok" && m.status !== "not_configured" && m.related?.length
    ? `<h3>Related resources <span class="meta">search results, not citations</span></h3><ul class="related-list">${m.related.slice(0, 5).map((r) => `<li>${r.in_dashboard ? `<a href="#/resource/${encodeURIComponent(r.pid)}">${esc(r.title || r.pid)}</a>` : esc(r.title || r.pid)}</li>`).join("")}</ul>`
    : m.status !== "ok" && m.status !== "not_configured" ? `<p class="dim small">No resource of this dashboard matches the words of the question.</p>` : "";
  const retry = m.status === "timeout" || m.status === "error" ? `<button type="button" class="link" data-retry="${i}">Try again</button>` : "";
  const single = m.single_turn && !m.mock && m.status !== "not_configured" ? `<p class="meta">single-turn answer: earlier turns were not sent</p>` : "";
  const toList = m.mock && question && m.related?.length ? `<p class="small"><a href="#/resources?q=${encodeURIComponent(question)}">See the matching resources in the list</a></p>` : "";
  return `<li class="msg assistant"><span class="who" aria-hidden="true">✦</span><div class="bubble-text">${body}${related}${toList}${single}${retry}</div></li>`;
}

// External discovery results, kept apart from the catalog and labelled by source. A member of this dashboard links to its
// record, an https PID links out, any other PID is named and not linked.
export function discoveryHtml(d) {
  const tag = d.mock ? `<p class="mock-tag">Mock: a local placeholder, not a real discovery service.</p>` : "";
  if (d.status === "not_configured") return `<p class="state">Discovery in ${esc(d.source)} is not configured for this site.</p>`;
  if (d.status !== "ok") return `${tag}<p class="state" role="alert">${esc(d.source)} could not be used${d.reason ? ` (${esc(d.reason)})` : ""}.</p>`;
  if (!d.items.length) return `${tag}<p class="state">No result in ${esc(d.source)} for these words.</p>`;
  const caps = d.capabilities_source === "failed" ? `<p class="meta">The service's capability declaration could not be read; relations are not shown.</p>` : "";
  const title = (it) => it.in_dashboard ? `<a href="#/resource/${encodeURIComponent(it.pid)}">${esc(it.title)}</a>`
                      : isHttps(it.pid) ? `<a href="${esc(it.pid)}" rel="noopener noreferrer" target="_blank">${esc(it.title)}</a>` : `<span>${esc(it.title)}</span>`;
  const ident = (it) => it.pid ? (isHttps(it.pid) || it.in_dashboard ? "" : ` <code>${esc(it.pid)}</code>`) : ` <span class="meta">no persistent identifier stated${it.id ? ` · ${esc(it.id)}` : ""}</span>`;
  const rel = (it) => it.relations?.length ? `<br><span class="meta">relations as stated: ${it.relations.slice(0, 5).map((r) => `${esc(r.type)} → ${esc(r.target)}`).join("; ")}</span>` : "";
  const li = (it) => `<li>${title(it)}${ident(it)} <span class="mini">${it.in_dashboard ? "already in this dashboard" : "not a member of this dashboard"}</span>
      <span class="meta">${[it.type, it.access ? `access ${it.access}` : "", it.modified ? `modified ${it.modified.slice(0, 10)}` : ""].filter(Boolean).map(esc).join(" · ")}</span>${it.description ? `<br><small>${esc(it.description)}</small>` : ""}${rel(it)}</li>`;
  return `${tag}${caps}<p class="note">${d.items.length}${d.total > d.items.length ? ` of ${d.total}` : ""} results from ${esc(d.source)}, shown apart from this dashboard and not added to it.</p><ul class="discover-list">${d.items.map(li).join("")}</ul>`;
}

// ---- list ---------------------------------------------------------------------------------
export const CAROUSEL = 3;                                     // cards per carousel page
export const LIST_PAGE = 10;                                   // rows per page of the catalogue layout
export const listLayout = (cat) => ((cat?.site || {}).resources_layout === "catalogue" ? "catalogue" : "cards");
export const pageStep = (cat) => (listLayout(cat) === "catalogue" ? LIST_PAGE : CAROUSEL);

export function listHtml(cat, st, shown, counts, openFacet, moreOpen, found = null) {
  const active = Object.values(st.filters).reduce((n, s) => n + s.size, 0);
  const facets = visibleFacets(cat);
  const main = [...(cat.facets_without_source || []).map((m) => ({ na: m })), ...facets.filter((f) => f.panel === "main").map((f) => ({ f }))];
  const more = facets.filter((f) => f.panel !== "main");
  const secondary = Boolean(st.sort !== "title" || more.some((f) => st.filters[f.id].size));
  const o = Math.min(st.o, Math.max(0, Math.floor((shown.length - 1) / CAROUSEL) * CAROUSEL));
  const page = shown.slice(o, o + CAROUSEL), last = Math.min(o + CAROUSEL, shown.length);
  const empty = !cat.rows.length
    ? `<p class="state">${esc(cat.collection.explanation || "No resource of this collection can be shown.")}</p>`
    : !shown.length ? `<div class="state"><p>No resource matches${st.q ? ` “${esc(st.q)}”` : ""}${active ? ` with the ${plural(active, "active filter")}` : ""}.</p>
        <p class="hint">Search looks in title, description, keywords, authors, claims and date. <button class="link" data-clear>Clear all</button>.</p></div>` : "";
  if (listLayout(cat) === "catalogue") return catalogueHtml(cat, st, shown, counts, openFacet, found, active, empty);
  return `<section class="content-page list-page">
    <a class="back" href="#/">‹ Back to home</a>
    ${found?.refreshed ? `<p class="notice">${REFRESHED_NOTE}</p>` : ""}
    ${cat.rows.length && cat.collection.explanation ? `<p class="notice">${esc(cat.collection.explanation)}</p>` : ""}
    <div class="box filter-box" role="region" aria-label="Filters">
      <h2><span class="section-symbol" aria-hidden="true">♧</span>Filter</h2>
      <form class="search" id="searchForm" role="search">
        <label class="sr" for="q">Search the collection</label>
        <input id="q" type="search" value="${esc(st.q)}" placeholder="Search titles, descriptions, keywords, authors and claims…" autocomplete="off"/>
        <button type="submit">Search</button>
      </form>
      ${searchSourceHtml(cat)}
      <div class="facet-row four">${main.map((m, i) => m.f ? facetHtml(m.f, st, counts[m.f.id], openFacet, TONES[i % TONES.length]) : unavailableFacetHtml(m.na, i, openFacet, TONES[i % TONES.length])).join("")}</div>
      ${chipsHtml(cat, st)}
      <details class="more-filters" id="moreFilters"${moreOpen || secondary ? " open" : ""}><summary>More filters and sort</summary>
        ${more.length ? `<div class="facet-row">${more.map((f) => facetHtml(f, st, counts[f.id], openFacet, "")).join("")}</div>` : ""}
        <div class="search"><label class="sort" for="sort">Sort</label>
          <select id="sort">${Object.entries(SORTS).map(([k, v]) => `<option value="${k}" ${k === st.sort ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      </details>
    </div>
    <div class="box results">
      <h1 class="page-title">Resources <span class="count">(${shown.length}${shown.length !== cat.counts.usable ? ` of ${cat.counts.usable}` : ""})</span></h1>
      ${empty}
      ${shown.length ? `<div class="carousel">
        <button type="button" class="arrow" id="prev" aria-label="Previous resources"${o ? "" : " disabled"}>‹</button>
        <ol class="list-grid result-cards">${page.map(cardHtml).join("")}</ol>
        <button type="button" class="arrow" id="next" aria-label="Next resources"${last < shown.length ? "" : " disabled"}>›</button>
      </div>
      <p class="carousel-state" aria-live="polite">Showing ${o + 1}–${last} of ${shown.length}</p>` : ""}
    </div>
    ${found?.truncated ? `<p class="notice">The server lists ${found.total} matching resources; the first ${shown.length} are shown here. Narrow the search to see the rest.</p>` : ""}
    ${discoverOutHtml(cat, st)}
    ${overviewHtml()}
    ${notShownHtml(cat)}
  </section>`;
}

// The catalogue layout (site.resources_layout: catalogue): a sidebar of facets with counts, the search above the
// results, one row per resource with its snippet, keywords and metadata. Same state, ids and wiring as the cards layout.
function catalogueHtml(cat, st, shown, counts, openFacet, found, active, empty) {
  const facets = visibleFacets(cat);
  const o = Math.min(st.o, Math.max(0, Math.floor((shown.length - 1) / LIST_PAGE) * LIST_PAGE));
  const page = shown.slice(o, o + LIST_PAGE), last = Math.min(o + LIST_PAGE, shown.length);
  const side = facets.map((f, i) => facetHtml(f, st, counts[f.id], openFacet === f.id || st.filters[f.id].size || !i ? f.id : null, "")).join("");
  const unavailable = (cat.facets_without_source || []).map((m, i) => unavailableFacetHtml(m, i, openFacet, "")).join("");
  const byType = new Map();
  for (const r of shown) { const t = r.resource_type[0] || "type not stated"; byType.set(t, (byType.get(t) || 0) + 1); }
  const summary = [`${shown.length} matching ${shown.length === 1 ? "resource" : "resources"} of ${cat.counts.usable} ${cat.counts.usable === 1 ? "member" : "members"}`,
                   ...[...byType.entries()].map(([t, n]) => `${n} ${esc(t)}`), cat.not_usable.length ? `${cat.not_usable.length} cannot be shown` : ""].filter(Boolean).join(" · ");
  const row = (r) => {
    const meta = [r.date ? esc(r.date) : "", r.authors.length ? esc(r.authors.slice(0, 3).join("; ")) : "", plural(r.claims, "claim"),
                  r.duplicate_title ? `same title as another record; identifier ${esc(r.pid)}` : ""].filter(Boolean).join(" · ");
    return `<li class="result-row"><span class="kind${r.resource_type.length ? "" : " unstated"}">${esc(r.resource_type[0] || "type not stated")}</span>
      <h3><a href="#/resource/${encodeURIComponent(r.pid)}">${esc(r.title)}</a></h3>
      ${r.description ? `<p class="snippet">${esc(r.description)}</p>` : ""}
      ${r.keywords.length ? `<span class="tags">${r.keywords.slice(0, 6).map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</span>` : ""}
      <span class="meta">${meta}</span></li>`;
  };
  return `<section class="content-page list-page catalogue-page">
    <a class="back" href="#/">‹ Back to home</a>
    ${found?.refreshed ? `<p class="notice">${REFRESHED_NOTE}</p>` : ""}
    ${cat.rows.length && cat.collection.explanation ? `<p class="notice">${esc(cat.collection.explanation)}</p>` : ""}
    <div class="catalogue">
      <aside class="facet-side" role="region" aria-label="Filters"><h2>Filter by</h2>${side}
        ${unavailable ? `<p class="group-label">Not available yet</p>${unavailable}` : ""}</aside>
      <div class="catalogue-main">
        <h1 class="page-title">Resources <span class="count">(${shown.length}${shown.length !== cat.counts.usable ? ` of ${cat.counts.usable}` : ""})</span></h1>
        <form class="search" id="searchForm" role="search">
          <label class="field-label" for="q">Search the collection</label>
          <input id="q" type="search" value="${esc(st.q)}" placeholder="title, description, keywords, authors, claims, date" autocomplete="off"/>
          <button type="submit">Search</button>
          <label class="sort" for="sort">Sort</label>
          <select id="sort">${Object.entries(SORTS).map(([k, v]) => `<option value="${k}" ${k === st.sort ? "selected" : ""}>${v}</option>`).join("")}</select>
        </form>
        ${searchSourceHtml(cat)}
        <p class="result-summary">${summary}</p>
        ${chipsHtml(cat, st)}
        ${empty}
        ${shown.length ? `<ol class="result-list">${page.map(row).join("")}</ol>
        <div class="pager"><button type="button" class="arrow" id="prev" aria-label="Previous resources"${o ? "" : " disabled"}>‹</button>
          <p class="carousel-state" aria-live="polite">Showing ${o + 1}–${last} of ${shown.length}</p>
          <button type="button" class="arrow" id="next" aria-label="Next resources"${last < shown.length ? "" : " disabled"}>›</button></div>` : ""}
        ${found?.truncated ? `<p class="notice">The server lists ${found.total} matching resources; the first ${shown.length} are shown here. Narrow the search to see the rest.</p>` : ""}
      </div>
    </div>
    ${discoverOutHtml(cat, st)}
    ${overviewHtml()}
    ${notShownHtml(cat)}
  </section>`;
}

// Under the search box: what the words are matched against, and the external graph search that plugs in here (named by
// the configuration; not connected in mode disabled, a labelled mock in mode mock). Its results never join the list.
function discoverySource(cat) {
  const d = (cat.site || {}).discovery || {};
  const mode = ["remote", "mock"].includes(d.mode) ? d.mode : "disabled";
  return { d, mode, source: mode === "mock" ? (d.demo_label || "Mock discovery (synthetic)") : (d.label || "the repository") };
}

function searchSourceHtml(cat) {
  const { d, mode, source } = discoverySource(cat);
  if (mode === "disabled" && !d.label) return "";
  const text = mode === "disabled" ? (d.note || `${d.label} is not connected yet; until then the words are matched against this dashboard's catalog only.`)
    : `The words are matched against this dashboard's catalog and sent to ${source}; its results are shown below the dashboard's, apart from them, and are not added to it.`;
  return `<p class="search-source">${mode === "mock" ? `<span class="mock-tag">Mock: a local placeholder, not a real discovery service.</span> ` : ""}${esc(text)}</p>`;
}

// The place for the external results, present only when words were searched and a service is configured; app.js fills it.
function discoverOutHtml(cat, st) {
  const { mode, source } = discoverySource(cat);
  if (mode === "disabled" || !st.q) return "";
  return `<div class="box discover-box" role="region" aria-labelledby="discoverH"><h2 id="discoverH">From ${esc(source)}</h2><div id="discoverOut" aria-live="polite"><p class="state">Searching…</p></div></div>`;
}

// The API provider did not answer: said as such, with a retry; the page never searches the catalog instead.
export function searchErrorHtml(found, provider) {
  const why = { timeout: "did not answer within the time limit", error: `could not be used${found.reason ? ` (${found.reason})` : found.http ? ` (HTTP ${found.http})` : ""}` }[found.status] || "did not answer";
  return `<section class="content-page list-page"><a class="back" href="#/">‹ Back to home</a>
    <div class="box results"><h1 class="page-title">Resources</h1><div class="state error" role="alert"><p>The search service ${esc(why)}.</p>
    <p class="hint">This site searches through its server${provider?.endpoint ? ` (${esc(provider.endpoint)})` : ""}; no results are shown until it answers. <button class="link" id="retrySearch">Try again</button></p></div></div></section>`;
}

// The overview of the resources shown is not defined yet (TBD); the claims a resource states stay on its record page.
export function overviewHtml() {
  return `<section class="box overview"><h2>Overview</h2><p class="state">TBD</p></section>`;
}

function facetHtml(f, st, counts, openFacet, tone) {
  const selected = st.filters[f.id].size;
  const items = f.values.map((v, vi) => {
    const on = st.filters[f.id].has(v.value); const n = counts[v.value] || 0;
    const dead = !n && !on;
    return `<li><button type="button" class="facet-value${on ? " on" : ""}${dead ? " dim" : ""}" id="f-${esc(f.id)}-${vi}" data-facet="${esc(f.id)}" data-value="${esc(v.value)}" aria-pressed="${on}"${dead ? ' aria-disabled="true"' : ""}>
      <span>${esc(v.value)}</span><i aria-hidden="true">${on ? "✕" : n}</i><span class="sr">${on ? ", selected, remove" : `, ${plural(n, "resource")}`}</span></button></li>`;
  }).join("");
  return `<details class="facet ${tone}" data-facet="${esc(f.id)}"${openFacet === f.id ? " open" : ""}><summary>${f.icon ? `<span class="pill-ico" aria-hidden="true">${esc(f.icon)}</span>` : ""}${esc(f.label)}${selected ? ` <b aria-hidden="true">${selected}</b><span class="sr">, ${selected} selected</span>` : ""}</summary>
    <ul class="facet-list">${items || `<li class="dim small">no values stated</li>`}</ul></details>`;
}

// A control of the design whose values no record states yet: it opens to say so, it filters nothing.
function unavailableFacetHtml(m, i, openFacet, tone) {
  const id = `na-${i}`;
  return `<details class="facet unavailable ${tone}" data-facet="${id}"${openFacet === id ? " open" : ""}><summary><span class="pill-ico" aria-hidden="true">${esc(m.icon || "♨")}</span>${esc(m.label)}<span class="sr">, not available yet</span></summary>
    <ul class="facet-list"><li class="dim small">${esc(m.why)}</li></ul></details>`;
}

function chipsHtml(cat, st) {
  const chips = [];
  if (st.q) chips.push(`<button class="chip" data-remove="q" aria-label="Remove search ${esc(st.q)}">Search: ${esc(st.q)} <i aria-hidden="true">✕</i></button>`);
  for (const f of visibleFacets(cat)) for (const v of st.filters[f.id]) chips.push(`<button class="chip" data-remove="${esc(f.id)}" data-value="${esc(v)}" aria-label="Remove filter ${esc(f.label)} ${esc(v)}">${esc(f.label)}: ${esc(v)} <i aria-hidden="true">✕</i></button>`);
  return chips.length ? `<div class="chips active-chips">${chips.join("")}<button class="link" data-clear>Clear all</button></div>` : "";
}

function cardHtml(row) {
  const type = row.resource_type[0] || "type not stated";
  const meta = [row.authors.length ? esc(row.authors.join("; ")) : "", row.year ? esc(row.year) : ""].filter(Boolean).join(" · ");
  return `<li><a class="resource-card" href="#/resource/${encodeURIComponent(row.pid)}" aria-labelledby="t-${esc(row.key)}">
    <span class="kind ${row.resource_type.length ? "" : "unstated"}">${esc(type)}</span>
    <h3 id="t-${esc(row.key)}">${esc(row.title)}</h3>
    ${meta ? `<span class="meta">${meta}</span>` : ""}
    ${row.duplicate_title ? `<span class="meta dim">identifier …/${esc(tail(row.pid))}</span>` : ""}
    ${row.keywords.length ? `<span class="tags">${row.keywords.slice(0, 3).map((k, i) => `<span class="tag ${TONES[i % TONES.length]}">${esc(k)}</span>`).join("")}</span>` : ""}</a></li>`;
}

function notShownHtml(cat) {
  if (!cat.not_usable.length) return "";
  return `<details class="not-shown"><summary>${plural(cat.not_usable.length, "resource")} of the collection cannot be shown</summary>
    <ul>${cat.not_usable.map((r) => `<li><a href="#/resource/${encodeURIComponent(r.pid)}">${esc(r.pid)}</a><br>${esc(r.explanation)}</li>`).join("")}</ul></details>`;
}

// ---- resource page ---------------------------------------------------------------------------
const CLAIMS_FIRST = 3;                                        // claims shown before "View all claims"
const ACCESS_WORD = { open: "Public", restricted: "Restricted", unknown: "Access not stated" };
const facetHash = (fid, value) => `#/resources?${encodeURIComponent(fid)}=${encodeURIComponent(value)}`;
const formatOf = (mediaType) => mediaType ? mediaType.split("/").pop().replace(/^(vnd\.|x-)/, "") : "";

export function resourceHtml(cat, rec, backHash) {
  const back = `<a class="back" href="${esc(backHash)}">‹ Back to resources</a>`;
  if (!rec.source.usable) {
    return `<section class="content-page resource-page">${back}<article class="box resource-head"><span class="kind unstated">resource</span><h1>This resource cannot be shown</h1>
      <p class="lead">${esc(rec.source.explanation)}</p><p class="meta">Listed as ${link(rec.pid)}</p></article></section>`;
  }
  const keywordFacet = visibleFacets(cat).find((f) => f.concept === "keywords");
  const unread = unreadText(rec.source.record);
  return `<section class="content-page resource-page">${back}
    <article class="box resource-head">
      <div class="head-row"><span class="kind ${rec.resource_type.length ? "" : "unstated"}">${esc(rec.resource_type.join(", ") || (notRead(rec, "type") ? "type not read by this site" : "type not stated"))}</span>${rec.year ? `<span class="year">${esc(rec.year)}</span>` : ""}</div>
      <h1>${esc(rec.title)}</h1>
      ${rec.authors.length ? `<p class="authors">${esc(rec.authors.join("; "))}</p>` : ""}
      ${rec.description ? descriptionHtml(rec.description) : `<p class="lead dim">${notRead(rec, "description") ? "Description not read by this site." : "No description stated."}</p>`}
      ${rec.keywords.length ? `<p class="tags">${rec.keywords.map((k, i) => `<a class="tag ${TONES[i % TONES.length]}" href="${keywordFacet ? facetHash(keywordFacet.id, k) : "#/resources"}">${esc(k)}</a>`).join("")}</p>` : ""}
      ${unread ? `<p class="warn-line">Parts of this record could not be read (${unread}), so some of its information may be missing below.</p>` : ""}
      ${isHttp(rec.pid) ? `<a class="pill-btn solid" href="${esc(rec.pid)}" rel="noopener noreferrer" target="_blank">View original source</a>` : ""}
    </article>
    <div class="resource-grid">
      <div class="resource-main">${claimsHtml(rec)}</div>
      <aside class="box factsheet" aria-labelledby="fsh"><h2 id="fsh">About this resource</h2>${factsHtml(rec)}${techHtml(rec, cat)}</aside>
    </div>
    ${productsHtml(rec)}
    ${relatedHtml(rec)}
  </section>`;
}

function assertedHtml(rel) {
  if (!rel) return "";
  const href = memberHref(rel);
  const name = rel.title ? (href ? `<a href="${href}">${esc(rel.title)}</a>` : esc(rel.title)) : (rel.is_pid ? link(rel.pid) : esc(rel.pid));
  const where = rel.is_pid ? "" : " (a record inside this resource, no identifier yet)";
  const status = rel.status ? ` · status as stated: ${esc(rel.status)}` : "";
  return `<span class="source">Asserted in: ${name}${where}${status}</span>`;
}

function claimsHtml(rec) {
  if (!rec.claims.length) {
    const c = rec.source.claims;
    const unreadable = !c.usable || c.notes.some((n) => n.code === "profile.term_undefined") || rec.source.record.unknown_terms.length;
    return `<section class="box claims-box"><h2>Claims</h2><p class="dim">${unreadable
      ? "No claim or statement could be read from this resource here; it may still carry some."
      : "This resource states no claim or statement."}</p></section>`;
  }
  const kinds = [...new Set(rec.claims.map((c) => c.kind))];
  const heading = kinds.length === 1 && kinds[0] === "statement" ? "Statements" : "Claims";   // nanopublications are claims the record links
  // text_kind "name": the text is the part's registered name, not an assertion; it is not quoted.
  const textHtml = (c) => !c.text ? `<p class="dim">text not stated by the record</p>`
    : c.text_kind === "name" ? `<p class="claim-text"><span class="meta">Named in the record as:</span> ${esc(c.text)}</p>${c.text_cut ? `<span class="source">(the name ends with an ellipsis in the record)</span>` : ""}`
    : `<p class="claim-text">“${esc(c.text)}”</p>`;
  const author = (a) => isHttp(a.iri) ? `<a href="${esc(a.iri)}" rel="noopener noreferrer" target="_blank">${esc(a.label || a.iri)}</a>` : esc(a.label || a.iri);
  const li = (c) => `<li>${textHtml(c)}
      ${c.concepts.length ? `<span class="tags"><span class="meta">Concepts as stated:</span>${c.concepts.map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</span>` : ""}
      ${c.kind === "nanopublication" ? `<span class="source">Nanopublication: ${link(c.asserted_in.pid)}</span>`
        : c.kind === "linked_nanopublication" ? `<span class="source">Nanopublication identifier (type inferred): ${link(c.asserted_in.pid)}</span>` : assertedHtml(c.asserted_in)}
      ${Array.isArray(c.asserted_by) && c.asserted_by.length ? `<span class="source">asserted by ${c.asserted_by.map(author).join("; ")}</span>` : ""}
      ${c.note ? `<span class="source warn-text">${esc(c.note)}</span>` : ""}</li>`;
  const first = rec.claims.slice(0, CLAIMS_FIRST), rest = rec.claims.slice(CLAIMS_FIRST);
  return `<section class="box claims-box"><h2>${heading} <span class="count">(${rec.claims.length})</span></h2>
    <p class="note">As stated by the record, not as verified findings.</p>
    <ul class="claims">${first.map(li).join("")}</ul>
    ${rest.length ? `<details class="all-claims"><summary>View all claims (${rec.claims.length})</summary><ul class="claims">${rest.map(li).join("")}</ul></details>` : ""}
  </section>`;
}

function unitHtml(v) {
  if (v.unit) return esc(v.unit);
  if (v.unit_code) return `<span title="${esc(v.unit_code)}">${esc(tail(v.unit_code))} <span class="dim">(code)</span></span>`;
  return "not stated";
}

// A file is linked only when it is open and has a URL; a restricted or unlinked file is named, never offered.
// A DOI is a public identifier, not a file: it is linked and said to be one.
const isDoi = (u) => /^https:\/\/doi\.org\//i.test(String(u || ""));
const fileLi = (f) => isDoi(f.url)
  ? `<li><a href="${esc(f.url)}" rel="noopener noreferrer" target="_blank"><code>${esc(f.path)}</code></a> — DOI, public identifier</li>`
  : `<li>${isHttp(f.url) && f.access === "open" ? `<a href="${esc(f.url)}" rel="noopener noreferrer" target="_blank"><code>${esc(f.path)}</code></a>` : `<code>${esc(f.path)}</code>`} — ${esc(f.media_type || "format not stated")}, ${esc(ACCESS[f.access] || f.access)}${f.url && f.access !== "open" ? " (link not shown: access not stated as open)" : ""}</li>`;

// One data product as a card: name, format, access, an action only where a public link exists; the rest under "Technical details".
function productHtml(d) {
  const state = d.access.state;
  const formats = [...new Set(d.files.map((f) => formatOf(f.media_type)).filter(Boolean))];
  const open = state === "open" ? d.files.filter((f) => isHttp(f.url) && f.access === "open") : [];
  const action = state === "restricted"
    ? `<span class="access-note">${d.access.conditions.length ? esc(d.access.conditions.join("; ")) : "Access on request; no public link"}</span>`
    : open.length ? open.map((f) => `<a class="pill-btn solid" href="${esc(f.url)}" rel="noopener noreferrer" target="_blank">Open ${esc(tail(f.path))}</a>`).join(" ")
    : isHttp(d.pid) ? `<a class="pill-btn" href="${esc(d.pid)}" rel="noopener noreferrer" target="_blank">Open resource</a>`
    : `<span class="access-note dim">${d.files.length ? "Files listed in the record; no public link yet" : "No file stated for this product"}</span>`;
  return `<article class="product-card">
    <span class="badge ${esc(state)}">${esc(ACCESS_WORD[state] || state)}</span>
    <h3>${esc(d.name || d.id)}</h3>
    <p class="meta">${formats.length ? `Format: ${esc(formats.join(", "))}` : "Format not stated"}${d.variables.length ? ` · ${plural(d.variables.length, "variable")}` : ""}</p>
    <div class="actions">${action}</div>
    <details class="tech"><summary>Technical details</summary>
      <p class="meta">Access conditions as stated: ${d.access.conditions.length ? esc(d.access.conditions.join("; ")) : "none"}</p>
      <p class="meta">Extent: ${d.extent.box ? `as stated, box ${esc(d.extent.box)}` : "not stated"}</p>
      ${d.variables.length ? `<table class="vars"><thead><tr><th scope="col">variable</th><th scope="col">unit (as stated)</th><th scope="col">description</th></tr></thead><tbody>
        ${d.variables.map((v) => `<tr><td><code>${esc(v.name)}</code></td><td>${unitHtml(v)}</td><td>${esc(v.description || "")}</td></tr>`).join("")}</tbody></table>` : `<p class="meta">No variables stated.</p>`}
      ${d.files.length ? `<ul class="files">${d.files.map(fileLi).join("")}</ul>` : `<p class="meta">No file stated.</p>`}
    </details>
  </article>`;
}

// A DOI or a nanopublication identifier is a reference to another record, not a file of this one.
const isReference = (f) => isDoi(f.url) || /^https:\/\/w3id\.org\/sciencelive\/np\//i.test(String(f.url || ""));
const sameIri = (a, b) => String(a || "").replace(/\/+$/, "") === String(b || "").replace(/\/+$/, "");
const referenceLi = (f, claimed) => `<li>${link(f.url)}${isDoi(f.url) ? ` <span class="meta">DOI</span>` : ` <span class="meta">nanopublication</span>`}${claimed ? ` <span class="meta">(shown above as a claim)</span>` : ""}</li>`;

function productsHtml(rec) {
  const inProducts = new Set(rec.datasets.flatMap((d) => d.files.map((f) => f.path)));
  const other = rec.files.filter((f) => !inProducts.has(f.path));
  const references = other.filter(isReference), files = other.filter((f) => !isReference(f));
  const claimed = (f) => rec.claims.some((c) => sameIri(c.asserted_in?.pid, f.url));
  if (!rec.datasets.length && !other.length) return "";
  return `${references.length ? `<section class="box references"><h2>References <span class="count">(${references.length})</span></h2><p class="note">Identifiers this resource links to; they open at their publisher, they are not files of this resource.</p><ul class="files">${references.map((f) => referenceLi(f, claimed(f))).join("")}</ul></section>` : ""}
    ${rec.datasets.length || files.length ? `<section class="box products"><h2>Available data products <span class="count">(${rec.datasets.length})</span></h2>
    ${rec.datasets.length ? `<div class="product-grid">${rec.datasets.map(productHtml).join("")}</div>` : `<p class="dim">This resource states no data product.</p>`}
    ${files.length ? `<details class="tech"><summary>${rec.datasets.length ? "Other files of this resource" : "Files of this resource"} (${files.length})</summary><ul class="files">${files.map(fileLi).join("")}</ul></details>` : ""}
  </section>` : ""}`;
}

function relatedHtml(rec) {
  const items = [...rec.related.map((r) => ({ ...r, label: "" })), ...rec.based_on.map((r) => ({ ...r, label: "Based on: " }))];
  if (!items.length) return "";
  return `<section class="box related-box"><h2>Related resources</h2><ul class="related-list">${items.map((r) => {
    const href = memberHref(r);
    const name = r.title ? (href ? `<a href="${href}">${esc(r.title)}</a>` : esc(r.title)) : (r.is_pid ? link(r.pid) : esc(r.pid));
    const note = [r.is_pid ? "" : "inside this resource, no identifier yet", href ? "in this collection" : ""].filter(Boolean).join("; ");
    return `<li>${r.label}${name}${note ? ` <span class="dim small">(${note})</span>` : ""}</li>`; }).join("")}</ul></section>`;
}

function accessHtml(rec) {
  const own = `${esc(label(ACCESS, rec.access.state))}${rec.access.conditions.length ? `; conditions as stated: ${rec.access.conditions.map(esc).join("; ")}` : ""}`;
  const states = rec.datasets.map((d) => d.access.state).filter((s) => s !== "unknown");
  if (!states.length) return own;
  const summary = Object.entries(states.reduce((acc, s) => ({ ...acc, [s]: (acc[s] || 0) + 1 }), {})).map(([s, n]) => `${n} ${esc(ACCESS[s] || s)}`).join(", ");
  return `${rec.access.state === "unknown" ? "not stated at resource level" : own}; per data product: ${summary}`;
}

const STATUS_WORD = { PASS: "pass", PARTIAL: "partial", INDETERMINATE: "indeterminate", FAIL: "fail", NOT_ATTEMPTED: "not attempted" };
const statusHtml = (s) => `<span class="${s === "PASS" ? "ok-text" : s === "PARTIAL" ? "dim" : "warn-text"}">${esc(STATUS_WORD[s] || String(s || "unknown").toLowerCase())}</span>`;

// How the record was read: the map, the overlay, and fdo-consume's statuses as they are, never flattened to a pass.
function readingHtml(rec) {
  const r = rec.source?.record || {};
  if (!r.statuses) return "";
  const map = r.map ? `${esc(r.map)}${r.overlay ? ` + ${esc(r.overlay)}` : ""}` : "no map";
  return `${map} · validation ${statusHtml(r.statuses.validation)}${r.validator && !r.validator.ran ? ` <span class="dim">(validator not run)</span>` : ""} · compatibility ${statusHtml(r.statuses.compatibility)}`;
}

// The terms and contexts the reader could not expand, by name; empty when the record was fully read.
function unreadText(r) {
  const terms = r?.unknown_terms || [], contexts = r?.unknown_contexts || [];
  return [terms.length ? `terms: ${terms.map(esc).join(", ")}` : "", contexts.length ? `contexts: ${contexts.map(esc).join(", ")}` : ""].filter(Boolean).join("; ");
}

// Three states per field: a value as stated, "not stated" (the record carries none), "not read by this site" (record.not_read).
function factsHtml(rec) {
  const row = (k, v) => `<tr><th scope="row">${k}</th><td>${v}</td></tr>`;
  const stated = (field, v) => notRead(rec, field) ? NOT_READ : v;
  const none = `<span class="dim">not stated</span>`;
  const authors = rec.authors.length ? rec.authors.map((a) => link(a)).join("; ") + (rec.author_ids.length ? `<br><span class="small">${rec.author_ids.map(link).join("; ")}</span>` : "") : none;
  const licence = rec.licence ? `${link(rec.licence.iri)}${rec.licence.label ? ` <span class="dim small">(${esc(rec.licence.label)}; label by this site)</span>` : ""}` : none;
  const identifier = rec.identifier && rec.identifier !== rec.pid ? row("Identifier stated", link(rec.identifier)) : (!rec.identifier ? row("Identifier stated", `<span class="dim">not stated by the record</span>`) : "");
  const extent = rec.datasets.some((d) => d.extent?.box);
  return `<table class="facts">${row("Source identifier", link(rec.pid))}${identifier}
    ${row("Authors", stated("authors", authors))}
    ${row("Date (as stated)", stated("date", rec.date ? esc(rec.date) : none))}
    ${rec.status ? row("Status (as stated)", esc(rec.status)) : ""}
    ${row("Licence (as stated)", stated("licence", licence))}
    ${row("Access", stated("access", accessHtml(rec)))}
    ${row("Coverage", `<span class="dim">not read at record level${extent ? "; data products state their extent where given" : ""}</span>`)}</table>`;
}

// How the record was read, for readers who want it: map and statuses, what was not read, where the crate came from, the hash.
function techHtml(rec, cat) {
  const r = rec.source?.record || {};
  const note = cat.site?.map_notes?.[r.map];
  const rows = [readingHtml(rec) ? ["Read through", readingHtml(rec)] : null, unreadText(r) ? ["Not fully read", unreadText(r)] : null,
                r.located ? ["Located", esc(r.located)] : null, note ? ["Map note", esc(note)] : null, r.record_sha256 ? ["Record hash", `<code>${esc(r.record_sha256)}</code>`] : null].filter(Boolean);
  if (!rows.length) return "";
  return `<details class="tech"${cat.diagnostics_open ? " open" : ""}><summary>Technical details</summary>${rows.map(([k, v]) => `<p class="meta"><b>${k}:</b> ${v}</p>`).join("")}</details>`;
}

// ---- shared --------------------------------------------------------------------------------------
export function textPageHtml(title, text, extra = "") {
  return `<section class="content-page"><a class="back" href="#/">‹ Back to home</a><h1 class="page-title">${esc(title)}</h1><div class="info-box">${paragraphs(text) || `<p class="dim">No text configured.</p>`}${extra}</div></section>`;
}

// A site built from a Dashboard FDO says so on its about page, with the keys the FDO set.
export function compositionHtml(cat) {
  const c = cat.composition;
  if (!c || !c.pid) return "";
  const keys = Array.isArray(c.keys_from_fdo) && c.keys_from_fdo.length ? c.keys_from_fdo.map(esc).join(", ") : "none";
  return `<p>This site was composed from the Dashboard FDO ${link(c.pid)}; it set: ${keys}.</p>`;
}

export function missingHtml(backHash) {
  return `<section class="content-page"><a class="back" href="${esc(backHash)}">‹ Back to resources</a><h1 class="page-title">No resource with this identifier</h1><p class="state">No resource of this collection has this identifier.</p></section>`;
}

export function loadingHtml(backHash) {
  return `<section class="content-page"><a class="back" href="${esc(backHash)}">‹ Back to resources</a><p class="state">Loading the resource…</p></section>`;
}
