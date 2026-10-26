// A conversation: ordered user and assistant messages with bounds, kept in memory and, when the page allows it, in
// sessionStorage (this tab only). The id is chosen by the browser; it identifies nothing beyond this conversation.
export const LIMITS = { turns: 20, message: 2000, history: 6, context: 1000, storage: 65536 };
export const STORE = "fdo-knowledge-dashboard.conversation";
export const storeKey = () => `${STORE}:${globalThis.location?.pathname || ""}`;        // one key per dashboard on an origin
export const collectionOf = (cat) => cat?.collection?.pid || cat?.site?.title || "";     // what a stored conversation belongs to

const now = () => new Date().toISOString();
const newId = () => (globalThis.crypto?.randomUUID ? crypto.randomUUID() : `c-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`);

export function newConversation(collection = "") {
  return { id: newId(), collection, messages: [], created_at: now(), updated_at: now() };
}

// The user's turn, trimmed and bounded; null when the conversation is full or the text is empty.
export function addUser(c, text) {
  const content = String(text || "").trim().slice(0, LIMITS.message);
  if (!content || userTurns(c) >= LIMITS.turns) return null;
  const message = { role: "user", content, at: now() };
  c.messages.push(message);
  c.updated_at = message.at;
  return message;
}

// The assistant's turn as the service answered it: status, answer text, citations or related matches, generation.
export function addAssistant(c, result) {
  const message = { role: "assistant", content: result.answer || "", status: result.status, citations: result.citations || [], related: result.related || [],
                    generation_id: result.generation_id || null, provider: result.provider || null, mock: Boolean(result.mock), reason: result.reason || null,
                    single_turn: Boolean(result.single_turn), at: now() };
  c.messages.push(message);
  c.updated_at = message.at;
  return message;
}

export const userTurns = (c) => c.messages.filter((m) => m.role === "user").length;
export const full = (c) => userTurns(c) >= LIMITS.turns;

// The prior turns sent with a question: the last few, text only, each bounded; the current question is not among them.
export function historyOf(c) {
  const prior = c.messages.filter((m) => m.role === "user" || (m.role === "assistant" && m.content));
  return prior.slice(-LIMITS.history * 2).map((m) => ({ role: m.role, content: String(m.content).slice(0, LIMITS.context) }));
}

export function save(c, storage) {
  if (!storage) return false;
  try {
    let text = JSON.stringify(c);
    while (text.length > LIMITS.storage && c.messages.length > 2) { c.messages.splice(0, 2); text = JSON.stringify(c); }
    storage.setItem(storeKey(), text);
    return true;
  } catch { return false; }
}

// A stored conversation of another collection than the one shown is discarded.
export function load(storage, collection) {
  if (!storage) return null;
  try {
    const c = JSON.parse(storage.getItem(storeKey()) || "null");
    if (!c || typeof c.id !== "string" || !Array.isArray(c.messages)) return null;
    if (collection !== undefined && c.collection !== collection) { storage.removeItem(storeKey()); return null; }
    return c;
  } catch { return null; }
}

export function clear(storage) {
  try { storage?.removeItem(storeKey()); } catch { /* storage unavailable */ }
}
