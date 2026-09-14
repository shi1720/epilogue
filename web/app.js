/* Epilogue dashboard — vanilla JS, no build step. */

const $ = (id) => document.getElementById(id);

let state = null;
let refreshTimer = null;

/* ---------------- helpers ---------------- */

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

let accessCode = null;
try { accessCode = localStorage.getItem("epilogue_code"); } catch (e) {}

async function api(path, opts) {
  if (opts && opts.method === "POST") {
    opts.headers = opts.headers || {};
    if (accessCode) opts.headers["X-Epilogue-Code"] = accessCode;
  }
  const res = await fetch(path, opts);
  if (res.status === 401 && opts && opts.method === "POST") {
    const code = prompt("This shared demo asks for an access code:");
    if (code) {
      accessCode = code;
      try { localStorage.setItem("epilogue_code", code); } catch (e) {}
      opts.headers["X-Epilogue-Code"] = code;
      const retry = await fetch(path, opts);
      if (!retry.ok) throw new Error(await retry.text());
      return retry.json();
    }
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/* ---------------- rendering ---------------- */

const CATEGORY_LABELS = {
  financial: "Money & accounts",
  subscriptions: "Subscriptions & services",
  utilities: "The house",
  government: "Government",
  insurance: "Insurance",
  identity: "Identity protection",
  benefits: "Money owed to the family",
  memorial: "Memorial",
  digital_legacy: "Photos, memories & digital life",
};

const STATUS_LABELS = {
  pending: "queued",
  in_progress: "working",
  waiting_response: "awaiting reply",
  needs_decision: "needs you",
  follow_up: "will chase",
  done: "settled",
  dismissed: "set aside",
};

function render() {
  if (!state) return;
  if (!state.case) {
    $("intake-view").hidden = false;
    $("dashboard-view").hidden = true;
    return;
  }
  $("intake-view").hidden = true;
  $("dashboard-view").hidden = false;

  const c = state.case;
  const s = state.stats;
  const deceased = c.deceased.full_name;
  const born = c.deceased.date_of_birth ? c.deceased.date_of_birth.slice(0, 4) : "";
  const died = c.deceased.date_of_death ? c.deceased.date_of_death.slice(0, 4) : "";
  $("case-line").textContent =
    `Settling the affairs of ${deceased}` + (died ? ` · ${born ? born + "–" : ""}${died}` : "");
  const simD = new Date(s.sim_today + "T00:00:00");
  $("sim-date").textContent = simD.toLocaleDateString("en-US", {
    weekday: "long", month: "long", day: "numeric", year: "numeric",
  });
  $("busy-dot").className = "status-dot " + (state.status === "idle" ? "idle" : "working");

  // hero
  const open = state.decisions.filter((d) => d.status === "open");
  const first = c.survivor.full_name.split(" ")[0];
  $("hero-line").textContent =
    open.length === 0
      ? `Nothing needs you right now, ${first}. Everything is being handled.`
      : open.length === 1
        ? `One thing needs you, ${first}. Everything else is handled.`
        : `${open.length} things need you, ${first}. Everything else is handled.`;

  const stats = [
    [s.settled + " of " + s.total_matters, "matters settled"],
    [s.in_motion, "in motion"],
    [s.hours_given_back + " h", "given back to the family"],
  ];
  if (state.vault && state.vault_initial) {
    const left = state.vault.certified_death_certificate;
    const total = state.vault_initial.certified_death_certificate;
    if (typeof left === "number" && left >= 0 && total > 0) {
      stats.push([left + " of " + total, "certified copies in the vault"]);
    }
  }
  const row = $("stats-row");
  row.textContent = "";
  for (const [num, label] of stats) {
    const box = el("div", "stat");
    box.append(el("div", "stat-num", String(num)), el("div", "stat-label", label));
    row.append(box);
  }
  $("progress-fill").style.width =
    s.total_matters ? Math.round((100 * s.settled) / s.total_matters) + "%" : "0%";

  renderDecisions(open);
  renderMatters();
  renderTimeline();
  renderActivitySnapshot();

  const note = state.weekly_note;
  $("note-section").hidden = !note;
  if (note) $("weekly-note").textContent = note;
}

function renderDecisions(open) {
  $("decisions-section").hidden = open.length === 0;
  const wrap = $("decision-cards");
  wrap.textContent = "";
  for (const d of open) {
    const card = el("div", "decision-card");
    card.append(el("span", "urgency-chip urgency-" + d.urgency,
      d.urgency === "whenever" ? "whenever you're ready" : d.urgency.replace("_", " ")));
    card.append(el("p", "decision-q", d.question));
    card.append(el("p", "decision-context", d.context));
    const opts = el("div", "decision-options");
    for (const o of d.options) {
      const btn = el("button", "option-btn");
      btn.append(el("span", "opt-label", o.label));
      btn.append(el("span", "opt-consequence", o.consequence));
      if (d.recommendation === o.id) btn.append(el("span", "opt-rec", "Epilogue's suggestion"));
      btn.onclick = async () => {
        btn.disabled = true;
        await api(`/api/decisions/${d.id}/resolve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ option_id: o.id }),
        });
        refreshSoon();
      };
      opts.append(btn);
    }
    card.append(opts);
    wrap.append(card);
  }
}

function renderMatters() {
  const wrap = $("matters");
  wrap.textContent = "";
  const groups = {};
  for (const t of state.tasks) (groups[t.category] ||= []).push(t);
  const order = Object.keys(CATEGORY_LABELS).filter((k) => groups[k]);
  for (const k of Object.keys(groups)) if (!order.includes(k)) order.push(k);
  for (const cat of order) {
    const g = el("div", "matter-group");
    g.append(el("div", "matter-group-title", CATEGORY_LABELS[cat] || cat));
    for (const t of groups[cat]) {
      const m = el("div", "matter");
      const title = el("span", "matter-title", t.title);
      if (t.why) title.append(el("span", "matter-why", t.why));
      m.append(title);
      m.append(el("span", "chip " + t.status, STATUS_LABELS[t.status] || t.status));
      g.append(m);
    }
    wrap.append(g);
  }
}

function renderTimeline() {
  const wrap = $("timeline");
  wrap.textContent = "";
  for (const e of state.timeline.slice(0, 60)) {
    const item = el("div", "tl-item " + e.kind);
    item.append(el("div", "tl-date", fmtDate(e.sim_date) + " · " + e.actor));
    const line = el("div", "tl-summary", e.summary + " ");
    if ((e.kind === "letter_sent" || e.kind === "mail_received" || e.kind === "note") && e.detail) {
      const peek = el("span", "peek", "read");
      peek.onclick = () => showLetter(e);
      line.append(peek);
    }
    item.append(line);
    wrap.append(item);
  }
}

function renderActivitySnapshot() {
  const feed = $("activity-feed");
  if (feed.childElementCount > 0) return; // live feed is already flowing
  for (const e of state.activity.slice(0, 40).reverse()) appendActivity(e, false);
}

function appendActivity(e, scroll = true) {
  const feed = $("activity-feed");
  const line = el("div");
  if (e.kind === "clock") {
    line.className = "clock-mark";
    line.textContent = e.summary;
  } else {
    const actor = el("span", "actor", e.actor ? e.actor + " " : "");
    line.append(actor, document.createTextNode(e.summary));
  }
  feed.append(line);
  while (feed.childElementCount > 120) feed.removeChild(feed.firstChild);
  if (scroll) feed.scrollTop = feed.scrollHeight;
}

function showLetter(e) {
  const body = $("modal-body");
  body.textContent = "";
  body.append(el("div", "letter-head", e.summary));
  body.append(el("div", "letter-meta", (e.sim_date ? fmtDate(e.sim_date) + " · " : "") + e.actor));
  body.append(document.createTextNode(e.detail || ""));
  $("modal").hidden = false;
}

/* ---------------- data flow ---------------- */

async function refresh() {
  try {
    state = await api("/api/state");
    render();
  } catch (err) {
    console.error(err);
  }
}

function refreshSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, 500);
}

function connectFeed() {
  const src = new EventSource("/api/feed");
  src.onmessage = (msg) => {
    const e = JSON.parse(msg.data);
    if (e.kind === "hello") return;
    if (!$("dashboard-view").hidden) {
      appendActivity(e);
      $("activity-pulse").hidden = false;
      clearTimeout(connectFeed._pulseT);
      connectFeed._pulseT = setTimeout(() => ($("activity-pulse").hidden = true), 4000);
    }
    if (!$("intake-view").hidden && !$("intake-progress").hidden) {
      const feed = $("intake-feed");
      const line = document.createElement("div");
      line.textContent = (e.actor && e.actor !== "Epilogue" ? e.actor + " — " : "") + e.summary;
      feed.append(line);
      feed.scrollTop = feed.scrollHeight;
      if (e.kind === "status") $("intake-status").textContent = e.summary;
      if (e.kind === "error") {
        $("intake-status").textContent = e.summary + " — check the server logs, then try again.";
        $("begin-btn").disabled = false;
      }
    }
    if (e.kind === "case_ready") { refresh(); }
    if (["letter_sent", "mail_received", "decision_opened", "decision_resolved", "status", "note", "done", "clock"].includes(e.kind)) {
      refreshSoon();
    }
  };
  src.onerror = () => { /* EventSource auto-reconnects */ };
}

/* ---------------- intake ---------------- */

$("seed-btn").onclick = async () => {
  const seed = await api("/api/seed");
  $("narrative").value = seed.narrative;
  $("documents").value = seed.documents;
};

$("begin-btn").onclick = async () => {
  const narrative = $("narrative").value.trim();
  const documents = $("documents").value.trim();
  if (!narrative) return;
  $("begin-btn").disabled = true;
  $("intake-progress").hidden = false;
  try {
    await api("/api/case", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ narrative, documents }),
    });
  } catch (err) {
    $("intake-status").textContent = "Something went wrong starting the case — please try again.";
    $("begin-btn").disabled = false;
  }
};

/* ---------------- clock ---------------- */

for (const btn of document.querySelectorAll(".clock-btn")) {
  btn.onclick = async () => {
    document.querySelectorAll(".clock-btn").forEach((b) => (b.disabled = true));
    try {
      await api("/api/clock/advance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ days: parseInt(btn.dataset.days, 10) }),
      });
    } finally {
      setTimeout(() => document.querySelectorAll(".clock-btn").forEach((b) => (b.disabled = false)), 1500);
    }
  };
}

/* ---------------- modal ---------------- */

$("modal-close").onclick = () => ($("modal").hidden = true);
$("modal").onclick = (ev) => { if (ev.target === $("modal")) $("modal").hidden = true; };

/* ---------------- boot ---------------- */

refresh();
connectFeed();
setInterval(refresh, 12000);
