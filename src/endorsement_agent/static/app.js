// Endorsement agent UI. Plain JS, no build step. Everything shown comes from the session's
// SSE stream: case events (chat, activity, trace), token deltas, status bars, turn ends.
"use strict";

const STAGES = ["Intake", "Docs", "Validate", "Approval", "Insurer", "Done"];
const $ = (id) => document.getElementById(id);

const state = {
  sid: null,
  source: null,
  events: [],
  lastSeq: 0,
  draft: null,          // the assistant entry's text receiving tokens
  note: null,           // the margin note collecting the current model step's tool calls
  calls: new Map(),     // call_id -> {line, node} in a margin note
  attachments: [],      // {filename, mime, data (base64)}
  dock: null,           // {caseId, docs: [{name, sent}]}: the demo case's documents, added at will
  busy: false,
  replaying: false,
  live: false,          // past the replayed backlog of the case's stream
  status: null,        // the last status bar, so a name change can re-render the assignee
  submitted: null,      // insurer ref just submitted, celebrated when the turn settles
  insurer: null,        // the insurer named on the last approval card
  thinking: null,       // {node, phrase, detail, timer}: the agent's placeholder while it works
};

// --- helpers ---------------------------------------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Just enough markdown for agent replies: paragraphs, "- " lists, **bold**. Escaped first.
function renderMarkdown(text) {
  const inline = (s) => escapeHtml(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  const out = [];
  let list = null;
  for (const line of text.split("\n")) {
    const item = line.match(/^\s*[-*•]\s+(.*)/) || line.match(/^\s*\d+[.)]\s+(.*)/);
    if (item) {
      list = list || [];
      list.push(`<li>${inline(item[1])}</li>`);
      continue;
    }
    if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; }
    const head = line.match(/^#{1,3}\s+(.*)/);
    if (head) out.push(`<h4>${inline(head[1])}</h4>`);
    else if (line.trim()) out.push(`<p>${inline(line)}</p>`);
  }
  if (list) out.push(`<ul>${list.join("")}</ul>`);
  return out.join("");
}

// Every tool and skill name shown in the UI links to its entry on the Agent Documentation tab.
const refHref = (kind, name) => `#/ref/${kind}/${encodeURIComponent(name)}`;
const refLink = (kind, name, text = name) => el("a", { class: "ref-link", href: refHref(kind, name), "data-ref": "", text });

// Skill ids named by a call: load_skill {name}, read_skill_file {skill}.
const skillOf = (tool, args) => (tool === "load_skill" ? args?.name : tool === "read_skill_file" ? args?.skill : null);

const ms = (a, b) => new Date(b) - new Date(a);
const secs = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${n}ms`);
const short = (v, n = 60) => { const s = typeof v === "string" ? v : JSON.stringify(v); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
const clock = (ts) => new Date(ts ?? Date.now()).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const kTok = (n) => `${(n / 1000).toFixed(1)}k`;
const isRefused = (content) => /^(refused|error)/.test(content);
const docName = (id, events) => events.find((x) => x.type === "document.uploaded" && x.doc_id === id)?.filename || id;

// Tools that mark a turning point: a highlight on the margin note and the trace row.
const MARKS = new Set(["ask_user", "request_approval", "handover", "submit_to_insurer", "respond_to_insurer"]);

// "classify_document ×2 · extract_fields": names in call order, repeats counted.
function tally(names) {
  const counts = new Map();
  for (const n of names) counts.set(n, (counts.get(n) || 0) + 1);
  return [...counts].map(([n, k]) => (k > 1 ? `${n} ×${k}` : n)).join(" · ");
}

async function api(path, body, headers = {}) {
  const r = await fetch(path, body === undefined ? { method: "POST", headers } : {
    method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { const j = await r.json(); detail = typeof j.detail === "string" ? j.detail : "invalid request"; } catch { /* not JSON */ }
    throw Object.assign(new Error(detail), { status: r.status });
  }
  return r.json();
}

function scrollDown(node) { node.scrollTop = node.scrollHeight; }

// --- session ---------------------------------------------------------------------------------

// Cases live in server memory until it restarts (ADR-0022). The page only needs a case id to
// show one: the stream replays its whole event log. The id sits in the URL (?case=), so a reload
// re-attaches, and this browser keeps a short list of its cases to switch between.
const CASES_KEY = "cases";
const MAX_CASES = 12;
const gone = (sid) => `Case ${sid} isn't on the server any more. Cases live in memory: a restart, or two idle hours, clears them.`;
// Opening a case may need an invite code (ADR-0025). It is asked for once and kept here.
const INVITE_KEY = "invite";

function savedCases() {
  try { return JSON.parse(localStorage.getItem(CASES_KEY)) || []; } catch { return []; }
}

function saveCases(cases) {
  try { localStorage.setItem(CASES_KEY, JSON.stringify(cases.slice(0, MAX_CASES))); } catch { /* storage blocked: no list */ }
  renderCases();
}

// Newest first; an update keeps the case where it is.
function rememberCase(id, patch = {}) {
  const cases = savedCases();
  const i = cases.findIndex((c) => c.id === id);
  if (i < 0) cases.unshift({ id, label: "", dock: null, ...patch });
  else cases[i] = { ...cases[i], ...patch };
  saveCases(cases);
}

async function pruneCases() {
  const cases = savedCases();
  const alive = await Promise.all(cases.map((c) => fetch(`/api/sessions/${encodeURIComponent(c.id)}`).then((r) => r.ok, () => true)));
  saveCases(cases.filter((_, i) => alive[i]));
}

function renderCases() {
  const cases = savedCases();
  $("cases").replaceChildren(...cases.map((c) => el("option", { value: c.id, text: c.label ? `${c.id} · ${c.label}` : c.id })));
  $("cases").value = state.sid || "";
  $("cases").hidden = !cases.length;
}

function resetView() {
  if (state.source) state.source.close();
  hideThinking();
  Object.assign(state, { sid: null, source: null, events: [], lastSeq: 0, draft: null, note: null, live: false, attachments: [], submitted: null });
  state.calls.clear();
  setBusy(false);
  for (const id of ["chat", "trace", "context"]) $(id).replaceChildren();
  $("approval").hidden = true;
  $("pad-title").textContent = "Case notes";
  $("pad-date").textContent = "";
  renderSlots([]);
  renderAttachments();
}

function connect(sid) {
  state.sid = sid;
  history.replaceState(null, "", `?case=${encodeURIComponent(sid)}${location.hash}`);
  renderCases();
  const source = new EventSource(`/api/sessions/${encodeURIComponent(sid)}/stream`);
  source.addEventListener("event", (m) => onCaseEvent(JSON.parse(m.data)));
  source.addEventListener("token", (m) => onToken(JSON.parse(m.data).text));
  source.addEventListener("status", (m) => onStatus(JSON.parse(m.data)));
  source.addEventListener("turn", (m) => onTurn(JSON.parse(m.data)));
  source.addEventListener("agent_error", (m) => {
    hideThinking();
    addEntry("error", JSON.parse(m.data).message);
    state.draft = null;
  });
  state.source = source;
}

// A new case keeps the in-tray, with none of its documents sent yet.
async function newCase() {
  if (state.replaying) return;
  const dock = state.dock?.caseId ?? null;
  resetView();
  let session_id;
  try {
    ({ session_id } = await openSession());
  } catch (err) {
    addEntry("error", err.message);
    return;
  }
  setDock(dock);
  rememberCase(session_id, { dock });
  connect(session_id);
}

async function openSession() {
  let code;
  try { code = localStorage.getItem(INVITE_KEY) || ""; } catch { code = ""; }
  for (;;) {
    try {
      return await api("/api/sessions", undefined, code ? { "X-Invite-Code": code } : {});
    } catch (err) {
      if (err.status !== 403) throw err;
      code = (prompt(code ? "That invite code didn't work. Try again:" : "This demo needs an invite code:") || "").trim();
      if (!code) throw new Error("An invite code is needed to open a case.");
      try { localStorage.setItem(INVITE_KEY, code); } catch { /* storage blocked: asked again next time */ }
    }
  }
}

// False if the server no longer has the case.
async function openCase(sid) {
  if (sid === state.sid) return true;
  const r = await fetch(`/api/sessions/${encodeURIComponent(sid)}`);
  if (!r.ok) {
    saveCases(savedCases().filter((c) => c.id !== sid));
    return false;
  }
  resetView();
  setDock(savedCases().find((c) => c.id === sid)?.dock ?? null);
  rememberCase(sid);
  connect(sid);
  return true;
}

async function start() {
  await Promise.all([loadDemo(), pruneCases()]);
  const wanted = new URLSearchParams(location.search).get("case");
  if (wanted && (await openCase(wanted))) return;
  await newCase();
  if (wanted) addEntry("error", `${gone(wanted)} This is a new one.`);
}

// --- stream handlers -------------------------------------------------------------------------

function onCaseEvent(e) {
  if (e.seq <= state.lastSeq) return;  // a reconnect may resend
  state.lastSeq = e.seq;
  state.events.push(e);
  if (e.type === "case.created") $("pad-date").textContent = new Date(e.ts).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  if (e.type === "insurer.submitted") state.submitted = e.ref;
  if (e.type === "policy.selected") {
    $("pad-title").textContent = `Case notes · ${e.policy.policy_no}`;
    rememberCase(state.sid, { label: e.policy.policy_no });
  }
  if (e.type === "document.uploaded") markSent(e.filename);
  if (e.type === "slot.recorded" || e.type === "document.uploaded") renderSlots(state.events);
  if (!state.replaying) {
    showEvent(e, state.events);
    if (state.live && (e.type === "message.user" || e.type === "approval.decided")) showThinking();
  }
  if (!$("tab-trace").hidden) renderTrace();
}

function showEvent(e, events) {
  switch (e.type) {
    case "message.user":
      state.note = null;
      addEntry("user", e.text, e.doc_ids.map((id) => docName(id, events)), false, e.ts);
      break;
    case "message.assistant":
      hideThinking();
      state.note = null;
      if (state.draft) {
        state.draft.classList.remove("streaming");
        state.draft.innerHTML = renderMarkdown(e.text);
        state.draft = null;
      } else addEntry("assistant", e.text, [], false, e.ts);
      break;
    case "model.called":
      state.note = null;  // the next tool calls belong to a new step
      break;
    case "tool.called":
      noteCall(e);
      break;
    case "tool.result":
      noteResult(e);
      break;
  }
}

function onToken(text) {
  if (state.replaying) return;
  hideThinking();
  if (!state.draft) state.draft = addEntry("assistant", "", [], true);
  state.draft.textContent += text;
  scrollDown($("chat"));
}

// The first status closes the replayed backlog: what came before it already happened, so a
// submission in it is not celebrated again.
function onStatus(s) {
  if (!state.live) {
    state.live = true;
    state.submitted = null;
    if (!$("tab-context").hidden) renderContext();
  }
  renderStatus(s);
}

function onTurn(turn) {
  hideThinking();
  state.draft = null;
  if (turn.approval) showApproval(turn.approval);
  if (!$("tab-context").hidden) renderContext();
}

// --- chat ------------------------------------------------------------------------------------

// The conversation is one ruled pad (ADR-0021): who and when in the margin, the words on the lines.
const WHO = { user: "You", assistant: "Agent", error: "Error" };

function addEntry(kind, text, files = [], streaming = false, ts = null) {
  const body = el("div", { class: `text${streaming ? " streaming" : ""}` });
  if (kind === "assistant" && !streaming) body.innerHTML = renderMarkdown(text);
  else body.textContent = text;
  if (files.length) body.append(el("span", { class: "files", text: `📎 ${files.join(" · ")}` }));
  $("chat").append(el("div", { class: `entry ${kind}` },
    el("div", { class: "who" }, WHO[kind], el("time", { text: clock(ts) })), body));
  scrollDown($("chat"));
  return body;
}

// While the agent works and before it writes, its line on the pad cycles through desk chatter.
// The step's margin notes land underneath; the placeholder goes when the reply starts.
const PHRASES = [
  "Shuffling paperwork", "Licking stamps", "Squinting at the fine print", "Consulting the rulebook",
  "Rummaging through the filing cabinet", "Untangling red tape", "Sharpening pencils",
  "Dusting off the policy binder", "Cross-referencing clauses", "Counting carbon copies",
  "Warming up the rubber stamp", "Dotting i's, crossing t's", "Pondering premiums",
  "Flipping through annexures", "Straightening the in-tray", "Topping up the ink",
];
const phrase = (not) => { let p; do p = PHRASES[Math.floor(Math.random() * PHRASES.length)]; while (p === not); return `${p}…`; };

function showThinking() {
  if (state.thinking || state.draft) return;
  const text = phrase();
  const p = el("span", { class: "phrase", text });
  const detail = el("small");
  const node = el("div", { class: "entry assistant thinking" },
    el("div", { class: "who" }, WHO.assistant, el("time", { text: clock() })), el("div", { class: "text" }, p, detail));
  $("chat").append(node);
  const timer = setInterval(() => { p.textContent = phrase(p.textContent.slice(0, -1)); }, 2400);
  state.thinking = { node, detail, timer };
  scrollDown($("chat"));
}

function hideThinking() {
  if (!state.thinking) return;
  clearInterval(state.thinking.timer);
  state.thinking.node.remove();
  state.thinking = null;
}

// One margin note per model step: its tool calls folded to a line, unfolding to args and results.
function noteCall(e) {
  if (!state.note) {
    const who = el("div", { class: "who" });
    const label = el("span");
    const calls = el("div", { class: "calls" });
    const node = el("div", { class: "entry note" }, who,
      el("div", { class: "text" }, el("details", {}, el("summary", {}, label), calls)));
    $("chat").append(node);
    state.note = { node, who, label, calls, names: [] };
  }
  const n = state.note;
  n.names.push(e.tool);
  n.who.textContent = `→ ${n.names.length} call${n.names.length > 1 ? "s" : ""}`;
  n.label.textContent = tally(n.names);
  if (MARKS.has(e.tool)) n.node.classList.add("flag");
  const line = el("div", { class: "call" }, refLink("tool", e.tool), `(${short(e.args, 70)})`);
  n.calls.append(line);
  state.calls.set(e.call_id, { line, node: n.node });
  scrollDown($("chat"));
}

function noteResult(e) {
  const c = state.calls.get(e.call_id);
  if (!c) return;
  c.line.append(`\n  → ${short(e.content, 120)}`);
  if (isRefused(e.content)) {
    c.line.classList.add("refused");
    c.node.classList.add("flag");
  }
}

function setBusy(busy) {
  state.busy = busy;
  $("send").disabled = busy;
  for (const b of $("approval").querySelectorAll("button")) b.disabled = busy;
}

async function send(event) {
  event.preventDefault();
  const text = $("text").value.trim() || (state.attachments.length ? "Documents attached." : "");
  if (!text || state.busy) return;
  setBusy(true);
  try {
    const files = state.attachments.map(({ filename, mime, data }) => ({ filename, mime, data }));
    await api(`/api/sessions/${state.sid}/messages`, { text, files });
    $("text").value = "";
    state.attachments = [];
    renderAttachments();
    $("demo").open = false;
  } catch (err) {
    addEntry("error", err.message);
    setBusy(false);
  }
}

// --- attachments and demo picker -------------------------------------------------------------

function toBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

async function attach(filename, blob) {
  const mime = blob.type === "image/jpeg" ? "image/jpeg" : "image/png";
  state.attachments.push({ filename, mime, data: await toBase64(blob) });
  renderAttachments();
}

// --- document dock ---------------------------------------------------------------------------

// A demo case only drafts the opening message. Its documents wait in the dock, so the user
// decides when, and in what order, the agent sees them. Re-sending one is allowed on purpose.
const DOC_TYPE = "application/x-dock-doc";
const fixtureUrl = (name) => `/fixtures/${state.dock.caseId}/${name}`;
let demoCases = [];

// Which demo case's documents are in the tray. Sent marks come from the case's own uploads.
function setDock(caseId) {
  const c = demoCases.find((d) => d.id === caseId);
  state.dock = c ? { caseId, docs: c.docs.map((name) => ({ name, sent: false })) } : null;
  for (const e of state.events) if (e.type === "document.uploaded") markSent(e.filename, false);
  renderDock();
}

function markSent(filename, render = true) {
  const doc = state.dock?.docs.find((d) => d.name === filename);
  if (!doc || doc.sent) return;
  doc.sent = true;
  if (render) renderDock();
}

async function attachFromDock(name) {
  const blob = await fetch(fixtureUrl(name)).then((r) => r.blob());
  await attach(name, blob);
  $("text").focus();
}

function renderDock() {
  $("dock").hidden = !state.dock;
  if (!state.dock) return;
  $("dock-docs").replaceChildren(...state.dock.docs.map((d) => {
    const item = el("li", {
      class: `doc${d.sent ? " sent" : ""}`, draggable: "true", tabindex: "0", role: "button",
      title: d.sent ? "Already sent to the agent. You can send it again." : "Drag onto the pad, or click to add",
    },
      el("img", { src: fixtureUrl(d.name), alt: "", loading: "lazy" }),
      el("span", { class: "doc-name", text: d.name.replace(/\.(png|jpe?g)$/i, "") }));
    item.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData(DOC_TYPE, d.name);
      e.dataTransfer.effectAllowed = "copy";
    });
    item.onclick = () => attachFromDock(d.name);
    item.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); attachFromDock(d.name); } };
    return item;
  }));
}

function wireDrop(zone) {
  const accepts = (e) => e.dataTransfer.types.includes(DOC_TYPE) || e.dataTransfer.types.includes("Files");
  zone.addEventListener("dragover", (e) => {
    if (!accepts(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    zone.classList.add("drop-target");
  });
  zone.addEventListener("dragleave", (e) => { if (!zone.contains(e.relatedTarget)) zone.classList.remove("drop-target"); });
  zone.addEventListener("drop", async (e) => {
    if (!accepts(e)) return;
    e.preventDefault();
    zone.classList.remove("drop-target");
    const name = e.dataTransfer.getData(DOC_TYPE);
    if (name && state.dock) return attachFromDock(name);
    for (const file of e.dataTransfer.files) if (/^image\/(png|jpeg)$/.test(file.type)) await attach(file.name, file);
  });
}

function renderAttachments() {
  $("attachments").replaceChildren(...state.attachments.map((a, i) => {
    const remove = el("button", { type: "button", title: "Remove", text: "×" });
    remove.onclick = () => { state.attachments.splice(i, 1); renderAttachments(); };
    return el("span", { class: "chip" }, a.filename, remove);
  }));
}

async function loadDemo() {
  const demo = await fetch("/api/demo").then((r) => r.json());
  demoCases = demo.cases;
  $("demo-cases").replaceChildren(...demo.cases.map((c) => {
    const use = el("button", { type: "button", class: "ghost", text: `Use (${c.docs.length} docs)` });
    use.onclick = () => {
      state.attachments = [];
      renderAttachments();
      setDock(c.id);
      if (state.sid) rememberCase(state.sid, { dock: c.id });
      $("text").value = c.starter;
      $("text").focus();
    };
    return el("div", { class: "demo-case" }, el("strong", { text: c.title }), el("p", { text: c.starter }), use);
  }));
  const head = el("tr", {}, ...["Policy", "Insurer", "Reg no", "Holder", "Vehicle"].map((h) => el("th", { text: h })));
  $("demo-policies").replaceChildren(el("thead", {}, head), el("tbody", {}, ...demo.policies.map((p) => {
    const row = el("tr", { title: "Use in a message" }, ...[p.policy_no, p.insurer, p.reg_no, p.holder, p.vehicle].map((v) => el("td", { text: v })));
    row.onclick = () => { $("text").value = `I need a change on my policy ${p.policy_no}.`; $("text").focus(); };
    return row;
  })));
}

// --- status bar ------------------------------------------------------------------------------

function renderStatus(s) {
  state.status = s;
  renderAssignee(s.assignee);
  const current = STAGES.indexOf(s.stage);
  const stages = STAGES.map((name, i) =>
    el("li", { class: i < current ? "done" : i === current ? "current" : "", text: name }));
  if (s.stage === "Handover") stages.push(el("li", { class: "handover", text: "Handover" }));
  $("stages").replaceChildren(...stages);

  const busy = !["idle", "waiting for approval"].includes(s.current_activity);
  $("activity").textContent = s.current_activity;
  $("activity").className = `activity${busy ? " busy" : ""}`;
  setBusy(busy);
  if (busy && state.live && !state.replaying) showThinking();  // e.g. a reload mid-turn
  else if (!busy) hideThinking();
  if (state.thinking) state.thinking.detail.textContent = busy ? s.current_activity : "";
  if (state.submitted && !busy) {
    window.celebrateSubmission?.({ insurer: s.assignee.name || state.insurer, ref: state.submitted });
    state.submitted = null;
  }

  const t = s.trace_view;
  const fields = [
    ["Today", s.today],
    ["Skills", s.active_skills.join(", ") || "–"],
    ["Slots", `${s.slots.filled}/${s.slots.total}` + (s.slots.low_conf.length ? ` · low confidence: ${s.slots.low_conf.join(", ")}` : "")],
    ["Asks", `${s.ask_budget.used} of ${s.ask_budget.max} used`],
    ["Validation", s.validation.verdict + (s.validation.changed_since_last ? " (changed)" : "")],
    ["Approval", s.approval],
    ["Insurer", s.insurer.stage.replace("_", " ") + (s.insurer.ref ? ` · ${s.insurer.ref}` : "")],
  ];
  $("status-fields").replaceChildren(...fields.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));

  $("docs").replaceChildren(...(s.docs_checklist.length ? s.docs_checklist.map((d) =>
    el("li", {}, el("span", {}, d.name, d.reason ? el("span", { class: "reason-line", text: d.reason }) : null),
      el("span", { class: `state ${d.state}`, text: d.state })))
    : [el("li", { class: "muted", text: "Known once the change type is clear." })]));

  const c = s.context;
  $("pips").replaceChildren(...Array.from({ length: c.threshold }, (_, i) =>
    el("i", { class: i < c.uncompressed_tool_results ? "full" : "" })));
  $("meter-text").textContent = `${c.uncompressed_tool_results}/${c.threshold} uncompressed tool results` +
    (c.last_compressed_at ? ` · last squeezed ${new Date(c.last_compressed_at).toLocaleTimeString()}` : "");
  $("tally").textContent = `${t.model_calls} model calls · ${t.tool_calls} tool calls · ${kTok(t.input_tokens + t.output_tokens)} tok`;
}

// --- recorded values and their sources -------------------------------------------------------

// Each slot's latest value, with where it came from: a document (by file name) or the user.
function latestSlots(events) {
  const slots = new Map();
  for (const e of events) if (e.type === "slot.recorded") slots.set(e.name, e);
  return slots;
}

function sourceChip(source, events) {
  if (source === "user_msg") return el("span", { class: "src you", text: "you" });
  const id = source.startsWith("doc:") ? source.slice(4) : source;
  return el("span", { class: "src", text: docName(id, events).replace(/\.(png|jpe?g)$/i, "") });
}

function renderSlots(events) {
  const slots = [...latestSlots(events).values()];
  $("slots").replaceChildren(...(slots.length
    ? slots.flatMap((s) => [el("dt", { text: s.name }), el("dd", {}, el("span", { text: short(s.value, 60) }), sourceChip(s.source, events))])
    : [el("dt", { class: "muted", text: "Nothing yet." })]));
}

// --- assignee --------------------------------------------------------------------------------

// The user's name lives only in this browser. The backend says whose move it is; we name them.
const NAME_KEY = "user-name";

function userName() {
  try { return localStorage.getItem(NAME_KEY) || ""; } catch { return ""; }
}

function setUserName(name) {
  try { localStorage.setItem(NAME_KEY, name.trim()); } catch { /* storage blocked: default name */ }
  if (state.status) renderAssignee(state.status.assignee);
}

function renderAssignee(a) {
  const you = userName() || "You";
  const label = {
    agent: "AI Agent",
    customer: `${you} (The Customer) 🧢`,
    approver: `${you} (The Approver) 🎩`,
    insurer: a.name || "The insurer",
    team: `${a.name} (Endorsements team)`,
  }[a.role];
  $("assignee").textContent = label;
  $("assignee").className = a.role;
}

window.userName = userName;
window.setUserName = setUserName;

// --- approval --------------------------------------------------------------------------------

function showApproval(card) {
  $("approval-summary").textContent = card.summary;
  state.insurer = card.policy?.insurer || null;
  const fromPolicy = () => el("span", { class: "src sys", text: "policy" });
  const slots = latestSlots(state.events);
  const rows = [];
  if (card.change_type) rows.push(["Change", card.change_type, null]);
  if (card.policy) {
    rows.push(["Policy", `${card.policy.policy_no} · ${card.policy.insurer}`, fromPolicy()]);
    rows.push(["Holder now", card.policy.holder_name, fromPolicy()]);
    if (card.policy.nominee_name) rows.push(["Nominee now", card.policy.nominee_name, fromPolicy()]);
  }
  for (const [k, v] of Object.entries(card.details)) rows.push([k, short(v, 120), null]);
  for (const [k, v] of Object.entries(card.slots)) rows.push([k, v, slots.has(k) ? sourceChip(slots.get(k).source, state.events) : null]);
  for (const [k, v] of Object.entries(card.waivers)) rows.push([`${k} (waived)`, v, null]);
  const head = el("tr", {}, ...["Field", "Value", "Source"].map((h) => el("th", { text: h })));
  $("approval-diff").replaceChildren(el("thead", {}, head), el("tbody", {}, ...rows.map(([k, v, src]) =>
    el("tr", {}, el("td", { text: k }), el("td", { text: v }), el("td", {}, src)))));
  $("approval-reason").value = "";
  $("approval").hidden = false;
  $("approval").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function decide(decision) {
  const reason = $("approval-reason").value.trim() || null;
  if (decision !== "approved" && !reason) {
    $("approval-reason").focus();
    $("approval-reason").placeholder = "Give a reason first";
    return;
  }
  setBusy(true);
  try {
    await api(`/api/sessions/${state.sid}/approval`, { decision, reason });
    await stamp(decision);
    $("approval").hidden = true;
  } catch (err) {
    addEntry("error", err.message);
    setBusy(false);
  }
}

// The decision lands as a rubber stamp on the form before it is filed away.
const STAMPS = { approved: ["Approved", "--ok"], changes_requested: ["Changes", "--warn"], rejected: ["Rejected", "--stamp"] };

async function stamp(decision) {
  const [text, color] = STAMPS[decision];
  const mark = $("big-stamp");
  mark.textContent = text;
  mark.style.color = `var(${color})`;
  mark.classList.remove("on");
  $("approval").classList.remove("thud");
  void mark.offsetWidth;  // restart the animation
  mark.classList.add("on");
  $("approval").classList.add("thud");
  await new Promise((r) => setTimeout(r, 900));
  mark.classList.remove("on");
}

// --- trace and replay ------------------------------------------------------------------------

function renderTrace() {
  const ev = state.events;
  const results = new Map(ev.filter((e) => e.type === "tool.result").map((e) => [e.call_id, e]));
  const start = ev[0]?.ts;
  const rows = [];
  for (const e of ev) {
    const at = start ? secs(ms(start, e.ts)) : "";
    if (e.type === "model.called") {
      const tok = e.input_tokens != null ? `${e.input_tokens} in · ${e.output_tokens} out` : "–";
      rows.push(el("tr", {}, el("td", { class: "mono", text: at }), el("td", { text: "model" }),
        el("td", { text: e.tool_calls ? `${e.tool_calls} tool call(s)` : "reply" }),
        el("td", { class: "mono", text: secs(e.duration_ms) }), el("td", { class: "mono", text: tok })));
    } else if (e.type === "tool.called") {
      const r = results.get(e.call_id);
      const skill = skillOf(e.tool, e.args);
      const flag = MARKS.has(e.tool) || (r && isRefused(r.content));
      const body = el("details", {}, el("summary", { text: short(e.args, 50) }),
        el("pre", { text: `args: ${JSON.stringify(e.args, null, 1)}\n\nresult: ${r ? r.content : "(running)"}` }),
        skill ? el("p", { class: "small" }, "Skill: ", refLink("skill", skill)) : null);
      rows.push(el("tr", { class: flag ? "flag" : "" }, el("td", { class: "mono", text: at }), el("td", { class: "mono" }, refLink("tool", e.tool)),
        el("td", {}, body), el("td", { class: "mono", text: r ? secs(ms(e.ts, r.ts)) : "…" }), el("td", { text: "" })));
    } else if (e.type === "context.compressed") {
      rows.push(el("tr", {}, el("td", { class: "mono", text: at }), el("td", { text: "compression" }),
        el("td", { text: `${e.call_ids.join(", ")}: ${e.tokens_before} → ${e.tokens_after} tokens` }), el("td"), el("td")));
    }
  }
  const head = el("tr", {}, ...["At", "Step", "Detail", "Took", "Tokens"].map((h) => el("th", { text: h })));
  $("trace").replaceChildren(el("thead", {}, head), el("tbody", {}, ...rows));
  const models = ev.filter((e) => e.type === "model.called");
  const tokens = models.reduce((n, e) => n + (e.input_tokens || 0) + (e.output_tokens || 0), 0);
  const tools = ev.filter((e) => e.type === "tool.called").length;
  $("receipt-head").textContent = `${state.sid || ""} · ${start ? new Date(start).toLocaleString() : "nothing yet"}`;
  $("trace-totals").replaceChildren(el("span", { text: `TOTAL · ${models.length} MODEL + ${tools} TOOL CALLS` }),
    el("span", { text: `${tokens.toLocaleString()} TOK` }));
}

// Replay plays the session's own events back into the chat (ADR-0008).
async function replay() {
  if (state.replaying || !state.events.length) return;
  state.replaying = true;
  selectTab("chat");
  hideThinking();
  $("chat").replaceChildren();
  state.calls.clear();
  state.draft = null;
  state.note = null;
  const events = state.events.slice();
  for (let i = 0; i < events.length; i++) {
    showEvent(events[i], events);
    const gap = i + 1 < events.length ? ms(events[i].ts, events[i + 1].ts) : 0;
    await new Promise((r) => setTimeout(r, Math.min(800, Math.max(60, gap / 4))));
  }
  for (const e of state.events.slice(events.length)) showEvent(e, state.events);  // arrived meanwhile
  state.replaying = false;
}

// --- context tab -----------------------------------------------------------------------------

// "Docs:" links under a context item: the tool results it came from, the calls it made, the skill it carries.
function ctxLinks(it) {
  const tools = new Set();
  const skills = new Set();
  if (it.kind === "tool" && it.note) tools.add(it.note.split(",")[0]);
  if (it.kind === "assistant") for (const m of it.text.matchAll(/^→ (\w+)\(/gm)) tools.add(m[1]);
  if (it.kind === "skill") {
    const m = it.text.match(/^\[skill (?:file )?([\w-]+)/);
    if (m) skills.add(m[1]);
    tools.add(it.text.startsWith("[skill file") ? "read_skill_file" : "load_skill");
  }
  if (!tools.size && !skills.size) return null;
  const parts = [...tools].map((t) => refLink("tool", t)).concat([...skills].map((k) => refLink("skill", k, `skill ${k}`)));
  return el("p", { class: "small ctx-docs" }, "Docs: ", ...parts.flatMap((p, i) => (i ? [", ", p] : [p])));
}

// Why an item left the prompt, stamped on its envelope.
const ONFILE = { status: "superseded", tool: "compressed · on file", upload: "stubbed" };

async function renderContext() {
  if (!state.sid) return;
  const items = await fetch(`/api/sessions/${state.sid}/context`).then((r) => r.json());
  $("context").replaceChildren(...items.map((it) => {
    const head = [el("span", { class: "k", text: `${it.kind}${it.note ? ` · ${it.note}` : ""}` }),
      it.in_prompt ? null : el("span", { class: "onfile", text: ONFILE[it.kind] || "left the prompt" })];
    const long = it.text.length > 400 || it.kind === "system";
    const pre = el("pre", { text: it.text });
    const links = ctxLinks(it);
    const body = long ? el("details", {}, el("summary", {}, ...head, el("span", { class: "small muted", text: ` ${it.text.length} chars` })), pre, links)
      : el("div", {}, ...head, pre, links);
    return el("div", { class: `ctx ${it.kind} ${it.in_prompt ? "in" : "out"}` }, body);
  }));
}

// --- tabs and wiring -------------------------------------------------------------------------

function selectTab(name) {
  for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === name));
  for (const t of ["chat", "trace", "context", "reference"]) $(`tab-${t}`).hidden = t !== name;
  document.querySelector(".layout").classList.toggle("full", name === "reference");
  if (name === "trace") renderTrace();
  if (name === "context") renderContext();
  if (name === "reference") renderReference();
}

// --- reference tab ---------------------------------------------------------------------------

let referenceDocs = null;

function argsTable(args) {
  if (!args.length) return el("p", { class: "muted small", text: "No arguments." });
  const head = el("tr", {}, ...["Argument", "Type", "Notes"].map((h) => el("th", { text: h })));
  const rows = args.map((a) => el("tr", {}, el("td", { class: "mono", text: a.name }),
    el("td", { class: "mono", text: a.type }),
    el("td", { text: `${a.required ? "required" : "optional"}${a.description ? `. ${a.description}` : ""}` })));
  return el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, ...rows)));
}

const commaLinks = (kind, names) => names.flatMap((n, i) => (i ? [", ", refLink(kind, n)] : [refLink(kind, n)]));

function toolEntry(t) {
  return el("article", { class: "ref-entry", id: `tool-${t.name}` },
    el("h3", {}, el("code", { text: t.name }), " ", el("a", { class: "anchor", href: refHref("tool", t.name), "data-ref": "", text: "#" })),
    el("p", { class: "ref-summary", text: t.summary }),
    el("dl", {}, el("dt", { text: "Used when" }), el("dd", { text: t.when }),
      el("dt", { text: "Guardrails" }), el("dd", { text: t.guardrails }),
      t.skills.length ? el("dt", { text: "Mentioned by skills" }) : null,
      t.skills.length ? el("dd", {}, ...commaLinks("skill", t.skills)) : null),
    argsTable(t.args),
    el("p", { class: "muted small" }, "Description shown to the model: ", el("em", { text: t.description })));
}

function skillEntry(s) {
  return el("article", { class: "ref-entry", id: `skill-${s.name}` },
    el("h3", {}, el("code", { text: s.name }), " ", el("a", { class: "anchor", href: refHref("skill", s.name), "data-ref": "", text: "#" })),
    el("p", { class: "ref-summary", text: s.description }),
    s.tools_hint.length ? el("p", { class: "small" }, "Tools it leans on: ", ...commaLinks("tool", s.tools_hint)) : null,
    el("details", {}, el("summary", { text: "Full skill text (what the model reads)" }), el("div", { class: "skill-body", html: renderMarkdown(s.body) })),
    ...s.references.map((r) => el("details", {}, el("summary", { text: `references/${r.name}` }), el("pre", { text: r.text }))));
}

async function renderReference() {
  const root = $("reference");
  if (!referenceDocs) {
    try {
      referenceDocs = await fetch("/api/reference").then((r) => r.json());
    } catch (err) {
      root.replaceChildren(el("p", { class: "muted", text: `Could not load the reference: ${err.message}` }));
      return;
    }
    const d = referenceDocs;
    const toc = el("nav", { class: "ref-toc" },
      el("strong", { text: "Tools" }), ...d.tools.map((t) => refLink("tool", t.name)),
      el("strong", { text: "Skills" }), ...d.skills.map((s) => refLink("skill", s.name)));
    const sections = d.groups.map((g) => el("section", {}, el("h2", { text: g.title }),
      el("p", { class: "muted", text: g.blurb }), ...d.tools.filter((t) => t.group === g.id).map(toolEntry)));
    root.replaceChildren(toc, el("div", { class: "ref-body" },
      el("p", { class: "muted" }, "Everything the agent can call. Names in the chat's margin notes, Trace and Context tabs link here."),
      ...sections, el("section", {}, el("h2", { text: "Skills" }),
        el("p", { class: "muted", text: "Playbooks the agent loads on demand with load_skill. Each arrives as a message, not a tool result." }),
        ...d.skills.map(skillEntry))));
  }
  scrollToRef();
}

function scrollToRef() {
  const m = location.hash.match(/^#\/ref\/(tool|skill)\/(.+)$/);
  document.querySelectorAll(".ref-entry.target").forEach((n) => n.classList.remove("target"));
  if (!m) return;
  const node = $(`${m[1]}-${decodeURIComponent(m[2])}`);
  if (!node) return;
  node.classList.add("target");
  node.scrollIntoView({ block: "start" });
}

function routeHash() {
  if (/^#\/ref\b/.test(location.hash)) selectTab("reference");
}

document.addEventListener("click", (ev) => {
  const a = ev.target.closest("a[data-ref]");
  if (!a) return;
  ev.preventDefault();
  history.pushState(null, "", a.getAttribute("href"));
  routeHash();
  if (!$("tab-reference").hidden) scrollToRef();
});
window.addEventListener("popstate", routeHash);

window.selectTab = selectTab;

document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => selectTab(b.dataset.tab)));
$("composer").addEventListener("submit", send);
$("text").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("composer").requestSubmit(); }
});
$("file-input").addEventListener("change", async (e) => {
  for (const file of e.target.files) await attach(file.name, file);
  e.target.value = "";
});
wireDrop($("composer"));
$("approval").querySelectorAll("button").forEach((b) => (b.onclick = () => decide(b.dataset.decision)));
$("new-case").onclick = newCase;
$("cases").onchange = async (e) => {
  const sid = e.target.value;
  if (state.replaying) return renderCases();
  if (!(await openCase(sid))) addEntry("error", gone(sid));
};
$("replay").onclick = replay;

start();
routeHash();
