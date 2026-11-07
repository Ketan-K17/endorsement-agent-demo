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
  draft: null,          // the assistant bubble receiving tokens
  feedRows: new Map(),  // call_id -> feed row
  attachments: [],      // {filename, mime, data (base64), dock (doc name if it came from the dock)}
  dock: null,           // {caseId, docs: [{name, sent}]}: the demo case's documents, added at will
  busy: false,
  replaying: false,
  status: null,         // the last status bar, so a name change can re-render the assignee
  submitted: null,      // insurer ref just submitted, celebrated when the turn settles
  insurer: null,        // the insurer named on the last approval card
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

async function api(path, body) {
  const r = await fetch(path, body === undefined ? { method: "POST" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { const j = await r.json(); detail = typeof j.detail === "string" ? j.detail : "invalid request"; } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return r.json();
}

function scrollDown(node) { node.scrollTop = node.scrollHeight; }

// --- session ---------------------------------------------------------------------------------

async function newSession() {
  if (state.source) state.source.close();
  Object.assign(state, { events: [], lastSeq: 0, draft: null, busy: false, attachments: [], submitted: null });
  state.feedRows.clear();
  if (state.dock) for (const d of state.dock.docs) d.sent = false;  // a new case has seen none of them
  renderDock();
  for (const id of ["chat", "feed", "trace", "context"]) $(id).replaceChildren();
  $("approval").hidden = true;
  renderAttachments();
  const { session_id } = await api("/api/sessions");
  state.sid = session_id;
  $("session-id").textContent = session_id;
  const source = new EventSource(`/api/sessions/${session_id}/stream`);
  source.addEventListener("event", (m) => onCaseEvent(JSON.parse(m.data)));
  source.addEventListener("token", (m) => onToken(JSON.parse(m.data).text));
  source.addEventListener("status", (m) => renderStatus(JSON.parse(m.data)));
  source.addEventListener("turn", (m) => onTurn(JSON.parse(m.data)));
  source.addEventListener("agent_error", (m) => {
    addBubble("error", JSON.parse(m.data).message);
    state.draft = null;
  });
  state.source = source;
}

// --- stream handlers -------------------------------------------------------------------------

function onCaseEvent(e) {
  if (e.seq <= state.lastSeq) return;  // a reconnect may resend
  state.lastSeq = e.seq;
  state.events.push(e);
  if (e.type === "insurer.submitted") state.submitted = e.ref;
  if (!state.replaying) showEvent(e, state.events);
  if (!$("tab-trace").hidden) renderTrace();
}

function showEvent(e, events) {
  switch (e.type) {
    case "message.user": {
      const names = e.doc_ids.map((id) => events.find((x) => x.type === "document.uploaded" && x.doc_id === id)?.filename || id);
      addBubble("user", e.text, names);
      break;
    }
    case "message.assistant":
      if (state.draft) {
        state.draft.classList.remove("streaming");
        state.draft.innerHTML = renderMarkdown(e.text);
        state.draft = null;
      } else addBubble("assistant", e.text);
      break;
    case "tool.called": {
      const row = feedRow(e.tool, short(e.args, 40), "running", "running", true);
      state.feedRows.set(e.call_id, { row, ts: e.ts });
      break;
    }
    case "tool.result": {
      const entry = state.feedRows.get(e.call_id);
      if (!entry) break;
      entry.row.className = /^(refused|error)/.test(e.content) ? "refused" : "";
      entry.row.querySelector(".time").textContent = secs(ms(entry.ts, e.ts));
      break;
    }
    case "model.called": {
      const tokens = e.input_tokens != null ? ` · ${e.input_tokens}→${e.output_tokens} tok` : "";
      feedRow("model", e.tool_calls ? `${e.tool_calls} tool call(s)` : "reply", secs(e.duration_ms) + tokens, "model");
      break;
    }
    case "context.compressed":
      feedRow("compressed", `${e.call_ids.length} results, ${(e.tokens_before / 1000).toFixed(1)}k → ${(e.tokens_after / 1000).toFixed(1)}k tokens`, "", "compressed");
      break;
    case "history.image_stubbed":
      feedRow("image stubbed", e.doc_id, "", "compressed");
      break;
  }
}

function onToken(text) {
  if (state.replaying) return;
  if (!state.draft) state.draft = addBubble("assistant", "", [], true);
  state.draft.textContent += text;
  scrollDown($("chat"));
}

function onTurn(turn) {
  state.draft = null;
  if (turn.approval) showApproval(turn.approval);
  if (!$("tab-context").hidden) renderContext();
}

// --- chat ------------------------------------------------------------------------------------

function addBubble(kind, text, files = [], streaming = false) {
  const bubble = el("div", { class: `bubble ${kind}${streaming ? " streaming" : ""}` });
  if (kind === "assistant" && !streaming) bubble.innerHTML = renderMarkdown(text);
  else bubble.textContent = text;
  if (files.length) bubble.append(el("span", { class: "files", text: `📎 ${files.join(", ")}` }));
  $("chat").append(bubble);
  scrollDown($("chat"));
  return bubble;
}

function feedRow(name, detail, time, cls, link = null) {
  const label = link ? refLink("tool", name) : name;
  const row = el("li", { class: cls },
    el("span", { class: "name" }, label, detail ? ` ${detail}` : null),
    el("span", { class: "time", text: time }));
  $("feed").append(row);
  scrollDown($("feed"));
  return row;
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
    for (const a of state.attachments) {
      const doc = state.dock?.docs.find((d) => d.name === a.dock);
      if (doc) doc.sent = true;
    }
    renderDock();
    $("text").value = "";
    state.attachments = [];
    renderAttachments();
    $("demo").open = false;
  } catch (err) {
    addBubble("error", err.message);
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

async function attach(filename, blob, dock = null) {
  const mime = blob.type === "image/jpeg" ? "image/jpeg" : "image/png";
  state.attachments.push({ filename, mime, data: await toBase64(blob), dock });
  renderAttachments();
}

// --- document dock ---------------------------------------------------------------------------

// A demo case only drafts the opening message. Its documents wait in the dock, so the user
// decides when, and in what order, the agent sees them. Re-sending one is allowed on purpose.
const DOC_TYPE = "application/x-dock-doc";
const fixtureUrl = (name) => `/fixtures/${state.dock.caseId}/${name}`;

async function attachFromDock(name) {
  const blob = await fetch(fixtureUrl(name)).then((r) => r.blob());
  await attach(name, blob, name);
  $("text").focus();
}

function renderDock() {
  $("dock").hidden = !state.dock;
  document.querySelector(".layout").classList.toggle("with-dock", Boolean(state.dock));
  if (!state.dock) return;
  $("dock-docs").replaceChildren(...state.dock.docs.map((d) => {
    const item = el("li", {
      class: `dock-doc${d.sent ? " sent" : ""}`, draggable: "true", tabindex: "0", role: "button",
      title: d.sent ? "Already sent to the agent. You can send it again." : "Drag into the message box, or click to add",
    },
      el("img", { src: fixtureUrl(d.name), alt: "", loading: "lazy" }),
      el("span", { class: "dock-name", text: d.name }),
      d.sent ? el("span", { class: "dock-sent", text: "✓ sent" }) : null);
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
  $("demo-cases").replaceChildren(...demo.cases.map((c) => {
    const use = el("button", { type: "button", class: "ghost", text: `Use (${c.docs.length} docs)` });
    use.onclick = () => {
      state.attachments = [];
      renderAttachments();
      state.dock = { caseId: c.id, docs: c.docs.map((name) => ({ name, sent: false })) };
      renderDock();
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
  if (state.submitted && !busy) {
    window.celebrateSubmission?.({ insurer: s.assignee.name || state.insurer, ref: state.submitted });
    state.submitted = null;
  }

  const t = s.trace_view;
  const fields = [
    ["Today", s.today],
    ["Skills", s.active_skills.join(", ") || "–"],
    ["Slots", `${s.slots.filled}/${s.slots.total}` + (s.slots.low_conf.length ? ` · low confidence: ${s.slots.low_conf.join(", ")}` : "")],
    ["Asks", `${s.ask_budget.used}/${s.ask_budget.max}`],
    ["Validation", s.validation.verdict + (s.validation.changed_since_last ? " (changed)" : "")],
    ["Approval", s.approval],
    ["Insurer", s.insurer.stage.replace("_", " ") + (s.insurer.ref ? ` · ${s.insurer.ref}` : "")],
    ["Trace", `${t.model_calls} model calls · ${t.tool_calls} tool calls · ${t.input_tokens + t.output_tokens} tokens`],
  ];
  $("status-fields").replaceChildren(...fields.flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: v })]));

  $("docs").replaceChildren(...(s.docs_checklist.length ? s.docs_checklist.map((d) =>
    el("li", {}, el("span", { class: `state ${d.state}`, text: d.state }),
      el("span", {}, d.name, d.reason ? el("div", { class: "reason", text: d.reason }) : null)))
    : [el("li", { class: "muted", text: "Known once the change type is clear." })]));

  const c = s.context;
  $("meter-fill").style.width = `${Math.min(100, (100 * c.uncompressed_tool_results) / c.threshold)}%`;
  $("meter-text").textContent = `${c.uncompressed_tool_results}/${c.threshold} uncompressed tool results` +
    (c.last_compressed_at ? ` · last compressed ${new Date(c.last_compressed_at).toLocaleTimeString()}` : "");
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
    customer: `${you} (The Customer)`,
    approver: `${you} (The Approver)`,
    insurer: a.name || "The insurer",
  }[a.role];
  $("assignee").textContent = label;
  $("assignee").className = `assignee-badge ${a.role}`;
}

window.userName = userName;
window.setUserName = setUserName;

// --- approval --------------------------------------------------------------------------------

function showApproval(card) {
  $("approval-summary").textContent = card.summary;
  state.insurer = card.policy?.insurer || null;
  const rows = [];
  if (card.change_type) rows.push(["Change", card.change_type]);
  if (card.policy) {
    rows.push(["Policy", `${card.policy.policy_no} · ${card.policy.insurer}`]);
    rows.push(["Holder now", card.policy.holder_name]);
    if (card.policy.nominee_name) rows.push(["Nominee now", card.policy.nominee_name]);
  }
  for (const [k, v] of Object.entries(card.details)) rows.push([k, short(v, 120)]);
  for (const [k, v] of Object.entries(card.slots)) rows.push([k, v]);
  for (const [k, v] of Object.entries(card.waivers)) rows.push([`${k} (waived)`, v]);
  $("approval-diff").replaceChildren(...rows.map(([k, v]) => el("tr", {}, el("th", { text: k }), el("td", { text: v }))));
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
    $("approval").hidden = true;
  } catch (err) {
    addBubble("error", err.message);
    setBusy(false);
  }
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
      const body = el("details", {}, el("summary", { text: short(e.args, 50) }),
        el("pre", { text: `args: ${JSON.stringify(e.args, null, 1)}\n\nresult: ${r ? r.content : "(running)"}` }),
        skill ? el("p", { class: "small" }, "Skill: ", refLink("skill", skill)) : null);
      rows.push(el("tr", {}, el("td", { class: "mono", text: at }), el("td", { class: "mono" }, refLink("tool", e.tool)),
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
  $("trace-totals").textContent = `${models.length} model calls · ${ev.filter((e) => e.type === "tool.called").length} tool calls · ${tokens} tokens`;
}

// Replay plays the session's own events back into the chat and activity feed (ADR-0008).
async function replay() {
  if (state.replaying || !state.events.length) return;
  state.replaying = true;
  selectTab("chat");
  $("chat").replaceChildren();
  $("feed").replaceChildren();
  state.feedRows.clear();
  state.draft = null;
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

async function renderContext() {
  if (!state.sid) return;
  const items = await fetch(`/api/sessions/${state.sid}/context`).then((r) => r.json());
  $("context").replaceChildren(...items.map((it) => {
    const label = `${it.kind}${it.note ? ` · ${it.note}` : ""}${it.in_prompt ? "" : " · left the prompt"}`;
    const long = it.text.length > 400 || it.kind === "system";
    const pre = el("pre", { text: it.text });
    const links = ctxLinks(it);
    const body = long ? el("details", {}, el("summary", { text: `${label} (${it.text.length} chars)` }), pre, links)
      : el("div", {}, el("strong", { class: "small", text: label }), pre, links);
    return el("div", { class: `ctx ${it.in_prompt ? "in" : "out"}` }, body);
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
      el("p", { class: "muted" }, "Everything the agent can call. Names in the Activity feed, Trace and Context tabs link here."),
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
$("new-case").onclick = newSession;
$("replay").onclick = replay;

loadDemo();
newSession();
routeHash();
