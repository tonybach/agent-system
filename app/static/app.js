"use strict";

/* ------------------------------------------------------------------ *
 * Trajectory — renders a Claude Code stream-json run as it happens.  *
 * ------------------------------------------------------------------ */

const $ = (sel, root = document) => root.querySelector(sel);
const h = (tag, cls, html) => {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (html != null) el.innerHTML = html;
  return el;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
};

const ICON = {
  check: '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  cross: '<svg class="icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 4.5l7 7m0-7l-7 7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
  caret: '<svg class="caret" viewBox="0 0 12 12" aria-hidden="true"><path d="M4 2.5L7.5 6 4 9.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

/* ---------------- formatting ---------------- */

function md(text) {
  if (window.marked && window.DOMPurify) {
    return DOMPurify.sanitize(marked.parse(text, { gfm: true, breaks: false }));
  }
  return esc(text).replace(/\n/g, "<br>");
}
const fmtCost = (c) => (c == null ? "–" : c < 0.01 ? `$${c.toFixed(4)}` : `$${c.toFixed(2)}`);
function fmtDur(ms) {
  if (ms == null) return "–";
  const s = ms / 1000;
  if (s < 10) return `${s.toFixed(1)} s`;
  if (s < 60) return `${Math.round(s)} s`;
  return `${Math.floor(s / 60)} m ${String(Math.round(s % 60)).padStart(2, "0")} s`;
}
const shortId = (id) => (id ? id.slice(0, 8) : "");
const plural = (n, w) => `${n.toLocaleString()} ${w}${n === 1 ? "" : "s"}`;

const CATEGORY = {
  Read: "read", Glob: "read", Grep: "read", LS: "read", NotebookRead: "read", WebFetch: "read", WebSearch: "read",
  Edit: "write", MultiEdit: "write", Write: "write", NotebookEdit: "write", TodoWrite: "write",
  Bash: "exec", BashOutput: "exec", KillShell: "exec", KillBash: "exec",
  Task: "agent", Agent: "agent",
};
const category = (name) => CATEGORY[name] || (name?.startsWith("mcp__") ? "other" : "other");
const isAgentTool = (name) => name === "Task" || name === "Agent";

function relPath(p, cwd) {
  if (!p) return "";
  if (cwd && p.startsWith(cwd.replace(/\/$/, "") + "/")) return p.slice(cwd.replace(/\/$/, "").length + 1);
  return p;
}
function pathHtml(p, cwd) {
  const r = relPath(p, cwd);
  const i = r.lastIndexOf("/");
  return i < 0 ? esc(r) : `<span class="dim">${esc(r.slice(0, i + 1))}</span>${esc(r.slice(i + 1))}`;
}
function shortDir(p) {
  const parts = String(p).split("/").filter(Boolean);
  return parts.length > 3 ? `…/${parts.slice(-3).join("/")}` : p;
}
const lineCount = (s) => (s ? String(s).split("\n").length : 0);

/** One-line description of a tool call: [html, plain text]. */
function summarize(name, input, cwd) {
  const i = input || {};
  switch (name) {
    case "Read": {
      const range = i.offset || i.limit ? ` <span class="dim">lines ${i.offset || 1}–${(i.offset || 1) + (i.limit || 0)}</span>` : "";
      return [pathHtml(i.file_path, cwd) + range, relPath(i.file_path, cwd)];
    }
    case "Write":
      return [`${pathHtml(i.file_path, cwd)} <span class="add">+${lineCount(i.content)}</span>`, relPath(i.file_path, cwd)];
    case "Edit":
      return [`${pathHtml(i.file_path, cwd)} <span class="add">+${lineCount(i.new_string)}</span> <span class="del">−${lineCount(i.old_string)}</span>`, relPath(i.file_path, cwd)];
    case "MultiEdit":
      return [`${pathHtml(i.file_path, cwd)} <span class="dim">${plural((i.edits || []).length, "edit")}</span>`, relPath(i.file_path, cwd)];
    case "NotebookEdit":
      return [pathHtml(i.notebook_path, cwd), relPath(i.notebook_path, cwd)];
    case "Bash": {
      const cmd = String(i.command || "").split("\n")[0];
      return [esc(cmd), cmd];
    }
    case "Grep": {
      const where = i.path ? ` <span class="dim">in</span> ${pathHtml(i.path, cwd)}` : "";
      return [`"${esc(i.pattern)}"${where}`, `"${i.pattern}"`];
    }
    case "Glob":
      return [esc(i.pattern) + (i.path ? ` <span class="dim">in</span> ${pathHtml(i.path, cwd)}` : ""), i.pattern];
    case "Task":
    case "Agent": {
      const t = i.subagent_type ? `<span class="agent-type">${esc(i.subagent_type)}</span>` : "";
      return [`${esc(i.description || "subagent")}${t}`, i.description || "subagent"];
    }
    case "WebFetch":
      return [esc(i.url), i.url];
    case "WebSearch":
      return [esc(i.query), i.query];
    case "TodoWrite":
      return [`<span class="dim">${plural((i.todos || []).length, "todo")}</span>`, `${(i.todos || []).length} todos`];
    default: {
      const first = Object.values(i).find((v) => typeof v === "string");
      return [esc(first ? first.split("\n")[0] : ""), first || ""];
    }
  }
}

function resultText(content) {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.map((b) => (b.type === "text" ? b.text : b.type === "image" ? "[image]" : JSON.stringify(b))).join("\n");
  }
  return JSON.stringify(content, null, 2);
}

/* ---------------- state ---------------- */

const state = {
  sessionId: null,
  sessionCwd: null,
  runs: [],
  active: null,
  defaultCwd: "",
  cwd: "",
};

const els = {
  runs: $("#runs"),
  empty: $("#empty"),
  form: $("#composer"),
  prompt: $("#prompt"),
  cwd: $("#cwd"),
  cwdText: $("#cwd-text"),
  mode: $("#mode"),
  model: $("#model"),
  runBtn: $("#run-btn"),
  hint: $("#composer-hint"),
  sessionChip: $("#session-chip"),
  sessionId: $("#session-id"),
  outlineBody: $("#outline-body"),
  outlineCount: $("#outline-count"),
};
const DEFAULT_HINT = "Enter to run, Shift+Enter for a new line.";

/* ---------------- auto-scroll ---------------- */

function nearBottom() {
  return window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 180;
}
function stick(fn) {
  const was = nearBottom();
  fn();
  if (was && state.active) window.scrollTo({ top: document.documentElement.scrollHeight });
}

/* ---------------- runs ---------------- */

function createRun({ prompt, cwd, replay, resumed }) {
  const run = {
    n: state.runs.length + 1,
    prompt, cwd, replay, resumed,
    status: "running",
    t0: performance.now(), t1: null,
    nodes: new Map(),
    calls: [],
    lanes: new Map(),
    sysCount: 0,
    received: 0,
    lastText: null,
  };
  state.runs.push(run);
  els.empty.hidden = true;

  const sec = h("section", "run");
  sec.id = `run-${run.n}`;
  const head = h("div", "run-head");
  const p = h("div", "prompt");
  p.append(h("span", "turn-no", `Turn ${run.n}`), h("span", null, esc(prompt)));
  run.statusEl = h("span", "status running", "Running");
  const meta = h("div", "run-meta");
  if (replay) meta.append(h("span", "chip", "Recorded demo, replayed"));
  const dirChip = h("span", "chip", `Directory <b>${esc(shortDir(cwd))}</b>`);
  dirChip.title = cwd;
  meta.append(dirChip);
  if (resumed) meta.append(h("span", "chip", `Resumed session <b>${esc(shortId(resumed))}</b>`));
  run.metaEl = meta;
  head.append(p, run.statusEl, meta);

  run.lanesEl = h("div", "lanes");
  run.lanesEl.hidden = true;
  run.lanesBody = h("div");
  run.lanesFoot = h("div", "lanes-foot", "<span>0 s</span><span></span>");
  run.lanesEl.append(run.lanesBody, run.lanesFoot);

  run.eventsEl = h("div", "events");
  run.footEl = h("div");
  sec.append(head, run.lanesEl, run.eventsEl, run.footEl);
  run.el = sec;
  els.runs.append(sec);

  outlineAddRun(run);
  run.timer = setInterval(() => tick(run), 500);
  sec.scrollIntoView({ behavior: "smooth", block: "start" });
  return run;
}

function tick(run) {
  if (run.status === "running") {
    run.statusEl.textContent = `Running ${fmtDur(performance.now() - run.t0)}`;
    for (const node of run.calls) if (node.status === "pending") updateCallDuration(node);
  }
  layoutLanes(run);
}

/* Short chime when a run ends: rising notes on success, falling on failure. */
let audioCtx = null;
function unlockAudio() {
  // Browsers only allow audio after a user gesture, so create/resume the context on Run.
  try {
    audioCtx ??= new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
  } catch { /* audio unavailable */ }
}
function playChime(status) {
  if (!audioCtx) return;
  const notes = status === "finished" ? [660, 880] : [440, 330];
  const t0 = audioCtx.currentTime;
  notes.forEach((freq, i) => {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    const start = t0 + i * 0.14;
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.2, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.3);
    osc.connect(gain).connect(audioCtx.destination);
    osc.start(start);
    osc.stop(start + 0.32);
  });
}

function setRunStatus(run, status) {
  if (run.status === "running" && (status === "finished" || status === "failed")) playChime(status);
  run.status = status;
  run.t1 ??= performance.now();
  clearInterval(run.timer);
  run.statusEl.className = `status ${status}`;
  run.statusEl.textContent = status === "finished" ? "Finished" : status === "failed" ? "Failed" : status;
  run.oDot.className = `o-dot ${status}`;
  for (const node of run.calls) {
    if (node.status === "pending") setCallStatus(node, "interrupted");
  }
  layoutLanes(run);
}

function showRunError(run, title, detail) {
  const box = h("div", "run-error");
  box.append(h("strong", null, esc(title)));
  if (detail) box.append(h("pre", null, esc(detail)));
  stick(() => run.footEl.before(box));
}

/* ---------------- event reducer ---------------- */

function handleEvent(run, ev) {
  const pid = ev.parent_tool_use_id || null;
  switch (ev.type) {
    case "system":
      if (ev.subtype === "init") {
        if (!run.replay && ev.session_id) setSession(ev.session_id, run.cwd);
        if (ev.model) run.metaEl.append(h("span", "chip", `Model <b>${esc(ev.model)}</b>`));
      } else run.sysCount++;
      return;
    case "assistant":
      for (const block of ev.message?.content || []) {
        if (block.type === "text" && block.text?.trim()) addText(run, block.text, pid, ev.message.id);
        else if (block.type === "tool_use") addCall(run, block, pid);
      }
      return;
    case "user": {
      const content = ev.message?.content;
      if (!Array.isArray(content)) return;
      for (const block of content) if (block.type === "tool_result") attachResult(run, block);
      return;
    }
    case "result":
      finishRun(run, ev);
      return;
    case "app_error":
      showRunError(run, ev.message || "The run failed.", ev.detail);
      setRunStatus(run, "failed");
      return;
    case "app_done":
      endStream(run);
      if (run.status === "running") {
        showRunError(run, "The stream ended before Claude Code reported a result.");
        setRunStatus(run, "failed");
      }
      return;
    default:
      run.sysCount++;
  }
}

function containerFor(run, pid) {
  const parent = pid && run.nodes.get(pid);
  return parent?.subEvents ? parent : null;
}

function addText(run, text, pid, msgId) {
  const parent = containerFor(run, pid);
  const target = parent ? parent.subEvents : run.eventsEl;
  stick(() => {
    // Merge consecutive text blocks of the same message.
    const last = target.lastElementChild;
    if (last && last.classList.contains("text-ev") && last.dataset.msg === msgId) {
      last._raw += "\n\n" + text;
      last.innerHTML = md(last._raw);
    } else {
      const div = h("div", "text-ev md", md(text));
      div._raw = text;
      div.dataset.msg = msgId || "";
      target.append(div);
    }
  });
  if (parent) bumpSub(parent);
}

function addCall(run, block, pid) {
  if (run.nodes.has(block.id)) return;
  const parent = containerFor(run, pid);
  const cat = category(block.name);
  const [sumHtml, sumText] = summarize(block.name, block.input, run.cwd);
  const node = {
    id: block.id, name: block.name, input: block.input || {}, cat, run, parent,
    status: "pending", t0: performance.now(), t1: null, sumText,
  };
  run.nodes.set(node.id, node);
  run.calls.push(node);

  const el = h("div", `call cat-${cat} st-pending`);
  el.id = `call-${node.id}`;
  el._node = node;
  const head = h("button", "call-head");
  head.type = "button";
  head.title = "Show the full input";
  head.append(h("span", "tool-name", esc(block.name)), h("span", "summary", sumHtml));
  node.statusEl = h("span", "call-status", '<span class="spinner"></span><span class="label">Running</span>');
  head.append(node.statusEl);
  const detail = h("div", "call-detail");
  node.inputEl = renderInput(node);
  node.inputEl.hidden = !isEditLike(node.name);
  detail.append(node.inputEl);
  head.addEventListener("click", () => { node.inputEl.hidden = !node.inputEl.hidden; });
  el.append(head, detail);
  node.el = el;
  node.detailEl = detail;

  if (isAgentTool(block.name)) {
    const sub = h("div", "sub open");
    const toggle = h("button", "sub-toggle");
    toggle.type = "button";
    node.subLabel = h("span", null, "Subagent is starting");
    toggle.append(h("span", null, ICON.caret), node.subLabel);
    toggle.addEventListener("click", () => {
      node.userToggled = true;
      sub.classList.toggle("open");
    });
    node.subEvents = h("div", "events");
    node.subEl = sub;
    node.subCount = 0;
    node.subCalls = 0;
    sub.append(toggle, node.subEvents);
    detail.before(sub);
  }

  stick(() => (parent ? parent.subEvents : run.eventsEl).append(el));
  if (parent) { parent.subCalls++; bumpSub(parent); }
  spy.observe(el);
  outlineAddCall(node);
  laneAddCall(node);
  updateOutlineCount();
}

const isEditLike = (name) => name === "Edit" || name === "MultiEdit";

function renderInput(node) {
  const wrap = h("div", "input-view");
  const i = node.input;
  if (node.name === "Edit" || node.name === "MultiEdit") {
    const edits = node.name === "Edit" ? [i] : i.edits || [];
    for (const e of edits) {
      const lines = [
        ...String(e.old_string ?? "").split("\n").map((l) => `<span class="d-del">- ${esc(l)}</span>`),
        ...String(e.new_string ?? "").split("\n").map((l) => `<span class="d-add">+ ${esc(l)}</span>`),
      ];
      const pre = h("pre", "diff");
      foldInto(wrap, pre, lines, { join: "", head: 14 });
    }
    return wrap;
  }
  if (node.name === "Bash" && i.command) {
    const pre = h("pre", "input-json");
    pre.innerHTML = `<span class="cmd">${esc(i.command)}</span>` + (i.description ? `\n<span class="dim"># ${esc(i.description)}</span>` : "");
    wrap.append(pre);
    return wrap;
  }
  if (isAgentTool(node.name) && i.prompt) {
    wrap.append(h("div", "brief", esc(i.prompt)));
    return wrap;
  }
  wrap.append(h("pre", "input-json", esc(JSON.stringify(i, null, 2))));
  return wrap;
}

/**
 * Fold policy: show up to 14 lines whole. Longer output shows the first 8 lines
 * (errors show the last 12, where the traceback lives) with controls to expand.
 */
function foldInto(wrap, pre, lines, { join = "\n", head = 8, tail = 12, startTail = false } = {}) {
  const total = lines.length;
  const foldBar = h("div", "fold");
  let mode = total <= head + 6 ? "all" : startTail ? "tail" : "head";
  const clip = (arr) => arr.map((l) => (l.length > 400 ? l.slice(0, 400) + " …" : l));
  const paint = () => {
    let shown;
    if (mode === "all") shown = lines;
    else if (mode === "head") shown = clip(lines.slice(0, head));
    else shown = clip(lines.slice(-tail));
    pre.innerHTML = shown.join(join);
    pre.classList.toggle("full", mode === "all" && total > 40);
    foldBar.innerHTML = "";
    if (total <= head + 6) return;
    const hidden = total - shown.length;
    const msg = mode === "all" ? `Showing all ${total.toLocaleString()} lines.`
      : mode === "head" ? `${plural(hidden, "more line")} below.`
      : `${plural(hidden, "earlier line")} hidden.`;
    foldBar.append(h("span", null, msg));
    const btn = (label, m) => {
      const b = h("button", null, label);
      b.type = "button";
      b.addEventListener("click", () => { mode = m; paint(); });
      foldBar.append(b);
    };
    if (mode !== "all") btn(`Show all ${total.toLocaleString()} lines`, "all");
    if (mode !== "tail") btn(`Show last ${tail}`, "tail");
    if (mode !== "head") btn(`Show first ${head}`, "head");
  };
  paint();
  wrap.append(pre, foldBar);
}

function attachResult(run, block) {
  const node = run.nodes.get(block.tool_use_id);
  if (!node) return;
  const isError = !!block.is_error;
  node.t1 = performance.now();
  setCallStatus(node, isError ? "error" : "ok");

  const text = resultText(block.content).replace(/\s+$/, "");
  const box = h("div", `result${isError ? " is-error" : ""}`);
  const lines = text ? text.split("\n") : [];
  const label = h("div", "result-label");
  label.textContent = isError ? "Error" : isAgentTool(node.name) ? "Subagent report" : "Result";
  if (lines.length > 1 && !isAgentTool(node.name)) label.append(h("span", null, `${lines.length.toLocaleString()} lines`));
  box.append(label);

  if (!text) {
    box.append(h("div", "fold", "No output."));
  } else if (isAgentTool(node.name) && !isError) {
    const report = h("div", "md", md(text));
    box.append(report);
    if (text.length > 900) {
      report.classList.add("clamped");
      const bar = h("div", "fold");
      const b = h("button", null, "Show the full report");
      b.type = "button";
      b.addEventListener("click", () => {
        const clamped = report.classList.toggle("clamped");
        b.textContent = clamped ? "Show the full report" : "Collapse the report";
      });
      bar.append(b);
      box.append(bar);
    }
  } else {
    foldInto(box, h("pre"), lines.map(esc), { startTail: isError });
  }
  stick(() => node.detailEl.append(box));

  if (node.subEl) {
    bumpSub(node);
    if (!node.userToggled && node.subCount > 6) node.subEl.classList.remove("open");
  }
  if (node.parent) bumpSub(node.parent);
}

function setCallStatus(node, status) {
  node.status = status;
  node.el.classList.remove("st-pending", "st-ok", "st-error", "st-interrupted");
  node.el.classList.add(`st-${status}`);
  if (status === "ok") node.statusEl.innerHTML = `<span class="dur"></span>${ICON.check}`;
  else if (status === "error") node.statusEl.innerHTML = `<span class="dur"></span>${ICON.cross}<span class="label">Error</span>`;
  else if (status === "interrupted") node.statusEl.innerHTML = '<span class="label">No result</span>';
  updateCallDuration(node);
  node.pill?.classList.remove("st-pending", "st-ok", "st-error", "st-interrupted");
  node.pill?.classList.add(`st-${status}`);
  if (node.subEl) bumpSub(node);
}

function updateCallDuration(node) {
  const d = $(".dur", node.statusEl);
  if (d) d.textContent = fmtDur((node.t1 ?? performance.now()) - node.t0);
  else if (node.status === "pending") {
    const label = $(".label", node.statusEl);
    if (label) label.textContent = `Running ${fmtDur(performance.now() - node.t0)}`;
  }
}

function bumpSub(node) {
  node.subCount = node.subEvents.children.length;
  const parts = [plural(node.subCount, "event")];
  if (node.subCalls) parts.push(plural(node.subCalls, "tool call"));
  const st = node.status === "pending" ? "Subagent working" : node.status === "error" ? "Subagent failed" : node.status === "interrupted" ? "Subagent stopped" : "Subagent done";
  node.subLabel.textContent = `${st}, ${parts.join(", ")}`;
}

function finishRun(run, ev) {
  if (!run.replay && ev.session_id) setSession(ev.session_id, run.cwd);
  const failed = ev.is_error || (ev.subtype && ev.subtype !== "success");
  if (failed) {
    const reasons = {
      error_max_turns: "The agent stopped after reaching the turn limit.",
      error_during_execution: "The agent hit an error during execution.",
    };
    const detail = [ev.result, ...(ev.errors || [])].filter(Boolean).join("\n");
    showRunError(run, reasons[ev.subtype] || "The agent reported an error.", detail);
  }
  const stats = h("div", "stats");
  const tile = (v, k, cls = "") => h("div", `stat ${cls}`, `<span class="v">${v}</span><span class="k">${k}</span>`);
  stats.append(
    tile(fmtCost(ev.total_cost_usd), "Cost"),
    tile(fmtDur(ev.duration_ms), "Duration"),
    tile(ev.num_turns ?? "–", ev.num_turns === 1 ? "Turn" : "Turns"),
    tile(run.calls.length, run.calls.length === 1 ? "Tool call" : "Tool calls", "tools"),
  );
  if (run.sysCount) stats.append(h("span", "sys-note", `${plural(run.sysCount, "system event")} not shown`));
  stick(() => run.footEl.append(stats));
  setRunStatus(run, failed ? "failed" : "finished");
}

/* ---------------- swimlane timeline ---------------- */

function laneFor(run, node) {
  const key = node.parent ? node.parent.id : "main";
  let lane = run.lanes.get(key);
  if (!lane) {
    const row = h("div", "lane");
    const name = node.parent ? node.parent.sumText : "Main agent";
    row.append(h("span", "lane-name", esc(name)), h("div", "lane-track"));
    row.firstChild.title = name;
    lane = { row, track: row.lastChild, segs: [] };
    run.lanes.set(key, lane);
    // Subagent lanes sit right below the lane of the agent that spawned them.
    const anchor = node.parent && run.lanes.get(node.parent.parent ? node.parent.parent.id : "main");
    if (anchor) {
      let after = anchor.row;
      while (after.nextElementSibling && after.nextElementSibling._depth > anchor.row._depth) after = after.nextElementSibling;
      after.after(row);
    } else run.lanesBody.append(row);
    row._depth = node.parent ? (anchor?.row._depth ?? 0) + 1 : 0;
  }
  return lane;
}

function laneAddCall(node) {
  const run = node.run;
  run.lanesEl.hidden = false;
  const lane = laneFor(run, node);
  const seg = h("button", `seg cat-${node.cat}`);
  seg.type = "button";
  seg.title = `${node.name} ${node.sumText}`.trim();
  seg.addEventListener("click", () => jumpTo(node));
  lane.track.append(seg);
  node.seg = seg;
  lane.segs.push(node);
  layoutLanes(run);
}

function layoutLanes(run) {
  if (!run.calls.length) return;
  const end = run.t1 ?? performance.now();
  const span = Math.max(end - run.t0, 1);
  for (const node of run.calls) {
    if (!node.seg) continue;
    const a = node.t0 - run.t0;
    const b = (node.t1 ?? (node.status === "pending" ? end : node.t0)) - run.t0;
    node.seg.style.left = `${(a / span) * 100}%`;
    node.seg.style.width = `${Math.max(((b - a) / span) * 100, 0.6)}%`;
    node.seg.classList.toggle("pending", node.status === "pending");
    node.seg.classList.toggle("error", node.status === "error");
  }
  run.lanesFoot.lastChild.textContent = fmtDur(span);
}

/* ---------------- outline ---------------- */

function outlineAddRun(run) {
  $(".outline-empty", els.outlineBody)?.remove();
  const turn = h("div", "o-turn");
  const head = h("button", "o-turn-head");
  head.type = "button";
  run.oDot = h("span", "o-dot running");
  head.append(run.oDot, h("span", "t", `Turn ${run.n}: ${esc(run.prompt)}`));
  head.title = run.prompt;
  head.addEventListener("click", () => { run.el.scrollIntoView({ behavior: "smooth", block: "start" }); closeDrawer(); });
  run.oList = h("ul", "o-list");
  turn.append(head, run.oList);
  els.outlineBody.append(turn);
}

function makePill(node) {
  const pill = h("button", `o-pill cat-${node.cat} st-pending`);
  pill.type = "button";
  pill.title = `${node.name} ${node.sumText}`.trim();
  pill.append(h("span", "bar"), h("span", "n", esc(node.name)), h("span", "s", esc(node.sumText)), h("span", "sd"));
  pill.addEventListener("click", () => jumpTo(node));
  node.pill = pill;
  return pill;
}

function outlineAddCall(node) {
  const list = node.parent ? node.parent.oChildren : node.run.oList;
  const pill = makePill(node);
  if (isAgentTool(node.name)) {
    // Subagents launched while a sibling subagent is still running share a row of lanes.
    const last = list.lastElementChild;
    const lanes = last?._lanes;
    const parallel = lanes && lanes._tasks.some((t) => t.status === "pending");
    const lane = h("div", "o-lane");
    node.oChildren = h("ul", "o-list");
    lane.append(pill, node.oChildren);
    if (parallel) {
      lanes.append(lane);
      lanes._tasks.push(node);
    } else {
      const li = h("li", "o-item");
      const row = h("div", "o-lanes");
      row._tasks = [node];
      row.append(lane);
      li.append(row);
      li._lanes = row;
      list.append(li);
    }
  } else {
    const li = h("li", "o-item");
    li.append(pill);
    list.append(li);
  }
}

function updateOutlineCount() {
  const n = state.runs.reduce((a, r) => a + r.calls.length, 0);
  els.outlineCount.textContent = n ? plural(n, "call") : "";
}

function jumpTo(node) {
  for (let p = node.parent; p; p = p.parent) {
    if (p.subEl && !p.subEl.classList.contains("open")) { p.subEl.classList.add("open"); p.userToggled = true; }
  }
  node.el.scrollIntoView({ behavior: "smooth", block: "center" });
  node.el.classList.add("flash");
  setTimeout(() => node.el.classList.remove("flash"), 1200);
  setActivePill(node);
  closeDrawer();
}

let activePill = null;
function setActivePill(node) {
  if (activePill === node.pill) return;
  activePill?.classList.remove("active");
  activePill = node.pill;
  if (!activePill) return;
  activePill.classList.add("active");
  const body = els.outlineBody;
  const pr = activePill.getBoundingClientRect();
  const br = body.getBoundingClientRect();
  if (pr.top < br.top || pr.bottom > br.bottom) body.scrollTop += pr.top - br.top - br.height / 2;
}

const spy = new IntersectionObserver((entries) => {
  const visible = entries.filter((e) => e.isIntersecting);
  if (visible.length) setActivePill(visible[visible.length - 1].target._node);
}, { rootMargin: "-40% 0px -55% 0px" });

/* ---------------- session ---------------- */

function setSession(id, cwd) {
  state.sessionId = id;
  state.sessionCwd = cwd;
  els.sessionChip.hidden = false;
  els.sessionId.textContent = shortId(id);
  els.sessionId.title = `${id} (click to copy)`;
  updateHint();
}

els.sessionId.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(state.sessionId);
    els.sessionId.textContent = "Copied";
    setTimeout(() => (els.sessionId.textContent = shortId(state.sessionId)), 1000);
  } catch { /* clipboard unavailable */ }
});

$("#new-session").addEventListener("click", () => {
  // Stop a run in progress; its stream is closed below so no late events arrive.
  if (state.active) fetch(`/api/runs/${state.active.serverId}/cancel`, { method: "POST" }).catch(() => {});
  for (const run of state.runs) {
    clearInterval(run.timer);
    run.es?.close();
    for (const node of run.calls) spy.unobserve(node.el);
  }
  state.runs = [];
  state.active = null;
  state.sessionId = null;
  state.sessionCwd = null;
  activePill = null;
  els.sessionChip.hidden = true;
  els.runs.replaceChildren();
  els.outlineBody.replaceChildren(h("p", "outline-empty", "Tool calls appear here as the agent runs."));
  els.outlineCount.textContent = "";
  els.empty.hidden = false;
  els.prompt.value = "";
  autoGrow();
  closeDrawer();
  updateComposer();
  window.scrollTo({ top: 0 });
  els.prompt.focus();
});

/* ---------------- streaming ---------------- */

function connect(run, runId) {
  let seen = 0;
  const es = new EventSource(`/api/runs/${runId}/events`);
  run.es = es;
  es.onopen = () => { seen = 0; }; // the server replays from the start on reconnect
  es.onmessage = (msg) => {
    seen++;
    if (seen <= run.received) return;
    run.received++;
    let ev;
    try { ev = JSON.parse(msg.data); } catch { return; }
    handleEvent(run, ev);
  };
  es.onerror = () => {
    if (run.status !== "running" || es.readyState === EventSource.CLOSED) {
      if (run.status === "running") {
        showRunError(run, "Lost the connection to the Trajectory server.");
        setRunStatus(run, "failed");
        endStream(run);
      }
    }
  };
}

function endStream(run) {
  run.es?.close();
  if (state.active === run) state.active = null;
  updateComposer();
}

async function start({ replay = false } = {}) {
  if (state.active) return;
  const prompt = replay ? "Use subagents to survey the repo, then update the README" : els.prompt.value.trim();
  if (!prompt) { els.prompt.focus(); return; }
  unlockAudio();
  const cwd = replay ? "/Users/me/scratch/demo-repo" : state.cwd || state.defaultCwd;
  const resume = !replay && state.sessionId && cwd === state.sessionCwd ? state.sessionId : null;

  let res, data;
  try {
    res = await fetch(replay ? "/api/replay" : "/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(replay ? {} : { prompt, cwd, session_id: resume, permission_mode: els.mode.value, model: els.model.value }),
    });
    data = await res.json();
  } catch (e) {
    return setHint(`Cannot reach the Trajectory server: ${e.message}`, true);
  }
  if (!res.ok) return setHint(data.error || `Request failed (${res.status}).`, true);

  if (!replay) {
    els.prompt.value = "";
    autoGrow();
    store.set("traj.cwd", cwd);
    store.set("traj.model", els.model.value);
  }
  const run = createRun({ prompt, cwd: data.cwd || cwd, replay, resumed: resume });
  state.active = run;
  run.serverId = data.run_id;
  updateComposer();
  connect(run, data.run_id);
}

async function stop() {
  const run = state.active;
  if (!run) return;
  els.runBtn.disabled = true;
  try { await fetch(`/api/runs/${run.serverId}/cancel`, { method: "POST" }); } catch { /* ignore */ }
}

/* ---------------- composer ---------------- */

function setHint(text, warn = false) {
  els.hint.textContent = text;
  els.hint.classList.toggle("warn", warn);
}
function updateHint() {
  const cwd = state.cwd || state.defaultCwd;
  if (state.sessionId && cwd !== state.sessionCwd) {
    setHint("This directory differs from the session's directory. The next prompt starts a new session.", true);
  } else if (state.sessionId) {
    setHint("Your next prompt continues this session. " + DEFAULT_HINT);
  } else setHint(DEFAULT_HINT);
}
function updateComposer() {
  const running = !!state.active;
  els.runBtn.disabled = false;
  els.runBtn.textContent = running ? "Stop" : "Run";
  els.runBtn.classList.toggle("stop", running);
  els.prompt.placeholder = running ? "Wait for the run to finish…" : state.sessionId ? "Ask a follow-up…" : "Ask Claude Code to do something…";
  if (!running) updateHint();
}
function autoGrow() {
  els.prompt.style.height = "auto";
  els.prompt.style.height = Math.min(els.prompt.scrollHeight, 200) + "px";
}

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  state.active ? stop() : start();
});
els.prompt.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    if (!state.active) start();
  }
});
els.prompt.addEventListener("input", autoGrow);
function setCwd(path) {
  state.cwd = path;
  // U+200E keeps a leading "/" on the left inside the right-to-left ellipsis box.
  els.cwdText.textContent = "\u200e" + path + "\u200e";
  els.cwd.title = `${path}\nClick to choose another folder`;
  store.set("traj.cwd", path);
  updateHint();
}

els.cwd.addEventListener("click", async () => {
  if (els.cwd.disabled) return;
  els.cwd.disabled = true;
  try {
    const res = await fetch("/api/pick-dir", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start: state.cwd || state.defaultCwd }),
    });
    const data = await res.json();
    if (data.path) setCwd(data.path);
    else if (res.status === 501) {
      // No native picker on this platform: ask for a path instead.
      const typed = window.prompt("Working directory", state.cwd);
      if (typed?.trim()) setCwd(typed.trim());
    } else if (data.error) setHint(data.error, true);
  } catch (e) {
    setHint(`Cannot open the folder picker: ${e.message}`, true);
  } finally {
    els.cwd.disabled = false;
  }
});
for (const b of document.querySelectorAll(".suggestion[data-prompt]")) {
  b.addEventListener("click", () => { els.prompt.value = b.dataset.prompt; autoGrow(); els.prompt.focus(); });
}
$("#replay-demo").addEventListener("click", () => start({ replay: true }));

/* ---------------- outline drawer (narrow windows) ---------------- */

const scrim = $("#scrim");
const toggleBtn = $("#outline-toggle");
function closeDrawer() {
  document.body.classList.remove("outline-open");
  scrim.hidden = true;
  toggleBtn.setAttribute("aria-expanded", "false");
}
toggleBtn.addEventListener("click", () => {
  const open = !document.body.classList.contains("outline-open");
  document.body.classList.toggle("outline-open", open);
  scrim.hidden = !open;
  toggleBtn.setAttribute("aria-expanded", String(open));
});
scrim.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

/* ---------------- boot ---------------- */

(async function boot() {
  try {
    const d = await (await fetch("/api/defaults")).json();
    state.defaultCwd = d.cwd;
  } catch { /* server offline; leave empty */ }
  setCwd(store.get("traj.cwd") || state.defaultCwd);
  const savedModel = store.get("traj.model");
  if (savedModel != null && [...els.model.options].some((o) => o.value === savedModel)) els.model.value = savedModel;
  updateComposer();
  els.prompt.focus();
})();
