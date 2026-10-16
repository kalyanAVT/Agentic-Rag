/*
 * Agentic RAG — trace viewer (Phase 6).
 *
 * A no-build vanilla-JS client for the FastAPI backend:
 *   POST /ask            -> run the pipeline, get the full Trace
 *   GET  /runs           -> list past runs
 *   GET  /runs/{run_id}  -> load one past run's Trace
 *
 * It renders a Trace as an Answer (with clickable [E#]/[M#] citations) followed
 * by the reasoning chain — Plan, Tool Calls, Evidence, Memory Used — so a reader
 * can follow how the agent got to its answer without touching the logs.
 *
 * Settings (bring-your-own-key): the visitor's LLM key / base URL / model and
 * GitHub token live in this browser's localStorage and are sent with each
 * /ask request. The server uses them for that request only and never stores them.
 */

"use strict";

const $ = (id) => document.getElementById(id);

// --- small helpers --------------------------------------------------------

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtMs(ms) {
  const n = Number(ms) || 0;
  return n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${n}ms`;
}

function setStatus(message, kind = "") {
  const el = $("status");
  el.textContent = message || "";
  el.className = "status" + (kind ? ` status-${kind}` : "");
}

function pretty(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// --- citation linking -----------------------------------------------------

// Turn [E1], [E2], [M1] ... markers in the answer into links that jump to the
// matching evidence / memory card. Everything else is escaped as plain text.
function linkifyAnswer(answer, trace) {
  const evidence = trace.evidence || [];
  const memory = trace.memory_used || [];

  // Escape first, then substitute markers on the safe string.
  return escapeHtml(answer).replace(/\[([EM])(\d+)\]/g, (whole, kind, numStr) => {
    const n = parseInt(numStr, 10);
    const list = kind === "E" ? evidence : memory;
    if (n < 1 || n > list.length) return whole; // dangling marker -> leave as text
    const anchor = kind === "E" ? `ev-${n}` : `mem-${n}`;
    return `<a href="#${anchor}" class="cite" data-anchor="${anchor}">[${kind}${n}]</a>`;
  });
}

// Clicking a citation opens the enclosing <details> and highlights the card.
function onCiteClick(event) {
  const link = event.target.closest("a.cite");
  if (!link) return;
  event.preventDefault();
  const target = document.getElementById(link.dataset.anchor);
  if (!target) return;
  let node = target.parentElement;
  while (node) {
    if (node.tagName === "DETAILS") node.open = true;
    node = node.parentElement;
  }
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.remove("flash");
  void target.offsetWidth; // restart the animation
  target.classList.add("flash");
}

// --- section builders -----------------------------------------------------

function section(title, count, open, bodyHtml) {
  const badge = count === null ? "" : ` <span class="badge">${count}</span>`;
  return `
    <details class="section"${open ? " open" : ""}>
      <summary>${escapeHtml(title)}${badge}</summary>
      <div class="section-body">${bodyHtml}</div>
    </details>`;
}

function renderAnswer(trace) {
  const answerHtml = trace.answer
    ? linkifyAnswer(trace.answer, trace)
    : '<em class="muted">No answer produced.</em>';
  const t = trace.timing_ms || {};
  const timings = ["plan_ms", "tools_ms", "synthesis_ms", "total_ms"]
    .filter((k) => k in t)
    .map((k) => `${k.replace("_ms", "")} ${fmtMs(t[k])}`)
    .join(" · ");
  return `
    <div class="answer-card" id="answer">
      <h3>Answer</h3>
      <div class="answer-body">${answerHtml}</div>
      ${timings ? `<div class="timings">${escapeHtml(timings)}</div>` : ""}
    </div>`;
}

function renderPlan(plan) {
  if (!plan.length) return '<em class="muted">No plan steps.</em>';
  const items = plan
    .map((step, i) => {
      const hint = step.tool_hint
        ? ` <span class="chip">${escapeHtml(step.tool_hint)}</span>`
        : "";
      return `<li><span class="step-n">${i + 1}</span>${escapeHtml(step.sub_question)}${hint}</li>`;
    })
    .join("");
  return `<ol class="plan-list">${items}</ol>`;
}

function renderToolCalls(calls) {
  if (!calls.length) return '<em class="muted">No tool calls.</em>';
  return calls
    .map((c) => {
      const ok = c.success ? "ok" : "fail";
      const okLabel = c.success ? "success" : "failed";
      const args = c.args && Object.keys(c.args).length ? pretty(c.args) : "";
      const result = pretty(c.result);
      return `
        <div class="toolcall">
          <div class="toolcall-head">
            <code class="tool-name">${escapeHtml(c.tool_name)}</code>
            <span class="status-dot status-${ok}" title="${okLabel}">${okLabel}</span>
            <span class="muted">${fmtMs(c.latency_ms)}</span>
          </div>
          ${args ? `<div class="kv"><span class="k">args</span><pre>${escapeHtml(args)}</pre></div>` : ""}
          ${result ? `<div class="kv"><span class="k">result</span><pre class="scroll">${escapeHtml(result)}</pre></div>` : ""}
        </div>`;
    })
    .join("");
}

function renderEvidence(evidence) {
  if (!evidence.length) return '<em class="muted">No evidence gathered.</em>';
  return evidence
    .map((e, i) => {
      const n = i + 1;
      const src = escapeHtml(e.source || "source");
      const title = e.url
        ? `<a href="${escapeHtml(e.url)}" target="_blank" rel="noopener">${escapeHtml(e.id)} ↗</a>`
        : escapeHtml(e.id);
      const ts = e.timestamp
        ? `<span class="muted">${escapeHtml(e.timestamp)}</span>`
        : "";
      return `
        <div class="evidence-card" id="ev-${n}">
          <div class="evidence-head">
            <span class="tag tag-${src}">${src}</span>
            <span class="ev-id">[E${n}] ${title}</span>
            ${ts}
          </div>
          <p class="evidence-text">${escapeHtml(e.text)}</p>
        </div>`;
    })
    .join("");
}

function renderMemory(memory) {
  if (!memory.length) {
    return '<em class="muted">No prior-session memory was recalled for this question.</em>';
  }
  return memory
    .map((m, i) => {
      const n = i + 1;
      const tags = (m.topic_tags || [])
        .map((t) => `<span class="chip">${escapeHtml(t)}</span>`)
        .join("");
      return `
        <div class="memory-card" id="mem-${n}">
          <div class="memory-head"><span class="ev-id">[M${n}]</span>${tags}</div>
          <p>${escapeHtml(m.text)}</p>
        </div>`;
    })
    .join("");
}

// --- top-level render ------------------------------------------------------

function renderTrace(trace) {
  $("trace-question").textContent = trace.question || "";
  const meta = [];
  if (trace.run_id) meta.push(`run ${trace.run_id}`);
  meta.push(trace.repo ? trace.repo : "offline demo");
  if (trace.private) meta.push("private · not saved");
  meta.push(`${(trace.evidence || []).length} evidence`);
  meta.push(`${(trace.memory_used || []).length} memory`);
  $("trace-meta").textContent = meta.join(" · ");

  const html = [
    renderAnswer(trace),
    section("Plan", (trace.plan || []).length, true, renderPlan(trace.plan || [])),
    section("Tool Calls", (trace.tool_calls || []).length, false, renderToolCalls(trace.tool_calls || [])),
    section("Evidence", (trace.evidence || []).length, true, renderEvidence(trace.evidence || [])),
    section("Memory Used", (trace.memory_used || []).length, true, renderMemory(trace.memory_used || [])),
  ].join("");

  $("sections").innerHTML = html;
  $("trace").hidden = false;
  $("sections").querySelectorAll("a.cite").forEach((a) => a.addEventListener("click", onCiteClick));
  $("trace").scrollIntoView({ behavior: "smooth", block: "start" });
}

// --- settings (bring-your-own-key) -----------------------------------------

const SETTINGS_KEY = "agentic-rag.settings.v1";

// Picking a provider fills in its endpoint + a model that works there.
const PROVIDERS = {
  openai: { baseUrl: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  openrouter: { baseUrl: "https://openrouter.ai/api/v1", model: "openrouter/free" },
  xai: { baseUrl: "https://api.x.ai/v1", model: "grok-2-latest" },
  custom: null,
};

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_) {
    return {}; // storage blocked (e.g. some private modes) or corrupt -> defaults
  }
}

function saveSettings(settings) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    return true;
  } catch (_) {
    return false;
  }
}

function fillSettingsForm(s) {
  $("s-provider").value = s.provider || "openai";
  $("s-base-url").value = s.llmBaseUrl || "";
  $("s-model").value = s.llmModel || "";
  $("s-llm-key").value = s.llmApiKey || "";
  $("s-github-token").value = s.githubToken || "";
}

function readSettingsForm() {
  return {
    provider: $("s-provider").value,
    llmBaseUrl: $("s-base-url").value.trim(),
    llmModel: $("s-model").value.trim(),
    llmApiKey: $("s-llm-key").value.trim(),
    githubToken: $("s-github-token").value.trim(),
  };
}

function updateLlmStatus() {
  const s = loadSettings();
  const el = $("llm-status");
  if (s.llmApiKey) {
    el.textContent = `LLM: your key · ${s.llmModel || "default model"}`;
    el.className = "llm-status llm-own";
  } else {
    el.textContent = "LLM: server default";
    el.className = "llm-status";
  }
  if (s.githubToken) el.textContent += " · GitHub token set";
}

function setSettingsMsg(message, kind = "") {
  const el = $("settings-msg");
  el.textContent = message;
  el.className = "settings-msg" + (kind ? ` status-${kind}` : "");
}

function openSettings() {
  fillSettingsForm(loadSettings());
  setSettingsMsg("");
  $("settings").hidden = false;
  $("settings-backdrop").hidden = false;
  $("settings-open").setAttribute("aria-expanded", "true");
  $("s-provider").focus();
}

function closeSettings() {
  $("settings").hidden = true;
  $("settings-backdrop").hidden = true;
  $("settings-open").setAttribute("aria-expanded", "false");
  $("settings-open").focus();
}

// --- data calls ------------------------------------------------------------

// FastAPI returns errors as {"detail": "..."} (e.g. a bad repo URL -> 422, an
// unreadable/private repo -> 400); fall back to raw text otherwise.
async function errorDetail(resp) {
  const raw = await resp.text();
  try {
    const j = JSON.parse(raw);
    if (j && typeof j.detail === "string") return j.detail;
    if (j && Array.isArray(j.detail)) return j.detail.map((e) => e.msg).join("; ");
  } catch (_) {}
  return raw.slice(0, 300);
}

async function ask(question, repo) {
  setStatus("Thinking — planning, calling tools, synthesizing…", "busy");
  $("ask-btn").disabled = true;
  try {
    // Everything but the question is optional: no repo -> the offline seed
    // demo; no LLM key -> the server's default LLM config. Secrets from
    // Settings authenticate only this request and are never echoed back.
    const s = loadSettings();
    const payload = { question };
    if (repo) payload.repo = repo;
    if (s.githubToken) payload.github_token = s.githubToken;
    if (s.llmApiKey) {
      payload.llm_api_key = s.llmApiKey;
      if (s.llmBaseUrl) payload.llm_base_url = s.llmBaseUrl;
      if (s.llmModel) payload.llm_model = s.llmModel;
    }
    const resp = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      throw new Error(`${resp.status}: ${await errorDetail(resp)}`);
    }
    const trace = await resp.json();
    renderTrace(trace);
    setStatus(`Done in ${fmtMs((trace.timing_ms || {}).total_ms)}.`, "ok");
    loadRuns();
  } catch (err) {
    setStatus(`Something went wrong: ${err.message}`, "error");
  } finally {
    $("ask-btn").disabled = false;
  }
}

async function loadRuns() {
  try {
    const resp = await fetch("/runs");
    if (!resp.ok) return;
    const runs = await resp.json();
    $("recent-count").textContent = runs.length;
    $("recent-list").innerHTML = runs
      .map(
        (r) => `
        <li>
          <button type="button" class="run-item" data-run="${escapeHtml(r.run_id)}">
            <span class="run-q">${escapeHtml(r.question)}</span>
            <span class="run-meta">${r.n_evidence} evidence · ${fmtMs(r.total_ms)}</span>
          </button>
        </li>`
      )
      .join("");
    $("recent-list")
      .querySelectorAll(".run-item")
      .forEach((b) => b.addEventListener("click", () => loadRun(b.dataset.run)));
  } catch {
    /* recent runs are non-critical; ignore fetch errors */
  }
}

async function loadRun(runId) {
  setStatus(`Loading run ${runId}…`, "busy");
  try {
    const resp = await fetch(`/runs/${encodeURIComponent(runId)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const trace = await resp.json();
    $("question").value = trace.question || "";
    renderTrace(trace);
    setStatus(`Loaded run ${runId}.`, "ok");
  } catch (err) {
    setStatus(`Could not load run ${runId}: ${err.message}`, "error");
  }
}

// --- wiring ----------------------------------------------------------------

$("ask-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("question").value.trim();
  if (q) ask(q, $("repo").value.trim());
});

document.querySelectorAll(".example").forEach((btn) =>
  btn.addEventListener("click", () => {
    $("question").value = btn.dataset.q;
    ask(btn.dataset.q, $("repo").value.trim());
  })
);

$("settings-open").addEventListener("click", openSettings);
$("settings-close").addEventListener("click", closeSettings);
$("settings-backdrop").addEventListener("click", closeSettings);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("settings").hidden) closeSettings();
});

$("s-provider").addEventListener("change", (e) => {
  const preset = PROVIDERS[e.target.value];
  if (preset) {
    $("s-base-url").value = preset.baseUrl;
    $("s-model").value = preset.model;
  }
});

$("s-show").addEventListener("change", (e) => {
  const type = e.target.checked ? "text" : "password";
  $("s-llm-key").type = type;
  $("s-github-token").type = type;
});

$("settings-form").addEventListener("submit", (e) => {
  e.preventDefault();
  if (saveSettings(readSettingsForm())) {
    setSettingsMsg("Saved in this browser.", "ok");
  } else {
    setSettingsMsg("Couldn't save — this browser is blocking local storage.", "error");
  }
  updateLlmStatus();
});

$("settings-clear").addEventListener("click", () => {
  try {
    localStorage.removeItem(SETTINGS_KEY);
  } catch (_) {}
  fillSettingsForm({});
  setSettingsMsg("Cleared. Questions now use the server's defaults.", "ok");
  updateLlmStatus();
});

// Prime the LLM label and the recent-runs list on load.
updateLlmStatus();
loadRuns();
