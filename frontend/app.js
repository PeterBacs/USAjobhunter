/* USA JOB HUNTER — single-page frontend (vanilla JS, no build step). */
"use strict";

// ------------------------------------------------------------------ utilities
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};
const fmtMoney = (v) => (v || v === 0) ? "$" + Math.round(v).toLocaleString("en-US") : "";
const fmtDate = (s) => s ? new Date(s.length === 10 ? s + "T00:00:00" : s + (s.endsWith("Z") ? "" : "Z")).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";
const fmtDT = (s) => s ? new Date(s + (s.endsWith("Z") ? "" : "Z")).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
const title = (s) => String(s || "").replace(/_/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());

async function api(path, opts = {}) {
  const o = { credentials: "same-origin", ...opts, headers: { ...(opts.headers || {}) } };
  if (o.body && !(o.body instanceof FormData)) { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(o.body); }
  const r = await fetch(path, o);
  if (r.status === 401 && !path.startsWith("/api/auth")) { showAuth(); throw new Error("Please sign in"); }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : `HTTP ${r.status}`);
  return data;
}
function toast(msg, ms = 3200) { const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), ms); }
function copy(text) { navigator.clipboard?.writeText(text).then(() => toast("Copied to clipboard"), () => toast("Copy failed")); }

// ------------------------------------------------------------------ badges (color + icon + label, never color alone)
const STATUS = {
  ACTIVE: ["b-good", "● ACTIVE"], POSSIBLY_ACTIVE: ["b-warn", "◐ POSSIBLY ACTIVE"], CLOSED: ["b-bad", "✕ CLOSED"], UNKNOWN: ["b-unk", "○ STATUS UNKNOWN"],
};
const J1 = {
  CONFIRMED_J1_VACANCY: ["b-good", "✓ Confirmed J-1 vacancy"], CONFIRMED_J1_EMPLOYER: ["b-good", "✓ Confirmed J-1 employer"],
  INTERNATIONAL_FRIENDLY: ["b-warn", "◐ International friendly"], NEEDS_CONFIRMATION: ["b-warn", "? J-1 needs confirmation"],
  NO_SPONSORSHIP: ["b-bad", "✕ No sponsorship"], UNKNOWN: ["b-unk", "○ J-1 unknown"],
};
const VER = { VERIFIED: ["b-good", "✓ Verified"], PARTIALLY_VERIFIED: ["b-warn", "◐ Partially verified"], UNKNOWN: ["b-unk", "○ Unknown"], CONFLICTING: ["b-bad", "! Conflicting"] };
const EMAIL = { VERIFIED: ["b-good", "✓ Verified"], PUBLISHED_ELSEWHERE: ["b-warn", "◐ Published elsewhere"], DO_NOT_USE: ["b-bad", "✕ Do not use"], NONE: ["b-unk", "○ Not published"] };
const MAILBOX = {
  EXISTS: ["b-good", "✓ Mailbox exists"], NOT_FOUND: ["b-bad", "✕ Mailbox doesn't exist"],
  NO_MAIL_SERVER: ["b-bad", "✕ No mail server"], CATCH_ALL: ["b-warn", "◐ Can't confirm (accepts all)"],
  UNKNOWN: ["b-unk", "? Check inconclusive"],
};
const mailboxBadge = (c) => c && c.email ? (MAILBOX[c.mailbox_status] ? badge(MAILBOX, c.mailbox_status) : `<span class="badge b-unk">○ Mailbox not checked</span>`) : "";
const deadMailbox = (c) => c && ["NOT_FOUND", "NO_MAIL_SERVER"].includes(c.mailbox_status);
const badge = (map, key) => { const [c, l] = map[key] || ["b-unk", title(key || "unknown")]; return `<span class="badge ${c}">${esc(l)}</span>`; };
function freshBadge(f, posted) {
  if (!f || f.days === null || f.days === undefined) return `<span class="badge b-unk">○ Date unknown</span>`;
  const cls = { green: "b-good", yellow: "b-warn", orange: "b-orange", red: "b-bad" }[f.color] || "b-unk";
  return `<span class="badge ${cls}" title="Posted ${esc(posted)}"><span class="dot"></span>${esc(fmtDate(posted).replace(/, \d{4}$/, ""))} — ${esc(f.label)}</span>`;
}
function matchBox(score) {
  if (score === null || score === undefined) return `<span class="match lo">—<small>MATCH</small></span>`;
  return `<span class="match ${score >= 90 ? "hi" : score < 60 ? "lo" : ""}" title="Prioritization aid, not a hiring prediction">${score}%<small>MATCH</small></span>`;
}
function salary(j) {
  if (j.salary_min && j.salary_max && j.salary_min !== j.salary_max) return `${fmtMoney(j.salary_min)}–${fmtMoney(j.salary_max)}`;
  if (j.salary_max) return fmtMoney(j.salary_max);
  if (j.salary_text) return esc(j.salary_text);
  return `<span class="muted">Not published</span>`;
}
// Only emails confirmed to exist by the school's mail server are ever displayed (the API withholds the rest).
const emailCell = (c) => {
  if (!c) return `<span class="muted">—</span>`;
  if (c.email) return `<a href="mailto:${esc(c.email)}" onclick="event.stopPropagation()">${esc(c.email)}</a><br>${badge(MAILBOX, "EXISTS")}`;
  return `<span class="muted small">No confirmed email</span>`;
};
const emailLine = (c) => c.email
  ? `<a href="mailto:${esc(c.email)}">${esc(c.email)}</a> ${badge(MAILBOX, "EXISTS")}`
  : `<span class="muted">No confirmed email${c.has_unconfirmed_email ? (deadMailbox(c) ? " (published address doesn't exist)" : " (published address not confirmed yet)") : ""}</span>`;
const personCell = (c) => c ? `<div class="t">${esc(c.full_name || c.title || "Unnamed contact")}</div><div class="s">${esc(c.full_name ? (c.title || "") : "")}</div>${badge(VER, c.verification_status)}` : `<span class="muted small">Not found</span>`;

// ------------------------------------------------------------------ app state
const S = {
  me: null, demo: store.get("jh_demo", false), view: store.get("jh_view", "table"), page: 1,
  F: store.get("jh_filters", { sort: "match" }), facets: null, scanRun: null,
};
const NAV = [
  ["dashboard", "▦", "Dashboard"], ["jobs", "⌕", "Job Hunter"], ["map", "▩", "USA Map"], ["j1", "✈", "J-1 Jobs"],
  ["high", "★", "High Match"], ["saved", "♥", "Saved Jobs"], "-", ["applications", "▤", "Applications"], ["outbox", "📨", "Outbox"],
  ["contacts", "☎", "Contacts"], ["interviews", "◷", "Interviews"], ["alerts", "🔔", "Alerts"], ["documents", "🗎", "Documents"],
  "-", ["engineering", "🔧", "Engineering Jobs"], ["h1b", "🛂", "H-1B Sponsors"], ["sites", "🌐", "Job Sites"], ["monitor", "⚙", "Scan Monitor"], ["settings", "⚒", "Settings"],
];

function renderNav(active, unread = 0, outboxN = S.outboxPending || 0) {
  const cnt = (k) => k === "alerts" && unread ? `<span class="count">${unread}</span>` : k === "outbox" && outboxN ? `<span class="count" title="Emails waiting for your approval">${outboxN}</span>` : "";
  $("#nav").innerHTML = NAV.map((n) => n === "-" ? `<div class="sep"></div>` :
    `<a href="#/${n[0]}" class="${active === n[0] ? "active" : ""}"><span class="ico">${n[1]}</span>${n[2]}${cnt(n[0])}</a>`).join("");
}

// ------------------------------------------------------------------ auth
async function showAuth() {
  $("#shell").classList.add("hidden");
  const st = await api("/api/auth/status");
  const setup = st.needs_setup;
  $("#auth").classList.remove("hidden");
  $("#auth").innerHTML = `<div class="card"><div class="brand" style="border:0;padding:0 0 14px"><span class="logo" style="background:var(--navy);color:#fff">∑</span><div><b style="color:var(--ink)">USA JOB HUNTER</b><small>Verified U.S. Mathematics Teaching Jobs for International Educators</small></div></div>
    <h2>${setup ? "Create your account" : "Sign in"}</h2>
    <form class="form" id="authForm">
      ${setup ? `<label>Full name<input name="full_name" required></label>` : ""}
      <label>Email<input name="email" type="email" required autocomplete="username"></label>
      <label>Password<input name="password" type="password" minlength="8" required autocomplete="${setup ? "new-password" : "current-password"}"></label>
      ${st.awaiting_data ? `<div class="notice warn small">Your account isn't online yet. On your computer, double-click <b>Upload my data to the cloud.bat</b> (in the JOB HUNTER folder), paste the DATABASE_URL from Vercel &gt; Storage, and wait for "Done". Then sign in here with the same email and password as on your computer.</div>` : ""}
            <button class="btn primary">${setup ? "Create account" : "Sign in"}</button>
      <div class="muted small" id="authErr"></div>
    </form></div>`;
  $("#authForm").onsubmit = async (e) => {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(e.target));
    try { await api(setup ? "/api/auth/setup" : "/api/auth/login", { method: "POST", body: fd }); boot(); }
    catch (err) { $("#authErr").textContent = err.message; }
  };
}

async function boot() {
  try { S.me = await api("/api/me"); } catch { return; }
  $("#auth").classList.add("hidden");
  $("#shell").classList.remove("hidden");
  route();
  pollScan();
  // Scheduled scans run in the background, so look for newly prepared emails every few minutes.
  clearInterval(S.outboxTimer); S.outboxTimer = setInterval(() => checkOutbox(), 5 * 60 * 1000);
}

// ------------------------------------------------------------------ router
window.addEventListener("hashchange", route);
async function route() {
  const h = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [name, arg] = h.split("/");
  $("#sidebar").classList.remove("open");
  if (name === "job" && arg) {
    // Remember whether this job was opened from a page inside the app (so ✕ can go back to it).
    S.openedFromPage = !!S.lastPage;
    if (!$("#view").innerHTML) await renderView((S.lastPage || "#/jobs").replace(/^#\/?/, "").split("/")[0] || "jobs");
    openJob(+arg);
    return;
  }
  S.lastPage = location.hash || "#/dashboard";
  closeDrawer(true);
  await renderView(name);
}
async function renderView(name) {
  let unread = 0;
  try { unread = (await api("/api/alerts")).unread; } catch { /* ignore */ }
  S.unread = unread;
  renderNav(name, unread);
  checkOutbox();
  const v = $("#view");
  v.innerHTML = `<div class="empty">Loading…</div>`;
  const views = { dashboard: viewDashboard, jobs: () => viewJobs("jobs"), high: () => viewJobs("high"), saved: () => viewJobs("saved"),
    j1: viewJ1, map: viewMap, applications: viewApplications, contacts: viewContacts, interviews: viewInterviews,
    alerts: viewAlerts, documents: viewDocuments, settings: viewSettings, monitor: viewMonitor, sites: viewJobSites, h1b: viewH1B, engineering: viewEngineering, outbox: viewOutbox };
  try { await (views[name] || viewDashboard)(); } catch (e) { v.innerHTML = `<div class="empty"><b>Something went wrong</b>${esc(e.message)}</div>`; }
}
const demoBanner = () => S.demo ? `<div class="demo-banner">DEMO / FICTIONAL DATA mode is on — these records are not real vacancies. Turn it off in Settings.</div>` : "";

// ------------------------------------------------------------------ dashboard
async function viewDashboard() {
  const [d, f] = await Promise.all([api(`/api/dashboard?demo=${S.demo}`), api(`/api/jobs/facets?demo=${S.demo}`)]);
  S.facets = f;
  const c = d.cards;
  const K = [
    ["Active Math Jobs", c.active_math_jobs, "#/jobs"], ["New Today", c.new_today, "#/jobs"], ["New This Week", c.new_this_week, "#/jobs"],
    ["90%+ Matches", c.matches_90, "#/high"], ["Confirmed J-1", c.confirmed_j1, "#/j1"], ["Verified Contacts", c.verified_contacts, "#/contacts"],
    ["Applications Sent", c.applications_sent, "#/applications"], ["Follow-ups Due", c.follow_ups_due, "#/applications"],
    ["Interviews", c.interviews, "#/interviews"], ["Offers", c.offers, "#/applications"],
  ];
  const stageOrder = ["DISCOVERED", "SAVED", "APPLYING", "APPLIED", "FOLLOW_UP", "INTERVIEW", "SECOND_INTERVIEW", "OFFER", "HIRED", "REJECTED", "WITHDRAWN", "POSITION_CLOSED"];
  const stages = Object.fromEntries(stageOrder.filter((s) => d.applications_by_stage[s]).map((s) => [title(s), d.applications_by_stage[s]]));
  const j1 = Object.fromEntries(Object.entries(f.by_j1).map(([k, v]) => [(J1[k] || [0, k])[1].replace(/^[^ ]+ /, ""), v]));
  const topStates = Object.fromEntries(Object.entries(f.by_state).sort((a, b) => b[1] - a[1]).slice(0, 12));
  const salOrder = ["< $50k", "$50-60k", "$60-70k", "$70-80k", "$80-100k", "$100k+", "Not published"];
  const sal = Object.fromEntries(salOrder.filter((k) => f.by_salary[k]).map((k) => [k, f.by_salary[k]]));
  const ls = d.last_scan;
  $("#view").innerHTML = `${demoBanner()}
    <div class="page-head"><div><h1>Dashboard</h1><p>Current Mathematics teaching vacancies from official sources, with your application pipeline.</p></div>
      <div class="row"><button class="btn" onclick="startScan('VERIFY_JOBS')">VERIFY JOBS</button><button class="btn" onclick="startScan('VERIFY_CONTACTS')">VERIFY CONTACTS</button><button class="btn" onclick="startScan('J1')">CHECK J-1 STATUS</button></div></div>
    <div class="kpis">${K.map(([l, v, href]) => `<div class="kpi click" onclick="location.hash='${href}'"><div class="lbl">${l}</div><div class="val">${v}</div></div>`).join("")}</div>
    ${c.active_math_jobs === 0 && !S.demo ? `<div class="notice" style="margin-bottom:14px">No vacancies stored yet. Press <b>SCAN USA NOW</b> to search official district job boards and SchoolSpring nationwide. Only real, source-linked postings are stored.</div>` : ""}
    <div class="charts">
      <div class="card"><h3>Jobs by State (top 12)</h3>${bars(topStates, (k) => `#/jobs?states=${k}`)}</div>
      <div class="card"><h3>Jobs by Salary (published maximum)</h3>${bars(sal)}</div>
      <div class="card"><h3>Jobs by Grade Level</h3>${bars(Object.fromEntries(Object.entries(f.by_grade).sort((a, b) => b[1] - a[1])))}</div>
      <div class="card"><h3>Jobs by J-1 Status</h3>${bars(j1)}</div>
      <div class="card"><h3>Applications by Stage</h3>${Object.keys(stages).length ? bars(stages) : `<div class="muted small">No applications tracked yet.</div>`}</div>
      <div class="card"><h3>Last Scan</h3>${ls ? scanSummary(ls) : `<div class="muted small">No scans yet.</div>`}</div>
    </div>`;
}
function bars(obj, linkFn) {
  const entries = Object.entries(obj);
  if (!entries.length) return `<div class="muted small">No data yet.</div>`;
  const max = Math.max(...entries.map((e) => e[1]), 1);
  return `<div class="bars" role="table">${entries.map(([k, v]) => `<div class="bar-row" role="row" title="${esc(k)}: ${v}" ${linkFn ? `style="cursor:pointer" onclick="applyQuickFilter('${esc(k)}')"` : ""}>
    <span class="lab" role="cell">${esc(k)}</span><span class="track"><span class="fill" style="width:${(v / max) * 100}%;display:block"></span></span><span class="v" role="cell">${v}</span></div>`).join("")}</div>`;
}
window.applyQuickFilter = (st) => { S.F = { sort: "match", states: [st] }; store.set("jh_filters", S.F); location.hash = "#/jobs"; };
function scanSummary(r) {
  const s = r.stats || {};
  const rows = [
    ["States searched", s.states_searched], ["Sources checked", s.sources_checked], ["Potential jobs discovered", s.potential_jobs_discovered],
    ["Verified Math jobs", s.verified_math_jobs], ["New jobs", s.new_jobs], ["Duplicates removed", s.duplicates_removed],
    ["Closed jobs detected", s.closed_jobs_detected], ["Jobs with verified contacts", s.jobs_with_verified_contacts],
    ["Confirmed J-1 opportunities", s.confirmed_j1_opportunities], ["Jobs checked", s.jobs_checked], ["Contacts checked", s.contacts_checked],
    ["Principals found", s.principals_found], ["Districts researched", s.districts_researched],
  ].filter((x) => x[1] !== undefined && x[1] !== null);
  return `<div class="small muted" style="margin-bottom:8px">${esc(title(r.kind))} · ${esc(r.status)} · ${fmtDT(r.finished_at || r.started_at)}${s.coverage ? " · " + esc(s.coverage) : ""}</div>
    <div class="scan-summary">${rows.map(([k, v]) => `<div><span>${k}</span><b>${esc(v)}</b></div>`).join("")}</div>
    ${r.error ? `<div class="notice warn small" style="margin-top:8px">${esc(r.error.split("\n")[0])}</div>` : ""}`;
}

// ------------------------------------------------------------------ job hunter
const SUBJECTS = ["Mathematics", "Algebra", "Geometry", "Calculus", "Precalculus", "Statistics", "STEM", "Robotics", "Engineering", "Physics", "Computer Science"];
const GRADES = [["Elementary", "Elementary"], ["Middle School", "Middle"], ["High School", "High School"], ["Grades 6-12", "Grades 6-12"], ["Grades 7-12", "Grades 7-12"]];
const J1F = [["CONFIRMED_J1_VACANCY", "Confirmed J-1 Vacancy"], ["CONFIRMED_J1_EMPLOYER", "Confirmed J-1 Employer"], ["INTERNATIONAL_FRIENDLY", "International Friendly"], ["NEEDS_CONFIRMATION", "Needs Confirmation"], ["UNKNOWN", "Unknown"]];
const FRESH = [["", "Any time"], ["0", "Today"], ["3", "Last 3 days"], ["7", "Last 7 days"], ["14", "Last 14 days"], ["30", "Last 30 days"]];
const CONTACTF = [["verified_recruiter_email", "Verified recruiter email"], ["verified_principal_email", "Verified principal email"], ["named_recruiter", "Named recruiter"], ["named_principal", "Named principal"], ["direct_phone", "Direct phone"], ["vacancy_contact_only", "Vacancy-specific contact only"]];
const APPF = [["NOT_APPLIED", "Not Applied"], ["INTERESTED", "Interested (saved)"], ["APPLIED", "Applied"], ["FOLLOW_UP", "Follow-up"], ["INTERVIEW", "Interview"], ["OFFER", "Offer"], ["REJECTED", "Rejected"], ["POSITION_CLOSED", "Closed"]];

function preset(kind) {
  if (kind === "high") return { min_match: 90 };
  if (kind === "saved") return { saved_only: true, include_closed: true };
  if (kind === "j1") return { j1: ["CONFIRMED_J1_VACANCY", "CONFIRMED_J1_EMPLOYER", "INTERNATIONAL_FRIENDLY", "NEEDS_CONFIRMATION"] };
  return {};
}
function buildQuery(F, extra = {}) {
  const p = new URLSearchParams();
  const all = { ...F, ...extra };
  for (const [k, v] of Object.entries(all)) {
    if (v === undefined || v === null || v === "" || v === false || (Array.isArray(v) && !v.length)) continue;
    p.set(k, Array.isArray(v) ? v.join(",") : v);
  }
  if (S.demo) p.set("demo", "true");
  return p.toString();
}

async function viewJobs(kind, host = $("#view")) {
  if (!S.facets) S.facets = await api(`/api/jobs/facets?demo=${S.demo}`);
  const heads = { jobs: ["Job Hunter", "All current Mathematics & STEM vacancies found on official sources."], high: ["High Match", "Vacancies scoring 90%+ against your résumé."], saved: ["Saved Jobs", "Jobs you saved (including closed ones, kept for history)."], j1: ["J-1 Jobs", "Vacancies with J-1 / international-teacher evidence or pending confirmation."] };
  const [h1, sub] = heads[kind] || heads.jobs;
  const F = S.F;
  const isChecked = (arr, v) => (F[arr] || []).includes(v) ? "checked" : "";
  host.innerHTML = `${demoBanner()}<div class="page-head"><div><h1>${h1}</h1><p>${sub}</p></div>
    <div class="row"><span class="small muted">Export</span><button class="btn sm" onclick="doExport('csv')">CSV</button><button class="btn sm" onclick="doExport('xlsx')">Excel</button><button class="btn sm" onclick="doExport('pdf')">PDF</button></div></div>
  <div class="hunter${store.get("jh_filters_hidden", false) ? " filters-hidden" : ""}">
    <aside class="card filters" id="filters">
      <div class="row between"><b>Filters</b><button class="linkbtn" style="color:var(--accent-ink)" id="clearF">Clear</button></div>
      <details open><summary>Location</summary>
        <label class="ck"><input type="checkbox" id="allUsa" ${(F.states || []).length ? "" : "checked"}> All USA</label>
        <input class="fi" id="stateFind" placeholder="Find a state…" autocomplete="off">
        <div class="states">${S.facets.states.map((s) => `<label class="ck" title="${esc(s.name)}" data-sname="${esc((s.code + " " + s.name).toLowerCase())}"><input type="checkbox" data-arr="states" value="${s.code}" ${isChecked("states", s.code)}><span class="st-name"><b>${s.code}</b> – ${esc(s.name)}</span>${S.facets.by_state[s.code] ? `<span class="st-count">${S.facets.by_state[s.code]}</span>` : ""}</label>`).join("")}</div>
        <input class="fi" data-key="city" placeholder="City" value="${esc(F.city || "")}">
        <input class="fi" data-key="district" placeholder="School district" list="districtList" value="${esc(F.district || "")}">
        <datalist id="districtList">${S.facets.districts.map((d) => `<option value="${esc(d)}">`).join("")}</datalist>
        <input class="fi" data-key="school" placeholder="School" value="${esc(F.school || "")}">
        <input class="fi" data-key="zip" placeholder="ZIP code" value="${esc(F.zip || "")}">
        <div class="row" style="gap:6px"><select class="fi" data-key="near_city" style="flex:1"><option value="">Radius from city…</option>${S.facets.cities_with_coordinates.map((c) => `<option value="${esc(c)}" ${F.near_city === c ? "selected" : ""}>${esc(c.replace("|", ", "))}</option>`).join("")}</select>
        <select class="fi" data-key="radius" style="width:84px"><option value="">mi</option>${[10, 25, 50, 100, 200].map((r) => `<option ${+F.radius === r ? "selected" : ""}>${r}</option>`).join("")}</select></div>
      </details>
      <details open><summary>Subject</summary>${SUBJECTS.map((s) => `<label class="ck"><input type="checkbox" data-arr="subjects" value="${s}" ${isChecked("subjects", s)}>${s}</label>`).join("")}</details>
      <details open><summary>Grade</summary>${GRADES.map(([l, v]) => `<label class="ck"><input type="checkbox" data-arr="grades" value="${v}" ${isChecked("grades", v)}>${l}</label>`).join("")}</details>
      <details open><summary>J-1</summary>${J1F.map(([v, l]) => `<label class="ck"><input type="checkbox" data-arr="j1" value="${v}" ${isChecked("j1", v)}>${l}</label>`).join("")}
        <label class="ck"><input type="checkbox" data-bool="exclude_no_sponsorship" ${F.exclude_no_sponsorship ? "checked" : ""}>Exclude No Sponsorship</label></details>
      <details open><summary>Freshness</summary>${FRESH.map(([v, l]) => `<label class="ck"><input type="radio" name="fresh" data-key="max_days" value="${v}" ${String(F.max_days ?? "") === v ? "checked" : ""}>${l}</label>`).join("")}</details>
      <details open><summary>Salary</summary><div class="row between small"><span>Minimum</span><b id="salv">${F.min_salary ? fmtMoney(F.min_salary) + (F.min_salary >= 150000 ? "+" : "") : "Any"}</b></div>
        <input type="range" min="40000" max="150000" step="5000" data-key="min_salary" value="${F.min_salary || 40000}" style="width:100%">
        <div class="row between tiny muted"><span>$40,000</span><span>$150,000+</span></div><div class="tiny muted">Only jobs with a published salary pass a minimum.</div></details>
      <details><summary>Contact</summary>${CONTACTF.map(([v, l]) => `<label class="ck"><input type="checkbox" data-arr="contact" value="${v}" ${isChecked("contact", v)}>${l}</label>`).join("")}</details>
      <details open><summary>Match</summary>${[["90", "90%+"], ["80", "80%+"], ["70", "70%+"], ["", "All"]].map(([v, l]) => `<label class="ck"><input type="radio" name="mm" data-key="min_match" value="${v}" ${String(F.min_match ?? "") === v ? "checked" : ""}>${l}</label>`).join("")}</details>
      <details><summary>Application</summary>${APPF.map(([v, l]) => `<label class="ck"><input type="checkbox" data-arr="app_status" value="${v}" ${isChecked("app_status", v)}>${l}</label>`).join("")}
        <label class="ck" style="margin-top:6px"><input type="checkbox" data-bool="include_applied" ${F.include_applied ? "checked" : ""}>Show jobs I've applied to</label>
        <div class="tiny muted">Applied jobs are hidden from job lists, the map and alerts. They stay in Applications.</div></details>
      <details><summary>Status</summary><label class="ck"><input type="checkbox" data-bool="include_closed" ${F.include_closed ? "checked" : ""}>Include closed jobs</label></details>
    </aside>
    <section><div class="toolbar"><button class="btn sm" id="toggleFilters" aria-controls="filters"></button><span id="count" class="grow small muted"></span>
      <select id="sort">${[["match", "Best match"], ["newest", "Newest"], ["salary", "Highest salary"], ["deadline", "Deadline soonest"], ["state", "State"]].map(([v, l]) => `<option value="${v}" ${F.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select>
      <div class="seg"><button data-v="table" class="${S.view === "table" ? "on" : ""}">Table</button><button data-v="cards" class="${S.view === "cards" ? "on" : ""}">Cards</button></div></div>
      <div id="results"></div></section>
  </div>`;
  const fEl = $("#filters", host);
  const save = () => { store.set("jh_filters", S.F); S.page = 1; loadResults(kind); };
  $("#stateFind", fEl).addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    $$(".states label", fEl).forEach((l) => (l.style.display = !q || l.dataset.sname.includes(q) ? "" : "none"));
  });
  fEl.addEventListener("change", (e) => {
    const t = e.target;
    if (t.id === "stateFind") return;
    if (t.id === "allUsa") { if (t.checked) { S.F.states = []; $$("[data-arr=states]", fEl).forEach((x) => (x.checked = false)); } save(); return; }
    if (t.dataset.arr) { const a = new Set(S.F[t.dataset.arr] || []); t.checked ? a.add(t.value) : a.delete(t.value); S.F[t.dataset.arr] = [...a]; if (t.dataset.arr === "states") $("#allUsa", fEl).checked = !a.size; }
    else if (t.dataset.bool) S.F[t.dataset.bool] = t.checked;
    else if (t.dataset.key) S.F[t.dataset.key] = t.dataset.key === "min_salary" ? (+t.value <= 40000 ? "" : +t.value) : t.value;
    save();
  });
  fEl.addEventListener("input", (e) => { if (e.target.dataset.key === "min_salary") $("#salv").textContent = +e.target.value <= 40000 ? "Any" : fmtMoney(+e.target.value) + (+e.target.value >= 150000 ? "+" : ""); });
  $("#clearF", fEl).onclick = () => { S.F = { sort: S.F.sort }; store.set("jh_filters", S.F); viewJobs(kind, host); };
  $("#sort", host).onchange = (e) => { S.F.sort = e.target.value; save(); };
  // Show / hide the filter panel so the results can use the full width. The label counts active filters.
  const hunter = $(".hunter", host), tBtn = $("#toggleFilters", host);
  const activeCount = () => Object.entries(S.F).filter(([k, v]) => k !== "sort" && v !== "" && v !== false && v !== null && v !== undefined && !(Array.isArray(v) && !v.length)).length;
  const paintToggle = () => {
    const hidden = hunter.classList.contains("filters-hidden"), n = activeCount();
    tBtn.innerHTML = hidden ? `☰ Show filters${n ? ` <span class="badge b-info" style="margin-left:4px">${n} on</span>` : ""}` : "✕ Hide filters";
    tBtn.setAttribute("aria-expanded", String(!hidden));
  };
  tBtn.onclick = () => { hunter.classList.toggle("filters-hidden"); store.set("jh_filters_hidden", hunter.classList.contains("filters-hidden")); paintToggle(); };
  fEl.addEventListener("change", () => setTimeout(paintToggle, 0));
  paintToggle();
  $$(".seg button", host).forEach((b) => (b.onclick = () => { S.view = b.dataset.v; store.set("jh_view", S.view); $$(".seg button", host).forEach((x) => x.classList.toggle("on", x === b)); loadResults(kind); }));
  await loadResults(kind);
}
async function loadResults(kind) {
  const q = buildQuery(S.F, { ...preset(kind), q: $("#globalSearch").value.trim(), page: S.page, page_size: 50 });
  const res = await api(`/api/jobs?${q}`);
  $("#count").textContent = `${res.total} vacanc${res.total === 1 ? "y" : "ies"}`;
  const box = $("#results");
  if (!res.items.length) {
    box.innerHTML = `<div class="card empty"><b>No vacancies match these filters</b>Loosen the filters, or run SCAN USA NOW. Only postings found on real sources are listed.</div>`;
    return;
  }
  box.innerHTML = (S.view === "cards" ? jobCards(res.items) : jobTable(res.items)) + pager(res, kind);
  $$("[data-job]", box).forEach((el) => (el.onclick = () => (location.hash = `#/job/${el.dataset.job}`)));
}
function pager(res, kind) {
  const pages = Math.ceil(res.total / res.page_size);
  if (pages <= 1) return "";
  return `<div class="pager"><button class="btn sm" ${res.page <= 1 ? "disabled" : ""} onclick="S.page--;loadResults('${kind}')">‹ Prev</button><span class="small">Page ${res.page} of ${pages}</span><button class="btn sm" ${res.page >= pages ? "disabled" : ""} onclick="S.page++;loadResults('${kind}')">Next ›</button></div>`;
}
function jobTable(items) {
  const H = ["Freshness", "Position hiring", "School / Employer", "Exact school", "State / City", "Grade level", "Salary", "Date posted", "Deadline", "Job status", "Match", "J-1 / International", "Official website", "Direct job posting", "Principal / School contact", "Principal email", "Recruiter / Job poster", "Recruiter title", "Recruiter email", "Phone", "Recommended addressee", "Verification", "Last verified", "Application", "Actions"];
  return `<div class="card flush"><div class="table-wrap"><table class="jobs"><thead><tr>${H.map((h, i) => `<th class="${i === 1 ? "sticky" : ""}">${h}</th>`).join("")}</tr></thead><tbody>
  ${items.map((j) => `<tr data-job="${j.id}">
    <td>${freshBadge(j.freshness, j.date_posted)}</td>
    <td class="sticky"><div class="t">${esc(j.job_title)}</div><div class="s">${esc(j.subjects.join(", "))}</div></td>
    <td>${esc(j.employer_name || "—")}</td><td>${esc(j.school || "—")}</td>
    <td class="nowrap">${esc(j.state || "")}${j.city ? " · " + esc(j.city) : ""}</td>
    <td>${esc(j.grade_level || "Not stated")}</td><td class="nowrap">${salary(j)}</td>
    <td class="nowrap">${fmtDate(j.date_posted) || "—"}</td><td>${esc(j.closing_text || fmtDate(j.closing_date) || "Not stated")}</td>
    <td>${badge(STATUS, j.job_status)}</td><td>${matchBox(j.match_score)}</td><td>${badge(J1, j.j1_status)}</td>
    <td>${j.district_website ? `<a target="_blank" rel="noopener" href="${esc(j.district_website)}" onclick="event.stopPropagation()">Official Website ↗</a>` : `<span class="muted small">Not recorded</span>`}</td>
    <td>${j.application_url || j.official_job_url ? `<a target="_blank" rel="noopener" href="${esc(j.application_url || j.official_job_url)}" onclick="event.stopPropagation()">Apply ↗</a>` : "—"}</td>
    <td>${personCell(j.principal)}</td><td>${emailCell(j.principal)}</td>
    <td>${personCell(j.recruiter)}</td><td>${esc(j.recruiter?.title || "—")}</td><td>${emailCell(j.recruiter)}</td>
    <td class="nowrap">${esc(j.phone || "—")}</td>
    <td>${j.recommended_addressee ? `<div class="t">${esc(j.recommended_addressee.contact.full_name)}</div><div class="s">${esc(j.recommended_addressee.salutation)}</div>` : `<span class="muted small">Dear Hiring Committee</span>`}</td>
    <td>${badge(VER, j.verification_status)}<div class="s">${j.source_count} source${j.source_count === 1 ? "" : "s"}</div></td>
    <td class="nowrap small">${fmtDT(j.last_verified)}</td><td>${esc(title(j.application_status))}</td>
    <td class="nowrap"><button class="btn sm" onclick="event.stopPropagation();quickSave(${j.id},this)">${j.is_saved ? "♥ Saved" : "♡ Save"}</button></td>
  </tr>`).join("")}</tbody></table></div></div>`;
}
function jobCards(items) {
  return `<div class="cards-grid">${items.map((j) => `<div class="card jobcard" data-job="${j.id}">
    <div class="row between">${matchBox(j.match_score)}${badge(STATUS, j.job_status)}</div>
    <div class="title">${esc(j.job_title)}</div>
    <div class="small">${esc(j.school || "")}${j.school ? "<br>" : ""}${esc(j.employer_name || "")}<br>${esc([j.city, j.state].filter(Boolean).join(", "))}</div>
    <dl class="kv"><dt>Posted</dt><dd>${freshBadge(j.freshness, j.date_posted)}</dd><dt>Salary</dt><dd>${salary(j)}</dd>
      <dt>J-1</dt><dd>${badge(J1, j.j1_status)}</dd>
      <dt>Principal</dt><dd>${j.principal ? esc(j.principal.full_name || j.principal.title) + " " + badge(VER, j.principal.verification_status) : `<span class="muted">Not found</span>`}</dd>
      <dt>Contact</dt><dd>${j.recruiter ? esc(j.recruiter.full_name || j.recruiter.title || "Listed contact") : `<span class="muted">Not found</span>`}</dd>
      <dt>Email</dt><dd>${emailCell(j.principal?.email ? j.principal : j.recruiter)}</dd></dl>
    <div class="row"><button class="btn sm">VIEW JOB</button>${j.application_url ? `<a class="btn sm primary" target="_blank" rel="noopener" onclick="event.stopPropagation()" href="${esc(j.application_url)}">APPLY</a>` : ""}<button class="btn sm" onclick="event.stopPropagation();quickSave(${j.id},this)">${j.is_saved ? "♥ SAVED" : "SAVE"}</button></div>
  </div>`).join("")}</div>`;
}
window.quickSave = async (id, btn) => { const r = await api(`/api/jobs/${id}/save`, { method: "POST" }); btn.textContent = r.is_saved ? "♥ Saved" : "♡ Save"; toast(r.is_saved ? "Saved" : "Removed from saved"); };
window.doExport = (fmt) => { const q = buildQuery({ states: S.F.states, min_match: S.F.min_match }); location.href = `/api/export/${fmt}?${q}`; };
window.loadResults = loadResults;

// ------------------------------------------------------------------ job detail drawer
function closeDrawer(silent) {
  const drawer = $("#drawer");
  const wasOpen = !drawer.classList.contains("hidden");
  drawer.classList.add("hidden");
  // Only act once: a second call (e.g. two click handlers) must not step back an extra page.
  if (silent || !wasOpen || !location.hash.startsWith("#/job/")) return;
  if (S.openedFromPage) history.back();                 // back to the page the job was opened from
  else location.replace(S.lastPage || "#/jobs");         // opened directly by link: go to the last list page
}
$("#drawer").addEventListener("click", (e) => { if (e.target.dataset.close !== undefined) closeDrawer(); });
$("#modal").addEventListener("click", (e) => { if (e.target.dataset.close !== undefined) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") { if (!$("#modal").classList.contains("hidden")) closeModal(); else if (!$("#drawer").classList.contains("hidden")) closeDrawer(); } });
function openModal(html) { $("#modalPanel").style.width = ""; $("#modalPanel").innerHTML = html; $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); }
window.closeModal = closeModal;

async function openJob(id) {
  const j = await api(`/api/jobs/${id}`);
  S.job = j;
  const a = j.addressee;
  const ev = j.field_evidence || {};
  const evRow = (k, label) => ev[k] ? `<div class="ev"><div class="h"><span>${label}: ${esc(ev[k].value ?? "—")}</span>${badge(VER, ev[k].verification_status)}</div>
     <div class="small muted">${ev[k].source_url ? `<a target="_blank" rel="noopener" href="${esc(ev[k].source_url)}">VIEW SOURCE ↗</a> · ` : ""}${esc(title(ev[k].source_type))} · Checked ${fmtDT(ev[k].verified_at?.replace("Z", ""))}${ev[k].note ? " · " + esc(ev[k].note) : ""}</div></div>` : "";
  const m = j.match || {};
  $("#drawerPanel").innerHTML = `
  <div class="dh"><div class="row between"><div class="row">${matchBox(j.match_score)}<div><h1>${esc(j.job_title)}</h1>
    <div class="small">${esc(j.school || "")}${j.school ? " · " : ""}${esc(j.employer_name || "")} · ${esc([j.city, j.state].filter(Boolean).join(", "))}</div></div></div>
    <button class="iconbtn" aria-label="Close" onclick="closeDrawer()">✕</button></div>
    <div class="row" style="margin-top:8px">${j.is_demo ? `<span class="badge b-warn">DEMO / FICTIONAL DATA</span>` : ""}${j.h1b_employer ? `<a class="badge b-good" href="#/h1b" title="From your H-1B sponsor list (rank #${j.h1b_employer.rank}). Confirm sponsorship for this vacancy with HR.">🛂 H-1B sponsor #${j.h1b_employer.rank}</a>` : ""}${badge(STATUS, j.job_status)}${badge(J1, j.j1_status)}${freshBadge(j.freshness, j.date_posted)}<span class="small muted">${esc(j.status_reason || "")}</span></div>
    <div class="actions">
      <button class="btn primary" onclick="applyNow()">APPLY NOW</button>
      <button class="btn" onclick="saveJob()">${j.is_saved ? "♥ SAVED" : "SAVE JOB"}</button>
      <button class="btn" onclick="addTracker()">${j.application_id ? "IN TRACKER ✓" : "ADD TO TRACKER"}</button>
      <button class="btn" onclick="genDoc('cover-letter')">GENERATE COVER LETTER</button>
      <button class="btn" onclick="genDoc('email')">GENERATE APPLICATION EMAIL</button>
      <button class="btn" onclick="copyContact()">COPY CONTACT</button>
      <button class="btn" onclick="setFollowUp()">SET FOLLOW-UP</button>
      <button class="btn good" onclick="markApplied()">MARK APPLIED</button>
      <button class="btn" onclick="verifyNow(this)">RE-VERIFY NOW</button>
      <button class="btn" onclick="verifyContactFlow()">VERIFY CONTACT</button>
      <button class="btn" onclick="aiFindContacts(this)" title="The app searches the school's and district's official website (staff, directory, administration pages) for the principal's and HR's emails. Only addresses printed on the official page are kept.">FIND EMAIL AUTOMATICALLY</button>
      <button class="btn" onclick="markReapplied()" title="Record that you applied to this job again today. It is listed under Re-applied on the Applications page.">${(j.reapplied_dates || []).length ? `RE-APPLIED ✓ (${j.reapplied_dates.length}×)` : "RE-APPLIED"}</button>
    </div></div>
  <div class="db">
    <div class="two">
      <div class="card"><h3>Position</h3><dl class="kv">
        <dt>Position</dt><dd><b>${esc(j.job_title)}</b></dd><dt>School</dt><dd>${esc(j.school || "Not identified")}</dd>
        <dt>District</dt><dd>${esc(j.employer_name || "—")}</dd><dt>Location</dt><dd>${esc([j.city, j.state].filter(Boolean).join(", ") || "—")}</dd>
        <dt>Salary</dt><dd>${salary(j)}${j.salary_text && j.salary_max ? `<div class="tiny muted">${esc(j.salary_text)}</div>` : ""}</dd>
        <dt>Posting date</dt><dd>${fmtDate(j.date_posted) || "Not stated"}</dd><dt>Deadline</dt><dd>${esc(j.closing_text || fmtDate(j.closing_date) || "Not stated")}</dd>
        <dt>Job ID</dt><dd>${esc(j.external_job_id || "—")}</dd><dt>Grade level</dt><dd>${esc(j.grade_level || "Not stated")}</dd>
        <dt>Type</dt><dd>${esc(j.employment_type || "—")}</dd><dt>Last verified</dt><dd>${fmtDT(j.last_verified)}</dd></dl></div>
      <div class="card"><h3>Recommended addressee</h3>
        <div class="addressee ${a.recommended ? "" : "none"}">${a.recommended ? `<b>${esc(a.contact.full_name)}</b><br>${esc(a.contact.title || "")}<br>${esc(a.contact.organization || "")}<div style="margin:8px 0"><b>${esc(a.salutation)}</b></div>
          <div class="small"><b>WHY THIS PERSON?</b> ${esc(a.why)}</div><div class="small">Confidence: <b>${esc(a.confidence)}</b>${a.evidence_url ? ` · <a target="_blank" rel="noopener" href="${esc(a.evidence_url)}">Evidence ↗</a>` : ""}</div>`
          : `<b>${esc(a.salutation)}</b><div class="small" style="margin-top:6px">${esc(a.why)}</div>`}</div>
        <div class="tiny muted" style="margin-top:8px">Honorifics (Mr./Ms./Dr.) are used only when the source publishes them; otherwise the full name is used.</div></div>
    </div>
    <div class="two">
      <div class="card"><h3>Match score — ${esc(m.label || "")}</h3><div class="breakdown">${(m.breakdown || []).map((b) => `<div class="r"><span>${esc({ subject: "Subject Match", grade: "Grade-Level Match", experience: "Teaching Experience", education: "Education", certification: "Certification Alignment", stem: "STEM/Technology", j1: "International/J-1 Compatibility", location: "Location/Other Requirements" }[b.key])}</span><span class="tr"><i style="width:${(b.points / b.max) * 100}%"></i></span><b>${b.points}/${b.max}</b></div>`).join("")}</div>
        <p class="tiny muted">${esc(m.disclaimer || "")}</p></div>
      <div class="card"><h3>Why you match</h3><ul class="checks">${(m.why || []).map((w) => `<li><span class="ok">✓</span>${esc(w)}</li>`).join("") || "<li class='muted'>—</li>"}</ul>
        <h3 style="margin-top:12px">Gaps / risks</h3><ul class="checks">${(m.gaps || []).map((w) => `<li><span class="no">⚠</span>${esc(w)}</li>`).join("") || "<li class='muted'>None detected in the posting text</li>"}</ul></div>
    </div>
    <div class="card"><h3>Contacts</h3><div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr))">
      ${j.contacts.length ? j.contacts.map((c) => `<div class="contact"><div class="row between"><span class="nm">${esc(c.full_name || "Unnamed contact")}</span>${badge(VER, c.verification_status)}</div>
        <div class="small">${esc(c.title || "")}${c.organization ? " · " + esc(c.organization) : ""}</div>
        <div class="small">Relationship: <b>${esc(title(c.relationship))}</b> · Confidence <b>${esc(c.confidence)}</b></div>
        <div class="small">Email: ${emailLine(c)}
          ${c.has_unconfirmed_email && !deadMailbox(c) ? `<button class="btn sm" style="margin-left:4px" onclick="checkMailbox(${c.id}, this, true)">Check again</button>` : ""}</div>
        ${c.phone ? `<div class="small">Phone: ${esc(c.phone)}</div>` : ""}
        <div class="tiny muted">${c.source_url ? `<a target="_blank" rel="noopener" href="${esc(c.source_url)}">Source ↗</a> · ` : ""}checked ${fmtDT(c.verified_at)}</div>
        ${c.reviewer_note ? `<div class="tiny muted">${esc(c.reviewer_note)}</div>` : ""}
        <div class="row" style="margin-top:6px"><button class="btn sm" onclick="review('${c.contact_type === "PRINCIPAL" ? "principal" : "recruiter"}',true,${c.id})">✓ Approve</button><button class="btn sm danger" onclick="review('${c.contact_type === "PRINCIPAL" ? "principal" : "recruiter"}',false,${c.id})">Reject</button>${c.email ? `<button class="btn sm" onclick="review('email',true,${c.id})">✓ Email</button>` : ""}<button class="btn sm danger" onclick="deleteContact(${c.id}, true)" title="Remove this contact everywhere (can be undone)">Delete</button></div></div>`).join("")
        : `<div class="muted small">No verified principal or recruiter found for this vacancy. Use VERIFY CONTACT to research the school's official staff directory.</div>`}
    </div></div>
    <div class="two">
      <div class="card"><h3>J-1 status</h3><div>${badge(J1, j.j1_status)}</div>
        <div class="evidence" style="margin-top:8px">${(j.j1_evidence || []).map((e) => `<div class="ev"><div class="h"><span>${esc(title(e.kind))}</span><a target="_blank" rel="noopener" href="${esc(e.url)}">VIEW SOURCE ↗</a></div><q>${esc(e.quote)}</q><div class="tiny muted">Checked ${esc((e.checked_at || "").slice(0, 10))}</div></div>`).join("") || `<div class="small muted">No J-1 or international-teacher evidence found for this vacancy or employer. A sponsor operating in the same state is not evidence for this school — confirm with HR.</div>`}</div></div>
      <div class="card"><h3>Official links</h3><dl class="kv">
        <dt>Application</dt><dd>${j.application_url ? `<a target="_blank" rel="noopener" href="${esc(j.application_url)}">${esc(j.application_url)}</a>` : "—"}</dd>
        <dt>Posting</dt><dd>${j.official_job_url ? `<a target="_blank" rel="noopener" href="${esc(j.official_job_url)}">${esc(j.official_job_url)}</a>` : "—"}</dd>
        <dt>District site</dt><dd>${j.district?.website ? `<a target="_blank" rel="noopener" href="${esc(j.district.website)}">${esc(j.district.website)}</a>` : `<span class="muted">Not recorded</span>`}</dd>
        <dt>School site</dt><dd>${j.school_record?.website ? `<a target="_blank" rel="noopener" href="${esc(j.school_record.website)}">${esc(j.school_record.website)}</a>` : `<span class="muted">Not recorded</span>`}</dd></dl>
        <button class="btn sm" style="margin-top:8px" onclick="editOrgUrls()">Add official school / district URLs</button></div>
    </div>
    <div class="card"><h3>Source evidence</h3><div class="evidence">
      ${(() => {
        const d = j.district || {}, we = d.website_evidence;
        if (d.website) return `<div class="ev" style="border-left:4px solid var(--good)"><div class="h"><span>🏫 Official website — ${esc(d.name || j.employer_name || "")}
            ${we && we.verification_status === "VERIFIED" ? `<span class="badge b-good">✓ Verified</span>`
              : we && we.how_found === "Added by you" ? `<span class="badge b-warn">◐ Added by you</span>`
              : we ? `<span class="badge b-warn">◐ Likely — couldn't open it to confirm</span>` : `<span class="badge b-unk">○ Not checked</span>`}</span>
            <a target="_blank" rel="noopener" href="${esc(d.website)}">VISIT WEBSITE ↗</a></div>
          <div class="tiny mono" style="overflow-wrap:anywhere">${esc(d.website)}</div>
          ${we ? `<div class="tiny muted">Found from the ${esc(we.how_found || "")}${we.page_title ? ` · page title “${esc(we.page_title)}”` : ""}${we.check ? ` · ${esc(we.check)}` : ""}${we.checked_at ? ` · checked ${fmtDT(we.checked_at.replace("Z", ""))}` : ""}</div>` : ""}</div>`;
        return `<div class="ev" style="border-left:4px solid var(--warn-dot)"><div class="h"><span>🏫 Official website — not confirmed yet</span></div>
          <div class="small muted">The app looks for it using the district's own published email domain and posting links, and only saves it when the page names the district.</div>
          <div class="row" style="margin-top:6px"><button class="btn sm primary" onclick="findWebsite(this)">Find official website</button><button class="btn sm" onclick="editOrgUrls()">Enter it myself</button></div></div>`;
      })()}
      ${j.sources.map((s) => `<div class="ev"><div class="h"><span>${esc(s.source_name)} ${s.is_official ? `<span class="badge b-good">Official</span>` : `<span class="badge b-info">Discovery</span>`}</span><a target="_blank" rel="noopener" href="${esc(s.url)}">VIEW SOURCE ↗</a></div><div class="tiny muted">${esc(title(s.source_type))} · Tier ${s.tier} · first seen ${fmtDT(s.first_seen)} · last seen ${fmtDT(s.last_seen)}</div><div class="tiny mono" style="overflow-wrap:anywhere">${esc(s.url)}</div></div>`).join("")}
      ${evRow("job_title", "Job title")}${evRow("school", "School")}${evRow("salary", "Salary")}${evRow("deadline", "Deadline")}${evRow("job_status", "Job status")}
    </div></div>
    <div class="card"><h3>Job description</h3><div class="desc">${esc(j.job_description || "Not provided by the source.")}</div>
      ${j.requirements ? `<h3 style="margin-top:12px">Requirements</h3><div class="desc">${esc(j.requirements)}</div>` : ""}
      ${j.certification_requirements ? `<h3 style="margin-top:12px">Certification requirements</h3><div class="desc">${esc(j.certification_requirements)}</div>` : ""}</div>
    <div class="card"><h3>Verification history</h3><div class="scroll"><table class="tbl"><thead><tr><th>When</th><th>Check</th><th>Result</th><th>Detail</th><th>HTTP</th><th>By</th></tr></thead><tbody>
      ${j.verifications.map((v) => `<tr><td class="nowrap">${fmtDT(v.checked_at)}</td><td>${esc(v.check_type)} ${esc(v.target || "")}</td><td>${esc(v.result)}</td><td>${esc(v.detail || "")}${v.url ? ` <a target="_blank" rel="noopener" href="${esc(v.url)}">↗</a>` : ""}</td><td>${esc(v.http_status ?? "")}</td><td>${esc(v.reviewer || "system")}</td></tr>`).join("")}</tbody></table></div></div>
  </div>`;
  $("#drawer").classList.remove("hidden");
}
window.closeDrawer = closeDrawer;
const J = () => S.job;
const reopen = () => openJob(J().id);

window.applyNow = async () => {
  const sc = await api(`/api/jobs/${J().id}/safety-check`);
  const url = J().application_url || J().official_job_url;
  openModal(`<h2>APPLICATION VERIFICATION</h2>
    ${sc.stale ? `<div class="notice warn small">Last verification is older than 24 hours. <button class="btn sm" onclick="closeModal();verifyNow(null).then(applyNow)">Re-verify now</button></div>` : ""}
    <ul class="checks" style="margin:12px 0">${sc.checks.map((c) => `<li><span class="${c.ok ? "ok" : "no"}">${c.ok ? "✓" : "⚠"}</span><span><b>${esc(c.label)}</b><br><span class="small muted">${esc(c.detail)}</span></span></li>`).join("")}
      <li><span class="${sc.j1.ok ? "ok" : "no"}">${sc.j1.ok ? "✓" : "⚠"}</span><span><b>${esc(sc.j1.detail)}</b></span></li></ul>
    <div class="row">${url ? `<a class="btn primary" target="_blank" rel="noopener" href="${esc(url)}" onclick="closeModal()">Open official application ↗</a>` : ""}<button class="btn good" onclick="closeModal();markApplied()">Mark applied</button><button class="btn" onclick="closeModal()">Cancel</button></div>`);
};
window.saveJob = async () => { await api(`/api/jobs/${J().id}/save`, { method: "POST" }); toast("Updated"); reopen(); };
window.addTracker = async () => { await api("/api/applications", { method: "POST", body: { job_id: J().id, status: "SAVED" } }); toast("Added to application tracker"); reopen(); };
window.markApplied = async () => {
  const a = await api(`/api/jobs/${J().id}/mark-applied`, { method: "POST" });
  S.facets = null;
  toast(`Marked applied — moved to Applications and hidden from job lists and alerts. Follow-up ${fmtDate(a.follow_up_date)}`, 5000);
  if (location.hash.startsWith("#/job/")) { closeDrawer(); } else { closeDrawer(true); route(); }  // back to the list, re-rendered without it
};
window.markReapplied = async () => {
  const a = await api(`/api/jobs/${J().id}/re-applied`, { method: "POST" });
  S.facets = null;
  if (a.already_today) toast("Already marked re-applied today — it's in the Re-applied list on the Applications page.", 5000);
  else toastUndo(`Marked re-applied (${a.reapplied_dates.length}×) — added to the Re-applied list on the Applications page`, async () => {
    const today = new Date().toLocaleDateString("en-CA");
    await api(`/api/applications/${a.id}/re-applied`, { method: "PUT", body: { dates: a.reapplied_dates.filter((d) => d !== today) } });
    toast("Re-applied undone");
    if (S.job && S.job.id === a.job_id) reopen();
  });
  reopen();
};
window.aiFindContacts = async (btn) => {
  btn.disabled = true; btn.textContent = "Searching the official website… (up to 1 min)";
  try {
    const r = await api(`/api/jobs/${J().id}/ai-contacts`, { method: "POST" });
    const kept = r.kept || [], rej = r.rejected || [];
    openModal(`<h2>Automatic email search</h2>
      ${kept.length ? `<p class="small">Confirmed on the official website and saved:</p><ul class="checks">${kept.map((k) => `<li><span class="ok">✓</span><span><b>${esc(k.name || "")}</b> (${esc(title(k.role))}) — ${esc(k.email)}<br><a class="tiny" target="_blank" rel="noopener" href="${esc(k.source_url)}">${esc(k.source_url)}</a></span></li>`).join("")}</ul>`
        : `<p class="small">No email could be confirmed on the school's or district's official website.</p>`}
      ${rej.length ? `<details style="margin-top:8px"><summary class="small">Not saved (${rej.length})</summary><ul class="checks">${rej.map((x) => `<li><span class="no">✕</span><span>${esc(x.email || "")} — ${esc(x.why)}</span></li>`).join("")}</ul></details>` : ""}
      ${r.outbox_added ? `<div class="notice small" style="margin-top:8px">📨 ${r.outbox_added} application email${r.outbox_added === 1 ? "" : "s"} prepared in the Outbox for your approval.</div>` : ""}
      <div class="row" style="margin-top:10px"><button class="btn primary" onclick="closeModal();reopen()">Done</button></div>`);
  } catch (e) { toast(e.message, 7000); btn.disabled = false; btn.textContent = "FIND EMAIL AUTOMATICALLY"; }
};
window.verifyNow = async (btn) => { if (btn) { btn.disabled = true; btn.textContent = "Checking…"; } const r = await api(`/api/jobs/${J().id}/verify`, { method: "POST" }); toast(`${r.job_status}: ${r.reason}`, 5000); await reopen(); };
window.copyContact = () => {
  const a = J().addressee;
  const c = a.recommended ? a.contact : (J().contacts[0] || null);
  if (!c) return toast("No verified contact to copy");
  copy([c.full_name, c.title, c.organization, c.email_status === "VERIFIED" ? c.email : null, c.phone].filter(Boolean).join("\n"));
};
window.setFollowUp = async () => {
  let appId = J().application_id;
  if (!appId) appId = (await api("/api/applications", { method: "POST", body: { job_id: J().id, status: "SAVED" } })).id;
  const d = new Date(); let n = 5; while (n) { d.setDate(d.getDate() + 1); if (d.getDay() % 6) n--; }
  openModal(`<h2>Set follow-up</h2><form class="form" id="fu"><label>Follow-up date<input type="date" name="d" value="${d.toISOString().slice(0, 10)}"></label><div class="tiny muted">Suggested: 5 business days after applying.</div><button class="btn primary">Save</button></form>`);
  $("#fu").onsubmit = async (e) => { e.preventDefault(); await api(`/api/applications/${appId}`, { method: "PATCH", body: { follow_up_date: e.target.d.value } }); closeModal(); toast("Follow-up set"); reopen(); };
};
window.genDoc = async (kind) => {
  const r = await api(`/api/jobs/${J().id}/generate/${kind}`, { method: "POST" });
  const isEmail = kind !== "cover-letter";
  const who = `<div class="notice small" style="margin-bottom:10px">${r.greeting_note ? esc(r.greeting_note) : r.addressee.recommended ?`Addressed to ${esc(r.addressee.contact.full_name)} — ${esc(r.addressee.why)}` : "No HIGH-confidence verified contact: addressed to the Hiring Committee (no name invented)."}</div>`;
  if (!isEmail) {
    openModal(`<h2>Cover letter</h2>${who}
      <textarea id="gen" style="min-height:420px">${esc(r.text)}</textarea>
      <div class="tiny muted">Review and edit before sending.</div>
      <div class="row" style="margin-top:10px"><button class="btn primary" onclick="copy($('#gen').value)">Copy</button>
      <button class="btn" onclick="saveGen('${kind}')">Save to application</button><button class="btn" onclick="closeModal()">Close</button></div>`);
    return;
  }
  openModal(`<h2>${kind === "email" ? "Application email" : "Follow-up email"}</h2>${who}
    <form class="form" onsubmit="return false">
      ${r.note && r.mailbox_status && r.mailbox_status !== "EXISTS" ? `<div class="notice warn small"><b>⚠ Address left out:</b> ${esc(r.note)}</div>` : ""}
      <label>To${r.to ? ` <span class="badge b-good">✓ Published by the school</span> ${r.mailbox_status === "EXISTS" ? `<span class="badge b-good">✓ Mailbox confirmed by the school's mail server</span>` : r.mailbox_status === "CATCH_ALL" ? `<span class="badge b-warn">◐ Server accepts all addresses — can't confirm the mailbox</span>` : `<span class="badge b-unk">? Mailbox not confirmed</span>`}` : ` <span class="badge b-unk">○ No usable email — add one only if the school published it</span>`}<input id="genTo" type="email" value="${esc(r.to || "")}" placeholder="recipient@school.org"></label>
      <label>Subject<input id="genSubject" value="${esc(r.subject)}"></label>
      <label>Message<textarea id="gen" style="min-height:360px">${esc(r.body)}</textarea></label>
      <label>Send from Gmail account (optional)<input id="gmailAcct" type="email" value="${esc(store.get("jh_gmail", ""))}" placeholder="yourname@gmail.com — leave blank to use the account already open in your browser"></label>
    </form>
    <div class="tiny muted" style="margin-top:6px">Gmail opens a ready-to-send draft in a new tab. Attach your résumé and documents there before sending — links can't attach files.</div>
    <div class="row" style="margin-top:10px"><button class="btn primary" onclick="openGmail()">Open in Gmail ↗</button>
    <button class="btn" onclick="openMailApp()">Open in mail app</button>
    <button class="btn" onclick="copy('Subject: ' + $('#genSubject').value + '\\n\\n' + $('#gen').value)">Copy</button>
    <button class="btn" onclick="saveGen('${kind}')">Save to application</button><button class="btn" onclick="closeModal()">Close</button></div>`);
};
window.openGmail = () => {
  const acct = $("#gmailAcct").value.trim();
  store.set("jh_gmail", acct);
  const q = { view: "cm", fs: "1", to: $("#genTo").value.trim(), su: $("#genSubject").value, body: $("#gen").value };
  if (acct) q.authuser = acct;
  const qs = Object.entries(q).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");  // %20, never "+"
  window.open(`https://mail.google.com/mail/?${qs}`, "_blank", "noopener");
};
window.openMailApp = () => {
  const to = encodeURIComponent($("#genTo").value.trim());
  location.href = `mailto:${to}?subject=${encodeURIComponent($("#genSubject").value)}&body=${encodeURIComponent($("#gen").value)}`;
};
window.copy = copy;
window.saveGen = async (kind) => {
  let appId = J().application_id;
  if (!appId) appId = (await api("/api/applications", { method: "POST", body: { job_id: J().id, status: "APPLYING" } })).id;
  const body = kind === "cover-letter" ? { cover_letter_text: $("#gen").value, cover_letter_version: "Generated " + new Date().toISOString().slice(0, 10) }
    : { email_text: `To: ${$("#genTo").value}\nSubject: ${$("#genSubject").value}\n\n${$("#gen").value}` };
  await api(`/api/applications/${appId}`, { method: "PATCH", body });
  toast("Saved to application"); closeModal(); reopen();
};
window.review = async (target, approved, contactId) => {
  const note = approved ? "" : prompt("Reason (optional)") || "";
  await api(`/api/jobs/${J().id}/review`, { method: "POST", body: { target, approved, contact_id: contactId, note } });
  toast("Review saved"); reopen();
};
window.findWebsite = async (btn) => {
  btn.disabled = true; btn.textContent = "Searching…";
  try {
    const r = await api(`/api/jobs/${J().id}/find-website`, { method: "POST" });
    if (r.found) { toast(`Official website found: ${r.evidence.url}`, 5000); reopen(); }
    else {
      toast(r.candidates.length ? `Checked ${r.candidates.join(", ")} — no page confirmed it belongs to this district.`
        : "No published email domain or posting link from this district to check. You can enter the website yourself.", 7000);
      btn.disabled = false; btn.textContent = "Find official website";
    }
  } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = "Find official website"; }
};
window.editOrgUrls = () => {
  const j = J();
  openModal(`<h2>Official school & district URLs</h2><p class="small muted">Used for principal discovery and J-1 research. Enter only official .org/.edu/.gov/k12 pages.</p>
  <form class="form" id="org"><label>District website<input name="district_website" value="${esc(j.district?.website || "")}"></label>
  <label>District careers page<input name="district_careers_url" value="${esc(j.district?.careers_url || "")}"></label>
  <label>District HR directory<input name="district_hr_directory_url" value="${esc(j.district?.hr_directory_url || "")}"></label>
  <label>School website<input name="school_website" value="${esc(j.school_record?.website || "")}"></label>
  <label>School staff directory<input name="school_staff_directory_url" value="${esc(j.school_record?.staff_directory_url || "")}"></label>
  <button class="btn primary">Save & research principal</button><div id="orgMsg" class="small"></div></form>`);
  $("#org").onsubmit = async (e) => {
    e.preventDefault(); $("#orgMsg").textContent = "Fetching the school page…";
    const r = await api(`/api/jobs/${j.id}/org-urls`, { method: "POST", body: Object.fromEntries(new FormData(e.target)) });
    $("#orgMsg").textContent = r.principal_found ? `Principal found on the official page: ${r.principal_found.full_name}` : "Saved. No explicitly named principal was found on that page.";
    setTimeout(() => { closeModal(); reopen(); }, 1600);
  };
};
window.verifyContactFlow = () => {
  const j = J();
  const links = [["Job source", j.official_job_url], ["Application", j.application_url], ["School site", j.school_record?.website], ["School directory", j.school_record?.staff_directory_url], ["District HR", j.district?.hr_directory_url], ["District careers", j.district?.careers_url]].filter((x) => x[1]);
  // Search terms like: "Tutt Middle" principal Augusta GA email
  // The school name is quoted without a trailing "School" so pages that write "Tutt Middle" still match;
  // generic names like "Middle School" fall back to the district name.
  const rawSchool = (j.school || "").replace(/\s*[–-]\s*(Middle|High|Elementary) School$/i, "").trim();
  // Fall back to the district when the school is generic ("Middle School") or a campus code ("D H S 002").
  const looksLikeCode = (s) => !s.split(/\s+/).some((w) => /[a-z]{3,}/i.test(w) && !/\d/.test(w));
  const school = (/^(the\s+)?(elementary|middle|high|junior high|secondary)( school)?$/i.test(rawSchool) || !rawSchool || looksLikeCode(rawSchool)
    ? j.employer_name || "" : rawSchool).replace(/\s+School$/i, "").trim();
  const niceCity = (j.city || "").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
  const place = [niceCity, j.state].filter(Boolean).join(" ");
  const g = (terms) => `https://www.google.com/search?q=${encodeURIComponent(terms.replace(/\s+/g, " ").trim())}`;
  const qDirectory = g(`"${school}" staff directory ${place}`);
  const qPrincipalEmail = g(`"${school}" principal ${place} email`);
  openModal(`<h2>VERIFY CONTACT</h2>
    <p class="small muted">Open the official sources, find the person, then record them with the exact page URL. The page is fetched and must contain the name and exact email — guessed addresses are rejected.</p>
    <div class="row" style="margin-bottom:10px">${links.map(([l, u]) => `<a class="btn sm" target="_blank" rel="noopener" href="${esc(u)}">${l} ↗</a>`).join("")}
      <a class="btn sm" target="_blank" rel="noopener" href="${qDirectory}" title="${esc(decodeURIComponent(qDirectory.split("q=")[1]))}">Search for the official staff directory ↗</a>
      <a class="btn sm primary" target="_blank" rel="noopener" href="${qPrincipalEmail}" title="${esc(decodeURIComponent(qPrincipalEmail.split("q=")[1]))}">Search principal email ↗</a></div>
    <div class="tiny muted" style="margin:-4px 0 10px">Searching for: <b>${esc(decodeURIComponent(qPrincipalEmail.split("q=")[1]))}</b>. Use an address only if it appears on the school's or district's own website, then paste that page's link below.</div>
    <form class="form" id="vc"><div class="cols"><label>Full name<input name="full_name"></label><label>Title<input name="title" placeholder="Principal / Talent Partner / HR Director"></label></div>
      <div class="cols"><label>Email (exactly as published)<input name="email" type="email"></label><label>Phone<input name="phone"></label></div>
      <label>Official source URL (required)<input name="source_url" required type="url"></label>
      <div class="cols"><label>Relationship<select name="relationship">${["SCHOOL_PRINCIPAL", "JOB_POSTER", "VACANCY_CONTACT", "HIRING_MANAGER", "CAMPUS_ADMINISTRATOR", "REGIONAL_RECRUITER", "DISTRICT_RECRUITER", "INTERNATIONAL_RECRUITER", "VISA_COORDINATOR", "HR_ADMINISTRATOR", "GENERAL_HR_ONLY"].map((r) => `<option>${r}</option>`).join("")}</select></label>
      <label>Confidence<select name="confidence"><option>MEDIUM</option><option value="HIGH">HIGH (source ties this person to this vacancy)</option><option>LOW</option></select></label></div>
      <label>Evidence (quote from the page)<input name="evidence_text"></label>
      <label class="row" style="font-weight:500"><input type="checkbox" name="confirm_on_source" checked style="width:auto"> Confirm automatically on the source page</label>
      <button class="btn primary">Save contact</button><div id="vcMsg" class="small"></div></form>`);
  $("#vc").onsubmit = async (e) => {
    e.preventDefault();
    const fd = Object.fromEntries(new FormData(e.target));
    fd.confirm_on_source = !!e.target.confirm_on_source.checked;
    for (const k of ["full_name", "title", "email", "phone", "evidence_text"]) if (!fd[k]) delete fd[k];
    try { await api(`/api/jobs/${j.id}/contacts`, { method: "POST", body: fd }); closeModal(); toast("Contact recorded"); reopen(); }
    catch (err) { $("#vcMsg").textContent = err.message; $("#vcMsg").style.color = "var(--bad)"; }
  };
};

// ------------------------------------------------------------------ USA map
async function viewMap() {
  const f = await api(`/api/jobs/facets?demo=${S.demo}`);
  S.facets = f;
  const counts = f.by_state;
  const max = Math.max(1, ...Object.values(counts).filter((v, i) => Object.keys(counts)[i] !== "?"));
  const level = (n) => !n ? 0 : Math.min(5, Math.ceil((n / max) * 5));
  const tiles = f.states.filter((s) => s.tile).map((s) => {
    const n = counts[s.code] || 0, j = f.j1_activity_by_state[s.code] || 0;
    return `<div class="tile l${level(n)}" style="grid-column:${s.tile[0] + 1};grid-row:${s.tile[1] + 1}" title="${esc(s.name)}: ${n} active Math job${n === 1 ? "" : "s"}${j ? `, ${j} with J-1/international evidence` : ""}" onclick="applyQuickFilter('${s.code}')">
      <span class="st">${s.code}</span><span class="n">${n || ""}</span>${j ? `<span class="j1">J1 ${j}</span>` : ""}</div>`;
  }).join("");
  const ranked = Object.entries(counts).filter(([k]) => k !== "?").sort((a, b) => b[1] - a[1]);
  $("#view").innerHTML = `${demoBanner()}<div class="page-head"><div><h1>USA Map</h1><p>Active Mathematics vacancies stored from actual scans, by state. Click a state to filter results.</p></div></div>
  <div class="map-wrap"><div class="card"><div class="tilemap">${tiles}</div>
    <div class="legend">Fewer <span class="sw" style="background:var(--seq-0)"></span><span class="sw" style="background:var(--seq-1)"></span><span class="sw" style="background:var(--seq-2)"></span><span class="sw" style="background:var(--seq-3)"></span><span class="sw" style="background:var(--seq-4)"></span><span class="sw" style="background:var(--seq-5)"></span> More · <span class="badge b-good">J1 n</span> = jobs with J-1 / international evidence (from collected data)</div>
    <p class="tiny muted">Counts reflect only sources scanned so far; a low number can mean limited coverage, not a lack of vacancies. States are not ranked by assumption.</p></div>
    <div class="card"><h3>Active Math jobs by state</h3><div class="scroll" style="max-height:520px"><table class="tbl"><thead><tr><th>State</th><th>Jobs</th><th>J-1 / Intl.</th></tr></thead><tbody>
    ${ranked.map(([k, v]) => `<tr style="cursor:pointer" onclick="applyQuickFilter('${k}')"><td>${esc(k)}</td><td>${v}</td><td>${f.j1_activity_by_state[k] || 0}</td></tr>`).join("") || `<tr><td colspan="3" class="muted">No data yet — run a scan.</td></tr>`}</tbody></table></div></div></div>`;
}

// ------------------------------------------------------------------ J-1 page
async function viewJ1() {
  $("#view").innerHTML = `<div class="tabs"><button class="on" data-t="jobs">J-1 Jobs</button><button data-t="sponsors">Sponsor database</button><button data-t="districts">District research</button></div><div id="j1body"></div>`;
  const tabs = { jobs: () => viewJobs("j1", $("#j1body")), sponsors: j1Sponsors, districts: j1Districts };
  $$(".tabs button").forEach((b) => (b.onclick = () => { $$(".tabs button").forEach((x) => x.classList.toggle("on", x === b)); tabs[b.dataset.t](); }));
  await tabs.jobs();
}
async function j1Sponsors() {
  const rows = await api("/api/j1/programs");
  const TYPES = { DESIGNATED_J1_SPONSOR: "Designated J-1 Sponsor", RECRUITMENT_AGENCY: "Recruitment / Placement Agency", DISTRICT_EMPLOYER: "School District / Employer" };
  $("#j1body").innerHTML = `<div class="page-head"><div><h1>J-1 Sponsor Database</h1><p>Designated sponsors, recruitment agencies and employers are kept separate. A sponsor in a state is never treated as evidence that a particular school accepts J-1 teachers.</p></div>
    <div class="row"><button class="btn" onclick="addProgram()">Add record</button><label class="btn">Import State Dept CSV<input type="file" accept=".csv" hidden onchange="importDos(this)"></label></div></div>
    <div class="notice small" style="margin-bottom:12px">Full official list: open the <a target="_blank" rel="noopener" href="https://j1visa.state.gov/participants/how-to-apply/sponsor-search/?program=Teacher">BridgeUSA sponsor search ↗</a>, choose category <b>Teacher</b>, click <b>CSV</b>, and import the file here.</div>
    ${Object.entries(TYPES).map(([t, l]) => `<div class="card flush" style="margin-bottom:12px"><div style="padding:12px 14px"><h2>${l}</h2></div><div class="scroll"><table class="tbl"><thead><tr><th>Organization</th><th>Location / states</th><th>Subjects</th><th>Contact</th><th>Website / program</th><th>Fees</th><th>Verification</th><th>Source</th></tr></thead><tbody>
      ${rows.filter((r) => r.organization_type === t).map((r) => `<tr><td><b>${esc(r.organization)}</b>${r.notes ? `<div class="tiny muted">${esc(r.notes)}</div>` : ""}</td><td>${esc(r.address || "")}${r.states_served?.length ? `<div class="small">Serves: ${esc(r.states_served.join(", "))}</div>` : ""}</td><td>${esc((r.subjects_recruited || []).join(", ") || "—")}</td>
      <td>${esc(r.contact_person || "")}<div>${esc(r.email || "")}</div><div>${esc(r.phone || "")}</div></td>
      <td>${r.official_website ? `<a target="_blank" rel="noopener" href="${esc(r.official_website)}">${esc(r.official_website)}</a>` : ""}${r.teacher_program_url ? `<div><a target="_blank" rel="noopener" href="${esc(r.teacher_program_url)}">Teacher program ↗</a></div>` : ""}</td>
      <td>${esc(r.fees_if_public || "Not published")}</td><td>${badge(VER, r.verification_status)}<div class="tiny muted">${fmtDate(r.last_verified)}</div></td>
      <td><a target="_blank" rel="noopener" href="${esc(r.source_url)}">View ↗</a></td></tr>`).join("") || `<tr><td colspan="8" class="muted">No records yet.</td></tr>`}</tbody></table></div></div>`).join("")}`;
}
window.importDos = async (inp) => { const fd = new FormData(); fd.append("file", inp.files[0]); const r = await api("/api/j1/programs/import-state-dept-csv", { method: "POST", body: fd }); toast(`Imported ${r.added} Teacher-category sponsors`); j1Sponsors(); };
window.addProgram = async () => {
  const ds = await api("/api/districts");
  openModal(`<h2>Add J-1 / international record</h2><form class="form" id="pf">
    <label>Organization<input name="organization" required></label>
    <label>Type<select name="organization_type"><option value="DESIGNATED_J1_SPONSOR">Designated J-1 sponsor</option><option value="RECRUITMENT_AGENCY">Recruitment / placement agency</option><option value="DISTRICT_EMPLOYER">School district / employer</option></select></label>
    <label>Linked district (for employers)<select name="district_id"><option value="">—</option>${ds.map((d) => `<option value="${d.id}">${esc(d.name)} (${esc(d.state || "")})</option>`).join("")}</select></label>
    <div class="cols"><label>Official website<input name="official_website"></label><label>Teacher program URL<input name="teacher_program_url"></label></div>
    <div class="cols"><label>States served (comma)<input name="states_served"></label><label>Subjects recruited (comma)<input name="subjects_recruited"></label></div>
    <div class="cols"><label>Contact person<input name="contact_person"></label><label>Email (as published)<input name="email"></label></div>
    <div class="cols"><label>Phone<input name="phone"></label><label>Fees (if public)<input name="fees_if_public"></label></div>
    <label>Evidence source URL (required)<input name="source_url" type="url" required></label>
    <label>Evidence quote<textarea name="evidence_quote" style="min-height:60px"></textarea></label>
    <label>Verification<select name="verification_status"><option value="VERIFIED">Verified on official source</option><option value="PARTIALLY_VERIFIED">Partially verified</option></select></label>
    <button class="btn primary">Save</button></form>`);
  $("#pf").onsubmit = async (e) => {
    e.preventDefault(); const b = Object.fromEntries(new FormData(e.target));
    b.states_served = b.states_served ? b.states_served.split(",").map((s) => s.trim()) : [];
    b.subjects_recruited = b.subjects_recruited ? b.subjects_recruited.split(",").map((s) => s.trim()) : [];
    b.district_id = b.district_id ? +b.district_id : null;
    await api("/api/j1/programs", { method: "POST", body: b }); closeModal(); toast("Saved. Run CHECK J-1 STATUS to apply it to jobs."); j1Sponsors();
  };
};
async function j1Districts() {
  const ds = await api("/api/districts");
  $("#j1body").innerHTML = `<div class="page-head"><div><h1>District J-1 research</h1><p>Add each district's official website or careers page; CHECK J-1 STATUS searches those official pages for international-teacher / J-1 evidence and stores quotes.</p></div><button class="btn primary" onclick="startScan('J1')">CHECK J-1 STATUS</button></div>
  <div class="card flush"><div class="scroll" style="max-height:640px"><table class="tbl"><thead><tr><th>District</th><th>State</th><th>Official website</th><th>Careers page</th><th>J-1 status</th><th>Evidence</th><th></th></tr></thead><tbody>
  ${ds.map((d) => `<tr><td>${esc(d.name)}</td><td>${esc(d.state || "")}</td><td><input data-d="${d.id}" data-k="website" value="${esc(d.website || "")}" placeholder="https://…" style="width:220px"></td><td><input data-d="${d.id}" data-k="careers_url" value="${esc(d.careers_url || "")}" placeholder="https://…" style="width:220px"></td>
  <td>${badge(J1, d.j1_status)}</td><td class="small">${(d.j1_evidence || []).slice(0, 2).map((e) => `<a target="_blank" rel="noopener" href="${esc(e.url)}">${esc(title(e.kind))} ↗</a>`).join("<br>")}</td><td><button class="btn sm" onclick="saveDistrict(${d.id})">Save</button></td></tr>`).join("")}</tbody></table></div></div>`;
}
window.saveDistrict = async (id) => { const body = {}; $$(`[data-d="${id}"]`).forEach((i) => (body[i.dataset.k] = i.value.trim())); await api(`/api/districts/${id}`, { method: "PATCH", body }); toast("Saved"); };

// ------------------------------------------------------------------ applications
const APPLIED_STAGES_UI = ["APPLIED", "FOLLOW_UP", "INTERVIEW", "SECOND_INTERVIEW", "OFFER", "HIRED", "REJECTED", "WITHDRAWN", "POSITION_CLOSED"];
const STAGE_LABEL = { APPLIED: "Applied", FOLLOW_UP: "Applied", INTERVIEW: "Interview", SECOND_INTERVIEW: "Interview", OFFER: "Interview",
  HIRED: "Hired", REJECTED: "Rejected", WITHDRAWN: "Withdrawn", POSITION_CLOSED: "Position closed" };
async function viewApplications() {
  const d = await api("/api/applications");
  S.apps = d;
  const q = store.get("jh_app_search", "");
  $("#view").innerHTML = `<div class="page-head"><div><h1>Applications</h1><p>Every job you mark applied is added here automatically.</p></div>
    <div class="row"><button class="btn" onclick="manualApp()">Add application manually</button><button class="btn sm" onclick="showDeleted()">Recently deleted</button><button class="btn sm" onclick="location.href='/api/export/xlsx?tracked_only=true'">Export (Excel)</button></div></div>
    <div class="toolbar"><div class="search-box"><span aria-hidden="true">⌕</span><input id="appSearch" placeholder="Search employer, email, school, state or job…" value="${esc(q)}" autocomplete="off"></div>
      <button class="btn primary" id="appSearchBtn">Search</button><button class="btn" id="appClear">Clear</button>
      <label class="small muted row" style="gap:6px">Posting<select id="appPosting">${[["", "All"], ["open", "Still posted"], ["closed", "Closed / no longer posted"]].map(([v, l]) => `<option value="${v}" ${store.get("jh_app_posting", "") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <button class="btn" id="appCheckClosed" title="Re-checks each applied job's posting (e.g. on SchoolSpring) and marks the ones that are closed or can no longer be viewed">Check which postings closed</button>
      <button class="btn" id="appReBtn" title="Jobs you applied to again">🔁 Re-applied <span class="badge b-info" id="reCount">0</span></button>
      <span class="grow"></span><span class="small muted" id="appCount"></span></div>
    <div class="card flush" style="margin-bottom:14px"><div class="scroll" style="max-height:calc(100vh - 470px);min-height:220px" id="appTable"></div></div>
    <h3>Stages</h3><div id="appBoard"></div>`;
  const run = () => { store.set("jh_app_search", $("#appSearch").value); renderApplications(); };
  $("#appSearchBtn").onclick = run;
  $("#appSearch").addEventListener("keydown", (e) => { if (e.key === "Enter") run(); });
  let t; $("#appSearch").addEventListener("input", () => { clearTimeout(t); t = setTimeout(run, 250); });
  $("#appClear").onclick = () => { $("#appSearch").value = ""; run(); };
  $("#appPosting").onchange = () => { store.set("jh_app_posting", $("#appPosting").value); renderApplications(); };
  $("#appCheckClosed").onclick = async () => {
    try {
      const r = await api("/api/scans", { method: "POST", body: { kind: "CLOSED_CHECK", tracked_only: true } });
      if (r.dispatched) { toast("Closed-posting check started in the cloud — refresh this page in about 15 minutes.", 7000); return; }
      S.scanRun = r.run_id; pollScan();
      toast("Checking your applied jobs' postings — closed ones will be marked Closed when the check finishes (a few minutes).", 6000);
    } catch (e) { toast(e.message); }
  };
  $("#appReBtn").onclick = () => {
    openModal(`<div class="row between"><h2 style="margin:0">🔁 Re-applied <span class="badge b-info" id="reModalCount">0</span></h2><button class="iconbtn" aria-label="Close" onclick="closeModal()">✕</button></div>
      <p class="small muted" style="margin:6px 0 10px">Jobs you applied to again — click RE-APPLIED in a job's view (next to VERIFY CONTACT) to add one.</p>
      <div class="scroll" style="max-height:65vh" id="reTable"></div>`);
    $("#modalPanel").style.width = "min(1240px, 100%)";
    renderReapplied();
  };
  renderApplications();
}
// Re-applied list (shown in a modal from the Applications page): every application with a re-applied date, latest first.
function renderReapplied() {
  const box = $("#reTable");
  if (!box) return;
  const re = S.reList || [], q = (($("#appSearch") || {}).value || "").trim();
  if ($("#reModalCount")) $("#reModalCount").textContent = re.length;
  box.innerHTML = `<table class="tbl apptbl"><thead><tr><th>#</th><th>Employer Name</th><th>Email</th><th>School</th><th>State</th><th>Job Re-applied For</th><th>First Applied</th><th>Re-applied On</th><th></th></tr></thead><tbody>
    ${re.map((a, i) => `<tr>
      <td class="muted">${i + 1}</td>
      <td><b>${esc(a.employer_name || "—")}</b></td>
      <td>${a.email ? `<a href="mailto:${esc(a.email)}">${esc(a.email)}</a>` : `<span class="muted small">No confirmed email</span>`}</td>
      <td>${esc(a.school || "—")}</td>
      <td>${a.state ? `<span class="badge b-info">${esc(a.state)}</span>` : "—"}</td>
      <td>${a.job_id ? `<a href="#/job/${a.job_id}" onclick="closeModal()">${esc(a.position || "Untitled")}</a>` : esc(a.position || "Untitled")}${a.job_status === "CLOSED" ? ` <span class="badge b-bad">Closed</span>` : ""}</td>
      <td class="nowrap">${a.date_applied ? fmtDate(a.date_applied) : `<span class="muted small">Not recorded</span>`}</td>
      <td class="nowrap"><b>${fmtDate(a.reapplied_dates.slice(-1)[0])}</b>${a.reapplied_dates.length > 1 ? `<div class="tiny muted" title="${esc(a.reapplied_dates.map(fmtDate).join(", "))}">${a.reapplied_dates.length}× · earlier: ${esc(a.reapplied_dates.slice(0, -1).map(fmtDate).join(", "))}</div>` : ""}</td>
      <td class="nowrap"><button class="btn sm" onclick="openAppById(${a.id})">Open</button> <button class="btn sm" onclick="undoReapply(${a.id})" title="Remove the latest re-applied date">Undo last</button> <button class="btn sm danger" onclick="removeReapply(${a.id})" title="Take this job out of the Re-applied list (the application itself stays)">Remove</button></td></tr>`).join("")
      || `<tr><td colspan="9" class="muted" style="padding:16px">${q ? `No re-applied jobs match “${esc(q)}”.` : "No re-applied jobs yet. Open a job and click RE-APPLIED next to VERIFY CONTACT."}</td></tr>`}</tbody></table>`;
}
function renderApplications() {
  const d = S.apps;
  const q = ($("#appSearch").value || "").trim().toLowerCase();
  const today = new Date().toISOString().slice(0, 10);
  const all = d.items.filter((a) => S.demo || !a.is_demo);
  const match = (a) => !q || [a.employer_name, a.email, a.school, a.state, a.position, STAGE_LABEL[a.application_status]].join(" ").toLowerCase().includes(q);
  const items = all.filter(match);
  const posting = $("#appPosting") ? $("#appPosting").value : "";
  const appliedAll = items.filter((a) => APPLIED_STAGES_UI.includes(a.application_status));
  const closedN = appliedAll.filter((a) => a.job_status === "CLOSED").length;
  const applied = appliedAll.filter((a) => !posting || (posting === "closed") === (a.job_status === "CLOSED"));
  $("#appCount").innerHTML = `${applied.length} applied job${applied.length === 1 ? "" : "s"}${q ? ` matching “${esc($("#appSearch").value.trim())}”` : ""}${closedN ? ` · <span style="color:var(--bad);font-weight:600">${closedN} closed</span>` : ""}`;
  $("#appTable").innerHTML = `<table class="tbl apptbl"><thead><tr><th>#</th><th>Employer Name</th><th>Email</th><th>School</th><th>State</th><th>Job Applied For</th><th>Date Applied</th><th>Status</th><th></th></tr></thead><tbody>
    ${applied.map((a, i) => `<tr data-app="${a.id}" draggable="true" title="Drag this row onto a stage to move it" class="drag-row${a.job_status === "CLOSED" ? " closed-row" : ""}">
      <td class="muted nowrap"><span class="grip" aria-hidden="true">⠿</span> ${i + 1}</td>
      <td><b>${esc(a.employer_name || "—")}</b></td>
      <td>${a.email ? `<a href="mailto:${esc(a.email)}">${esc(a.email)}</a>` : `<span class="muted small">No confirmed email</span>`}</td>
      <td>${esc(a.school || "—")}</td>
      <td>${a.state ? `<span class="badge b-info">${esc(a.state)}</span>` : "—"}</td>
      <td>${a.job_id ? `<a href="#/job/${a.job_id}">${esc(a.position || "Untitled")}</a>` : esc(a.position || "Untitled")}${a.job_status === "CLOSED" ? ` <span class="badge b-bad" title="${esc((a.job_status_reason || "Posting closed") + (a.job_last_verified ? " · checked " + fmtDT(a.job_last_verified) : ""))}">✕ Closed — no longer posted</span>` : ""}</td>
      <td class="nowrap">${a.date_applied ? fmtDate(a.date_applied) : "—"}${a.follow_up_date && a.follow_up_date <= today && ["APPLIED", "FOLLOW_UP"].includes(a.application_status) ? `<div class="tiny" style="color:var(--bad);font-weight:600">Follow-up due</div>` : ""}</td>
      <td class="nowrap">${esc(STAGE_LABEL[a.application_status] || title(a.application_status))}${(a.reapplied_dates || []).length ? ` <span class="badge b-info" title="Re-applied ${esc(a.reapplied_dates.map(fmtDate).join(", "))}">🔁 ${a.reapplied_dates.length}×</span>` : ""}${(() => {
        const next = (a.interviews || []).find((i) => !i.is_past) || (a.interviews || []).slice(-1)[0];
        return next ? `<div class="tiny" style="color:var(--accent-ink);font-weight:600" title="Philippine time: ${esc(next.ph_local)}">📅 ${esc(next.us_local)}</div>`
          : (["INTERVIEW", "SECOND_INTERVIEW", "OFFER"].includes(a.application_status) ? `<div class="tiny"><button class="linkbtn" style="color:var(--bad);font-weight:600" onclick="addInterview(${a.id})">Add interview time</button></div>` : "");
      })()}</td>
      <td class="nowrap"><button class="btn sm" onclick="openAppById(${a.id})">Open</button> <button class="btn sm danger" onclick="deleteApp(${a.id})">Delete</button></td></tr>`).join("")
      || `<tr><td colspan="9" class="muted" style="padding:20px">${q ? "No applications match your search." : "No applications yet. Click MARK APPLIED on a job and it appears here."}</td></tr>`}</tbody></table>`;
  S.reList = items.filter((a) => (a.reapplied_dates || []).length)
    .sort((x, y) => y.reapplied_dates.slice(-1)[0].localeCompare(x.reapplied_dates.slice(-1)[0]));
  $("#reCount").textContent = S.reList.length;
  renderReapplied();   // refreshes the Re-applied modal when it is open
  // Stage board (Applied, Interview, Hired + outcomes); older stages are grouped into these.
  const col = (st) => {
    const list = items.filter((a) => (d.groups[st] || [st]).includes(a.application_status));
    return `<div class="col${list.length ? "" : " empty-col"}" data-st="${st}"><h4><span>${title(st)}</span><span class="cnt">${list.length}</span></h4><div class="col-body">${list.map((a) => {
      const due = a.follow_up_date && a.follow_up_date <= today && ["APPLIED", "FOLLOW_UP"].includes(a.application_status);
      const tip = [a.position, [a.school, a.employer_name].filter(Boolean).join(" · "), a.state, a.email || ""].filter(Boolean).join("\n");
      return `<a class="applink${a.job_status === "CLOSED" ? " closed" : ""}" href="javascript:void 0" draggable="true" data-app="${a.id}" title="${esc(tip)}">
        ${due ? `<span class="due-dot" aria-label="Follow-up due"></span>` : ""}<span class="al-body"><span class="al-t">${esc(a.position || "Untitled")}</span>${a.employer_name ? `<span class="al-e">${esc(a.employer_name)}</span>` : ""}</span>${a.state ? `<span class="al-m">${esc(a.state)}</span>` : ""}</a>`;
    }).join("") || `<div class="col-empty">Drop here</div>`}</div></div>`;
  };
  // Applied jobs are already listed in the table above, so the board shows only the later stages and outcomes
  // (the drag-and-drop bar still offers "Applied" to move a job back).
  $("#appBoard").innerHTML = `<div class="kanban small-board">${[...d.stages, ...d.outcomes].filter((st) => st !== "APPLIED").map(col).join("")}</div>`;
  $$("#appBoard .applink").forEach((c) => {
    c.ondragstart = (e) => e.dataTransfer.setData("text/plain", c.dataset.app);
    c.onclick = (e) => { e.preventDefault(); openAppById(+c.dataset.app); };
  });
  const moveTo = async (id, st) => {
    const before = S.apps.items.find((x) => x.id === id);
    if (!before || (d.groups[st] || [st]).includes(before.application_status)) return;
    await api(`/api/applications/${id}`, { method: "PATCH", body: { application_status: st } });
    toast(`Moved to ${title(st)}: ${before.position || ""}${before.employer_name ? " — " + before.employer_name : ""}`);
    await viewApplications();
    promptInterviewIfNeeded(id, st, (before.interviews || []).length);
  };
  const dropTarget = (el, st) => {
    el.ondragover = (e) => { e.preventDefault(); el.classList.add("drop"); };
    el.ondragleave = () => el.classList.remove("drop");
    el.ondrop = (e) => { e.preventDefault(); el.classList.remove("drop"); const id = +e.dataTransfer.getData("text/plain"); if (id) moveTo(id, st); };
  };
  $$("#appBoard .col").forEach((c) => dropTarget(c, c.dataset.st));
  // Rows in the table can be dragged too; while dragging, a bar with the stages appears at the bottom of the screen.
  let bar = $("#stageDropBar");
  if (!bar) { bar = document.createElement("div"); bar.id = "stageDropBar"; document.body.appendChild(bar); }
  bar.innerHTML = `<span class="sdb-label">Drop on a stage:</span>${[...d.stages, ...d.outcomes].map((st) => `<div class="sdb-zone" data-st="${st}">${esc(title(st))}</div>`).join("")}`;
  $$("#stageDropBar .sdb-zone").forEach((z) => dropTarget(z, z.dataset.st));
  const showBar = (on) => bar.classList.toggle("show", on);
  $$("#appTable tr.drag-row").forEach((r) => {
    r.ondragstart = (e) => { e.dataTransfer.setData("text/plain", r.dataset.app); e.dataTransfer.effectAllowed = "move"; r.classList.add("dragging"); showBar(true); };
    r.ondragend = () => { r.classList.remove("dragging"); showBar(false); };
  });
  $$("#appBoard .applink").forEach((c) => { c.addEventListener("dragstart", () => showBar(true)); c.addEventListener("dragend", () => showBar(false)); });
}
window.openAppById = (id) => openApp(S.apps.items.find((a) => a.id === id));
const setReapplied = (id, dates) => api(`/api/applications/${id}/re-applied`, { method: "PUT", body: { dates } });
window.undoReapply = async (id) => {
  const a = S.apps.items.find((x) => x.id === id), before = [...a.reapplied_dates];
  await setReapplied(id, before.slice(0, -1));
  toastUndo(`Removed re-applied date ${fmtDate(before.slice(-1)[0])}: ${a.position || ""}`, async () => { await setReapplied(id, before); toast("Restored"); viewApplications(); });
  viewApplications();
};
window.removeReapply = async (id) => {
  const a = S.apps.items.find((x) => x.id === id), before = [...a.reapplied_dates];
  await setReapplied(id, []);
  toastUndo(`Removed from Re-applied: ${a.position || ""}`, async () => { await setReapplied(id, before); toast("Restored"); viewApplications(); });
  viewApplications();
};
window.deleteApp = async (id) => {
  const a = S.apps.items.find((x) => x.id === id);
  await api(`/api/applications/${id}`, { method: "DELETE" });
  S.facets = null;
  toastUndo(`Deleted: ${a ? a.position : "application"}${a && a.employer_name ? " — " + a.employer_name : ""}`, async () => {
    await api(`/api/applications/${id}/restore`, { method: "POST" });
    toast("Restored");
    if ((location.hash || "").includes("applications")) viewApplications();
  });
  viewApplications();
};
window.showDeleted = async () => {
  const rows = await api("/api/applications/deleted");
  openModal(`<h2>Recently deleted</h2><p class="small muted">Deleted applications can be restored here at any time.</p>
    <table class="tbl"><thead><tr><th>Job</th><th>Employer</th><th>State</th><th>Deleted</th><th></th></tr></thead><tbody>
    ${rows.map((a) => `<tr><td>${esc(a.position || "")}</td><td>${esc(a.employer_name || "")}</td><td>${esc(a.state || "")}</td><td class="nowrap small">${fmtDT(a.deleted_at)}</td>
      <td><button class="btn sm" onclick="restoreApp(${a.id}, this)">Undo delete</button></td></tr>`).join("") || `<tr><td colspan="5" class="muted">Nothing deleted.</td></tr>`}</tbody></table>`);
};
window.restoreApp = async (id, btn) => { await api(`/api/applications/${id}/restore`, { method: "POST" }); btn.closest("tr").remove(); toast("Restored"); viewApplications(); };
function toastUndo(msg, onUndo) {
  const t = $("#toast");
  t.innerHTML = `<span>${esc(msg)}</span> <button class="undo-btn" id="undoBtn">UNDO</button>`;
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), 10000);
  $("#undoBtn").onclick = async () => { clearTimeout(t._h); t.classList.add("hidden"); await onUndo(); };
}
window.manualApp = () => {
  openModal(`<h2>Add application</h2><form class="form" id="ma"><label>Job applied for<input name="position" required></label>
    <div class="cols"><label>Employer name<input name="district"></label><label>School<input name="school"></label></div>
    <div class="cols"><label>State<input name="state" maxlength="2"></label><label>Email<input name="contact_email" type="email"></label></div>
    <label>Job URL<input name="job_url"></label><button class="btn primary">Add</button></form>`);
  $("#ma").onsubmit = async (e) => { e.preventDefault(); const b = Object.fromEntries(new FormData(e.target)); b.status = "APPLIED"; if (b.state) b.state = b.state.toUpperCase(); await api("/api/applications", { method: "POST", body: b }); closeModal(); viewApplications(); };
};
async function openApp(a) {
  const d = await api("/api/applications");
  a = d.items.find((x) => x.id === a.id);
  const all = [...d.stages, ...d.outcomes];
  openModal(`<div class="row between"><h2>${esc(a.position)}</h2>${a.job_id ? `<button class="btn sm" onclick="closeModal();location.hash='#/job/${a.job_id}'">Open job</button>` : ""}</div>
  <div class="small muted" style="margin-bottom:10px">${esc([a.school, a.district, a.state].filter(Boolean).join(" · "))}</div>
  <form class="form" id="af"><div class="cols"><label>Status<select name="application_status">${all.map((s) => `<option value="${s}" ${a.application_status === s ? "selected" : ""}>${title(s)}</option>`).join("")}</select></label>
    <label>Date applied<input type="date" name="date_applied" value="${a.date_applied || ""}"></label></div>
    <div class="cols"><label>Follow-up date<input type="date" name="follow_up_date" value="${a.follow_up_date || ""}"></label><label>Visa status<input name="visa_status" value="${esc(a.visa_status || "")}"></label></div>
    <div class="cols"><label>Contact person<input name="contact_person" value="${esc(a.contact_person || "")}"></label><label>Contact email<input name="contact_email" value="${esc(a.contact_email || "")}"></label></div>
    <div class="cols"><label>Résumé version<input name="resume_version" value="${esc(a.resume_version || "")}"></label><label>Cover letter version<input name="cover_letter_version" value="${esc(a.cover_letter_version || "")}"></label></div>
    <div class="cols"><label>Documents sent (comma)<input name="documents_sent" value="${esc((a.documents_sent || []).join(", "))}"></label><label>Offer salary<input name="offer_salary" value="${esc(a.offer_salary || "")}"></label></div>
    <label class="row" style="font-weight:500"><input type="checkbox" name="response_received" ${a.response_received ? "checked" : ""} style="width:auto"> Response received</label>
    <label>Notes<textarea name="notes">${esc(a.notes || "")}</textarea></label>
    <div class="row"><button class="btn primary">Save</button>${a.job_id ? `<button type="button" class="btn" onclick="followUpEmail(${a.job_id})">Generate follow-up email</button>` : ""}<button type="button" class="btn" onclick="logEvent(${a.id},'FIRST_EMAIL')">Log first email</button><button type="button" class="btn" onclick="logEvent(${a.id},'FOLLOW_UP')">Log follow-up</button><button type="button" class="btn" onclick="logEvent(${a.id},'RESPONSE')">Log response</button></div></form>
  <h3 style="margin-top:14px">Interviews</h3>
  ${(a.interviews || []).length ? `<ul class="checks">${a.interviews.map((i) => `<li><span>📅</span><span><b>${esc(i.round_label || "Interview")}</b> — ${esc(i.us_local)} <span class="muted">(${esc(i.ph_local)})</span>${i.interviewer ? ` · ${esc(i.interviewer)}` : ""}</span></li>`).join("")}</ul>`
    : `<div class="small muted">No interview scheduled yet.</div>`}
  <div class="row" style="margin-top:6px"><button type="button" class="btn sm primary" onclick="addInterview(${a.id})">+ Add interview</button><a class="btn sm" href="#/interviews" onclick="closeModal()">Open Interviews page</a></div>
  <h3 style="margin-top:14px">Timeline</h3><ul class="checks">${a.events.map((e) => `<li><span class="muted small nowrap">${fmtDT(e.occurred_at)}</span><span><b>${esc(title(e.event_type))}</b> ${esc(e.description || "")}</span></li>`).join("")}</ul>`);
  $("#af").onsubmit = async (e) => {
    e.preventDefault(); const f = e.target; const b = Object.fromEntries(new FormData(f));
    b.response_received = f.response_received.checked; b.documents_sent = b.documents_sent ? b.documents_sent.split(",").map((s) => s.trim()).filter(Boolean) : [];
    for (const k of ["date_applied", "follow_up_date"]) if (!b[k]) b[k] = null;
    await api(`/api/applications/${a.id}`, { method: "PATCH", body: b }); closeModal(); toast("Saved"); await viewApplications();
    promptInterviewIfNeeded(a.id, b.application_status, (a.interviews || []).length);
  };
}
// Moving an application into the Interview stage without a time: ask for it so it reaches the Interviews page.
function promptInterviewIfNeeded(appId, status, interviewCount) {
  if (["INTERVIEW", "SECOND_INTERVIEW", "OFFER"].includes(status) && !interviewCount) addInterview(appId, null, { prompt: true });
}
window.logEvent = async (id, type) => { const desc = prompt(`${title(type)} — note (optional)`) ?? null; if (desc === null) return; await api(`/api/applications/${id}/events`, { method: "POST", body: { event_type: type, description: desc } }); toast("Logged"); closeModal(); viewApplications(); };
window.followUpEmail = async (jobId) => { S.job = await api(`/api/jobs/${jobId}`); genDoc("follow-up"); };

// ------------------------------------------------------------------ contacts
function ago(days) {
  if (days === null || days === undefined) return "Date unknown";
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 14) return "1 week ago";
  if (days < 30) return `${Math.floor(days / 7)} weeks ago`;
  if (days < 60) return "1 month ago";
  return `${Math.floor(days / 30)} months ago`;
}
function agoBadge(days) {
  const cls = days === null || days === undefined ? "b-unk" : days <= 14 ? "b-good" : days <= 30 ? "b-warn" : days <= 60 ? "b-orange" : "b-bad";
  return `<span class="badge ${cls}" style="font-weight:600">${esc(ago(days))}</span>`;
}
async function viewContacts() {
  const cf = store.get("jh_contact_filters", { sort: "newest", posted: "", q: "", type: "", state: "", mail: "EXISTS", applied: false });
  if (cf.mail === undefined || !["EXISTS", "", "NONE"].includes(cf.mail)) cf.mail = "EXISTS";
  if (!S.facets) { try { S.facets = await api(`/api/jobs/facets?demo=${S.demo}`); } catch { /* names are optional */ } }
  S.contacts = (await api(`/api/contacts${cf.applied ? "?include_applied=true" : ""}`)).filter((c) => S.demo || !c.jobs.every((j) => j.is_demo) || !c.jobs.length);
  const types = [...new Set(S.contacts.map((c) => c.contact_type))].sort();
  // States that actually have contacts, with how many contacts each.
  const stateCounts = {};
  S.contacts.forEach((c) => (c.states || []).forEach((s) => (stateCounts[s] = (stateCounts[s] || 0) + 1)));
  const STATE_NAMES = Object.fromEntries(((S.facets || {}).states || []).map((s) => [s.code, s.name]));
  if (cf.state && !stateCounts[cf.state]) cf.state = "";
  $("#view").innerHTML = `<div class="page-head"><div><h1>Contacts</h1><p>Normalized principal / recruiter / HR records with the source that confirms each one. Guessed emails are never stored.</p></div></div>
  <div class="toolbar" id="cbar">
    <input id="cq" placeholder="Search name, school, email…" value="${esc(cf.q)}" style="min-width:240px">
    <label class="small muted row" style="gap:6px">Posted<select id="cposted">${[["", "Any time"], ["0", "Today"], ["3", "Last 3 days"], ["7", "Last 7 days (1 week)"], ["14", "Last 14 days (2 weeks)"], ["30", "Last 30 days (1 month)"], ["older", "Older than 30 days"]].map(([v, l]) => `<option value="${v}" ${cf.posted === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    <label class="small muted row" style="gap:6px">State<select id="cstate"><option value="">All states</option>${Object.keys(stateCounts).sort().map((s) => `<option value="${s}" ${cf.state === s ? "selected" : ""}>${s}${STATE_NAMES[s] ? " – " + esc(STATE_NAMES[s]) : ""} (${stateCounts[s]})</option>`).join("")}</select></label>
    <label class="small muted row" style="gap:6px">Email<select id="cmail">${[["EXISTS", "✓ Confirmed email only"], ["", "All contacts"], ["NONE", "No confirmed email"]].map(([v, l]) => `<option value="${v}" ${(cf.mail ?? "EXISTS") === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    <label class="small muted row" style="gap:6px">Type<select id="ctype"><option value="">All</option>${types.map((t) => `<option value="${t}" ${cf.type === t ? "selected" : ""}>${esc(title(t))}</option>`).join("")}</select></label>
    <label class="small muted row" style="gap:6px">Sort<select id="csort">${[["newest", "Newest posting first"], ["oldest", "Oldest posting first"], ["verified", "Recently verified"], ["name", "Name A–Z"], ["org", "Organization A–Z"]].map(([v, l]) => `<option value="${v}" ${cf.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    <label class="small row" style="gap:6px;cursor:pointer" title="Contacts of jobs you marked Applied (or later stages) are hidden by default"><input type="checkbox" id="capplied" ${cf.applied ? "checked" : ""} style="width:auto">Show contacts for jobs I've applied to</label>
    <span class="grow"></span><span class="small muted" id="ccount"></span>
    <button class="btn sm" onclick="startScan('VERIFY_CONTACTS')" title="Asks each school's mail server whether every contact email exists. No email is sent.">Check all emails now</button>
    <button class="btn sm" onclick="showDeletedContacts()">Recently deleted</button>
  </div>
  <div class="card flush"><div class="scroll" style="max-height:calc(100vh - 240px)" id="ctable"></div></div>`;
  const apply = () => {
    const f = { q: $("#cq").value.trim().toLowerCase(), posted: $("#cposted").value, sort: $("#csort").value, type: $("#ctype").value, state: $("#cstate").value, mail: $("#cmail").value, applied: $("#capplied").checked };
    store.set("jh_contact_filters", f);
    if (f.applied !== cf.applied) { viewContacts(); return; }  // reload with/without applied jobs
    let rows = S.contacts.map((c) => {
      // Only the jobs inside the posted window / chosen state count toward the filter and are listed.
      const inWin = (j) => f.posted === "" ? true : f.posted === "older" ? (j.days_old ?? -1) > 30 : j.days_old !== null && j.days_old <= +f.posted;
      const inState = (j) => !f.state || j.state === f.state;
      return { ...c, _jobs: c.jobs.filter((j) => inWin(j) && inState(j)) };
    }).filter((c) => {
      const filtering = f.posted !== "" || f.state;
      const stateOnlyMatch = !c.jobs.length && f.posted === "" && (!f.state || (c.states || []).includes(f.state));
      return !filtering || c._jobs.length || stateOnlyMatch;
    }).filter((c) => !f.mail || (f.mail === "EXISTS" ? !!c.email : !c.email))
    .filter((c) => (!f.type || c.contact_type === f.type)
      && (!f.q || [c.full_name, c.title, c.organization, c.email, c.school, c.district, ...c.jobs.map((j) => j.title)].join(" ").toLowerCase().includes(f.q)));
    const cmp = {
      newest: (a, b) => (b.latest_posted || "").localeCompare(a.latest_posted || ""),
      oldest: (a, b) => (a.latest_posted || "9999").localeCompare(b.latest_posted || "9999"),
      verified: (a, b) => (b.verified_at || "").localeCompare(a.verified_at || ""),
      name: (a, b) => (a.full_name || "~").localeCompare(b.full_name || "~"),
      org: (a, b) => (a.organization || "~").localeCompare(b.organization || "~"),
    }[f.sort];
    rows.sort(cmp);
    $("#ccount").textContent = `${rows.length} contact${rows.length === 1 ? "" : "s"}`;
    $("#ctable").innerHTML = contactsTable(rows);
  };
  $("#cbar").addEventListener("change", apply);
  let t; $("#cq").addEventListener("input", () => { clearTimeout(t); t = setTimeout(apply, 250); });
  apply();
}
window.checkMailbox = async (id, btn, inDrawer) => {
  const old = btn.textContent; btn.disabled = true; btn.textContent = "Checking…";
  try {
    const c = await api(`/api/contacts/${id}/check-mailbox`, { method: "POST" });
    toast(c.email ? `Confirmed: ${c.email} exists` : `Still not confirmed — ${(MAILBOX[c.mailbox_status] || ["", "check inconclusive"])[1]}. The address stays hidden.`, 6000);
    if (inDrawer) reopen();
    else { const i = S.contacts.findIndex((x) => x.id === id); if (i >= 0) S.contacts[i] = { ...S.contacts[i], ...c }; $("#cbar").dispatchEvent(new Event("change")); }
  } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = old; }
};
function contactsTable(rows) {
  return `<table class="tbl"><thead><tr><th>Name</th><th>Title</th><th>Organization</th><th>Type</th><th>Email</th><th>Phone</th><th>Latest posting</th><th>Verification</th><th>Jobs</th><th>Source</th><th></th></tr></thead><tbody>
  ${rows.map((c) => `<tr><td><b>${esc(c.full_name || "Unnamed")}</b></td><td>${esc(c.title || "")}</td><td>${esc(c.organization || "")}${(c.states || []).length ? `<div style="margin-top:3px">${c.states.map((s) => `<span class="badge b-info">${esc(s)}</span>`).join(" ")}</div>` : ""}</td><td>${esc(title(c.contact_type))}</td>
    <td>${c.email ? `<a href="mailto:${esc(c.email)}">${esc(c.email)}</a><br>${badge(MAILBOX, "EXISTS")}`
      : `<span class="muted small">No confirmed email</span>${c.has_unconfirmed_email && !deadMailbox(c) ? `<div><button class="linkbtn" style="color:var(--accent-ink);font-size:11.5px" onclick="checkMailbox(${c.id}, this)">Check again</button></div>` : ""}`}</td><td>${esc(c.phone || "")}</td>
    <td class="nowrap">${agoBadge(c.latest_days_old)}<div class="tiny muted">${c.latest_posted ? fmtDate(c.latest_posted) : ""}</div></td>
    <td>${badge(VER, c.verification_status)}<div class="tiny muted">${fmtDT(c.verified_at)}</div></td>
    <td class="small">${c._jobs.map((j, i) => `<div class="row" style="gap:6px;flex-wrap:nowrap;margin-bottom:5px;${i >= 3 ? "display:none" : ""}" data-more="${i >= 3 ? 1 : 0}">
        <a class="btn sm primary" href="#/job/${j.job_id}">View job</a>
        <span><a href="#/job/${j.job_id}">${esc(j.title)}</a>${j.job_status === "CLOSED" ? ` <span class="badge b-bad">Closed</span>` : ""}
          <span class="muted">(${esc(title(j.relationship))}, ${j.confidence})</span>
          <span class="tiny" style="display:block;color:var(--ink-2)">Posted ${esc(ago(j.days_old))}${j.date_posted ? " · " + fmtDate(j.date_posted) : ""}</span></span></div>`).join("")
      || `<span class="muted">No linked job</span>`}
      ${c._jobs.length > 3 ? `<button class="linkbtn" style="color:var(--accent-ink)" onclick="this.closest('td').querySelectorAll('[data-more=\\'1\\']').forEach(e=>e.style.display='flex');this.remove()">Show ${c._jobs.length - 3} more</button>` : ""}</td>
    <td>${c.source_url ? `<a target="_blank" rel="noopener" href="${esc(c.source_url)}">Source ↗</a>` : ""}</td>
    <td><button class="btn sm danger" onclick="deleteContact(${c.id})">Delete</button></td></tr>`).join("") || `<tr><td colspan="11" class="muted">No contacts match these filters.</td></tr>`}</tbody></table>`;
}
// Delete a contact (removed from Contacts, jobs, letters and exports) with Undo.
window.deleteContact = async (id, fromDrawer) => {
  const c = (S.contacts || []).find((x) => x.id === id) || (S.job && S.job.contacts || []).find((x) => x.id === id);
  const label = c ? (c.full_name || c.title || c.email || "contact") : "contact";
  await api(`/api/contacts/${id}`, { method: "DELETE" });
  const refresh = () => {
    if (fromDrawer && S.job) reopen();
    const cur = (location.hash.replace(/^#\/?/, "") || "").split("/")[0];
    if (cur === "contacts") viewContacts();
  };
  toastUndo(`Deleted contact: ${label}`, async () => {
    const r = await api(`/api/contacts/${id}/restore`, { method: "POST" });
    toast(`Restored${r.jobs_relinked ? ` and re-linked to ${r.jobs_relinked} job${r.jobs_relinked === 1 ? "" : "s"}` : ""}`);
    refresh();
  });
  refresh();
};
window.showDeletedContacts = async () => {
  const rows = await api("/api/contacts/deleted");
  openModal(`<h2>Recently deleted contacts</h2><p class="small muted">Restoring a contact also puts it back on the jobs it was linked to.</p>
    <table class="tbl"><thead><tr><th>Name</th><th>Title</th><th>Organization</th><th>Jobs</th><th>Deleted</th><th></th></tr></thead><tbody>
    ${rows.map((c) => `<tr><td><b>${esc(c.full_name || "Unnamed")}</b></td><td>${esc(c.title || "")}</td><td>${esc(c.organization || "")}</td><td>${c.job_count}</td>
      <td class="nowrap small">${fmtDT(c.deleted_at)}</td><td><button class="btn sm" onclick="restoreContact(${c.id}, this)">Undo delete</button></td></tr>`).join("")
      || `<tr><td colspan="6" class="muted">Nothing deleted.</td></tr>`}</tbody></table>`);
};
window.restoreContact = async (id, btn) => {
  const r = await api(`/api/contacts/${id}/restore`, { method: "POST" });
  btn.closest("tr").remove();
  toast(`Restored${r.jobs_relinked ? ` and re-linked to ${r.jobs_relinked} job${r.jobs_relinked === 1 ? "" : "s"}` : ""}`);
  if ((location.hash || "").includes("contacts")) viewContacts();
};

// ------------------------------------------------------------------ interviews
function interviewCard(i, tz) {
  return `<div class="card"><div class="row between"><b>${esc(i.round_label || "Interview")}</b>
      <div class="row" style="gap:4px"><button class="btn sm" onclick="editInterview(${i.id})">Edit</button><button class="btn sm danger" onclick="delInterview(${i.id})">Delete</button></div></div>
    <div class="small"><b>${esc(i.position || "")}</b></div>
    <div class="small muted">${esc([i.school, i.employer_name].filter(Boolean).join(" · "))}${i.state ? ` <span class="badge b-info">${esc(i.state)}</span>` : ""}</div>
    <div class="times" style="margin:10px 0"><div><span class="tiny muted">U.S. LOCAL TIME (${esc(tz[i.us_timezone] || i.us_timezone)})</span><b>${esc(i.us_local)}</b></div><div><span class="tiny muted">PHILIPPINE TIME</span><b>${esc(i.ph_local)}</b></div></div>
    <dl class="kv"><dt>Interviewer</dt><dd>${esc(i.interviewer || "—")}${i.interviewer_role ? ", " + esc(i.interviewer_role) : ""}</dd><dt>Duration</dt><dd>${i.duration_minutes} min</dd>
    <dt>Meeting</dt><dd>${i.meeting_url ? `<a target="_blank" rel="noopener" href="${esc(i.meeting_url)}">${esc(i.meeting_url)}</a>` : "—"}</dd><dt>Notes</dt><dd>${esc(i.notes || "—")}</dd></dl>
    ${i.application_id ? `<div class="row" style="margin-top:8px"><button class="btn sm" onclick="openAppFromInterview(${i.application_id})">Open application</button>${i.job_id ? `<a class="btn sm" href="#/job/${i.job_id}">View job</a>` : ""}</div>` : ""}</div>`;
}
async function viewInterviews() {
  const d = await api("/api/interviews");
  S.tz = d.timezones;
  S.interviews = d.items;
  const upcoming = d.items.filter((i) => !i.is_past), past = d.items.filter((i) => i.is_past).reverse();
  const grid = (list) => `<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(340px,1fr))">${list.map((i) => interviewCard(i, d.timezones)).join("")}</div>`;
  $("#view").innerHTML = `<div class="page-head"><div><h1>Interviews</h1><p>Every interview shows U.S. local time and Philippine time (PHT). Interviews added from an application appear here automatically.</p></div><button class="btn primary" onclick="addInterview()">Add interview</button></div>
    ${d.awaiting.length ? `<div class="card" style="margin-bottom:14px;border-left:4px solid var(--warn-dot)"><h3>Needs a date &amp; time (${d.awaiting.length})</h3>
      <p class="small muted" style="margin-top:0">These applications are in the Interview stage but have no interview time yet.</p>
      <table class="tbl"><tbody>${d.awaiting.map((a) => `<tr><td><b>${esc(a.position || "")}</b><div class="small muted">${esc([a.school, a.employer_name].filter(Boolean).join(" · "))}</div></td>
        <td>${a.state ? `<span class="badge b-info">${esc(a.state)}</span>` : ""}</td><td class="nowrap" style="text-align:right"><button class="btn sm primary" onclick="addInterview(${a.id})">Add date &amp; time</button></td></tr>`).join("")}</tbody></table></div>` : ""}
    <h3>Upcoming (${upcoming.length})</h3>${upcoming.length ? grid(upcoming) : `<div class="card empty" style="margin-bottom:14px"><b>No upcoming interviews</b>Add one from an application or with “Add interview”.</div>`}
    ${past.length ? `<h3 style="margin-top:18px">Past (${past.length})</h3>${grid(past)}` : ""}`;
}
window.openAppFromInterview = async (appId) => {
  const d = await api("/api/applications");
  S.apps = d;
  const a = d.items.find((x) => x.id === appId);
  if (a) openApp(a); else toast("That application was deleted.");
};
window.editInterview = (id) => addInterview(null, (S.interviews || []).find((i) => i.id === id));
// Add or edit an interview. After saving, whichever page is open (Applications or Interviews) refreshes.
window.addInterview = async (appId, existing, opts = {}) => {
  const tz = S.tz || (S.tz = (await api("/api/interviews")).timezones);
  const apps = (await api("/api/applications")).items;
  const app = apps.find((a) => a.id === (appId || existing?.application_id));
  const v = existing || {};
  openModal(`<h2>${existing ? "Edit interview" : "Add interview"}</h2>
    ${opts.prompt ? `<div class="notice warn small" style="margin-bottom:10px">This application is now in the <b>Interview</b> stage. Add the date and time so it shows on the Interviews page.</div>` : ""}
    <form class="form" id="iv">
    <label>Application<select name="application_id" ${existing ? "disabled" : ""}><option value="">—</option>${apps.map((a) => `<option value="${a.id}" ${app && a.id === app.id ? "selected" : ""}>${esc(a.position)} — ${esc(a.school || a.employer_name || "")}</option>`).join("")}</select></label>
    <div class="cols"><label>Date & time (U.S. local)<input type="datetime-local" name="local_datetime" required value="${esc(v.us_local_iso || "")}"></label><label>U.S. time zone<select name="us_timezone">${Object.entries(tz).map(([k, lbl]) => `<option value="${k}" ${k === (v.us_timezone || "America/Chicago") ? "selected" : ""}>${lbl} (${k})</option>`).join("")}</select></label></div>
    <div id="phPreview" class="notice small">Philippine time will appear here.</div>
    <div class="cols"><label>Round<input name="round_label" placeholder="First interview" value="${esc(v.round_label || "")}"></label><label>Duration (min)<input type="number" name="duration_minutes" value="${esc(v.duration_minutes || 30)}"></label></div>
    <div class="cols"><label>Interviewer<input name="interviewer" value="${esc(v.interviewer || "")}"></label><label>Interviewer role<input name="interviewer_role" value="${esc(v.interviewer_role || "")}"></label></div>
    <div class="cols"><label>School<input name="school" value="${esc(v.school || (app && app.school) || "")}"></label><label>Meeting URL<input name="meeting_url" value="${esc(v.meeting_url || "")}"></label></div>
    <label>Notes<textarea name="notes" style="min-height:70px">${esc(v.notes || "")}</textarea></label><button class="btn primary">Save</button><div id="ivErr" class="small" style="color:var(--bad)"></div></form>`);
  const f = $("#iv");
  const preview = () => {
    const val = f.local_datetime.value; if (!val) return;
    try {
      // Convert U.S. wall time -> instant using Intl offsets (two-pass for DST boundaries)
      const zone = f.us_timezone.value;
      const guess = new Date(val + "Z");
      const off = (d) => { const p = new Intl.DateTimeFormat("en-US", { timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).formatToParts(d).reduce((a, x) => (a[x.type] = x.value, a), {}); return (Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) - d.getTime()); };
      let inst = new Date(guess.getTime() - off(guess)); inst = new Date(guess.getTime() - off(inst));
      const ph = inst.toLocaleString("en-US", { timeZone: "Asia/Manila", weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
      $("#phPreview").innerHTML = `Philippine time: <b>${ph} PHT</b>`;
    } catch { /* preview only */ }
  };
  f.local_datetime.oninput = preview; f.us_timezone.onchange = preview; preview();
  f.onsubmit = async (e) => {
    e.preventDefault();
    const b = Object.fromEntries(new FormData(f));
    b.application_id = existing ? existing.application_id : (b.application_id ? +b.application_id : null);
    b.duration_minutes = +b.duration_minutes || 30;
    try {
      if (existing) await api(`/api/interviews/${existing.id}`, { method: "PUT", body: b });
      else await api("/api/interviews", { method: "POST", body: b });
    } catch (err) { $("#ivErr").textContent = err.message; return; }
    closeModal();
    toast(existing ? "Interview updated" : "Interview saved — it's listed on the Interviews page", 5000);
    const cur = (location.hash.replace(/^#\/?/, "") || "dashboard").split("/")[0];
    if (cur === "applications") viewApplications(); else if (cur === "interviews") viewInterviews();
  };
};
window.delInterview = async (id) => { if (!confirm("Delete this interview?")) return; await api(`/api/interviews/${id}`, { method: "DELETE" }); viewInterviews(); };

// ------------------------------------------------------------------ alerts
const RULES = { STATE: "Only these states (filters all alerts)", HIGH_MATCH: "New high-match job", CONFIRMED_J1: "New confirmed J-1 math job", SALARY: "Salary above threshold", VERIFIED_RECRUITER_EMAIL: "Verified recruiter email found", VERIFIED_PRINCIPAL_EMAIL: "Verified principal email found" };
function ruleDetail(r) {
  const p = r.params || {};
  if (r.rule_type === "STATE") return `States: <b>${esc((p.states || []).join(", ") || "none")}</b>`;
  if (r.rule_type === "HIGH_MATCH") return `Match ≥ ${esc(p.min_score ?? 90)}%`;
  if (r.rule_type === "SALARY") return `Published salary ≥ ${fmtMoney(p.min_salary || 0)}`;
  return "";
}
async function viewAlerts() {
  const d = await api("/api/alerts");
  S.rules = d.rules;
  $("#view").innerHTML = `<div class="page-head"><div><h1>Alerts</h1><p>Generated after each scan from your rules.</p></div><div class="row"><button class="btn" onclick="readAll()">Mark all read</button><button class="btn primary" onclick="addRule()">Add alert rule</button></div></div>
  ${d.state_filter ? `<div class="notice" style="margin-bottom:12px">Showing alerts only for <b>${esc(d.state_filter.join(", "))}</b>, from your state rule. Turn that rule off to see alerts from every state.</div>`
    : `<div class="notice small" style="margin-bottom:12px">Alerts cover every state. Add an <b>“Only these states”</b> rule to limit all alerts to the states you choose.</div>`}
  <div class="two"><div class="card"><h3>Notifications</h3><div class="grid" style="gap:8px">${d.alerts.map((a) => `<div class="ev" style="${a.is_read ? "" : "border-left:4px solid var(--accent)"}"><div class="h"><span>${esc(a.title)}${a.state ? ` <span class="badge b-info">${esc(a.state)}</span>` : ""}</span><span class="tiny muted">${fmtDT(a.created_at)}</span></div><div class="small">${esc(a.message)}</div>
    ${a.job_id ? `<div class="row" style="margin-top:6px"><a class="btn sm" href="#/job/${a.job_id}">VIEW JOB</a></div>` : ""}</div>`).join("") || `<div class="muted small">No alerts${d.state_filter ? " in the selected states" : ""} yet.</div>`}</div></div>
  <div class="card"><h3>Rules</h3><table class="tbl"><tbody>${d.rules.map((r) => `<tr><td>${esc(RULES[r.rule_type] || r.rule_type)}<div class="small">${ruleDetail(r)}</div></td>
    <td><label class="row"><input type="checkbox" ${r.enabled ? "checked" : ""} onchange="toggleRule(${r.id},this.checked)" style="width:auto"> On</label></td>
    <td class="nowrap">${["STATE", "HIGH_MATCH", "SALARY"].includes(r.rule_type) ? `<button class="btn sm" onclick="addRule(${r.id})">Edit</button> ` : ""}<button class="btn sm danger" onclick="delRule(${r.id})">Delete</button></td></tr>`).join("")}</tbody></table></div></div>`;
}
window.readAll = async () => { await api("/api/alerts/read-all", { method: "POST" }); viewAlerts(); renderNav("alerts", 0); };
window.toggleRule = async (id, on) => {
  const r = S.rules.find((x) => x.id === id);
  try { await api(`/api/alerts/rules/${id}`, { method: "PATCH", body: { rule_type: r.rule_type, params: r.params, enabled: on } }); }
  catch (e) { toast(e.message); }
  renderView("alerts");
};
window.delRule = async (id) => { await api(`/api/alerts/rules/${id}`, { method: "DELETE" }); renderView("alerts"); };
window.addRule = async (editId) => {
  const edit = editId ? S.rules.find((r) => r.id === editId) : null;
  const states = (S.facets || await api("/api/jobs/facets")).states;
  const cur = edit?.params || {};
  const chosen = new Set(cur.states || []);
  openModal(`<h2>${edit ? "Edit" : "Add"} alert rule</h2><form class="form" id="rf">
    <label>Type<select name="rule_type" ${edit ? "disabled" : ""}>${Object.entries(RULES).map(([k, v]) => `<option value="${k}" ${edit?.rule_type === k ? "selected" : ""}>${v}</option>`).join("")}</select></label>
    <div data-for="STATE"><div class="small muted" style="margin-bottom:6px">Selected states filter <b>every</b> alert rule: only jobs in these states will create alerts or appear under Alerts.</div>
      <div class="row" style="margin-bottom:6px"><button type="button" class="btn sm" id="stAll">Select all</button><button type="button" class="btn sm" id="stNone">Clear</button><span class="small muted" id="stCount"></span></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:2px 10px;max-height:300px;overflow-y:auto;border:1px solid var(--line);border-radius:8px;padding:8px">
      ${states.map((s) => `<label style="display:flex;align-items:center;gap:6px;font-weight:500;color:var(--ink);padding:2px 0;cursor:pointer"><input type="checkbox" name="st" value="${s.code}" ${chosen.has(s.code) ? "checked" : ""} style="width:auto">${s.code} · ${esc(s.name)}</label>`).join("")}</div></div>
    <label data-for="HIGH_MATCH">Minimum match %<input name="min_score" type="number" min="0" max="100" value="${esc(cur.min_score ?? 90)}"></label>
    <label data-for="SALARY">Minimum published salary<input name="min_salary" type="number" value="${esc(cur.min_salary ?? "")}" placeholder="65000"></label>
    <div id="rfErr" class="small" style="color:var(--bad)"></div>
    <button class="btn primary">${edit ? "Save" : "Add"}</button></form>`);
  const f = $("#rf");
  const count = () => { $("#stCount").textContent = `${$$("input[name=st]:checked", f).length} selected`; };
  const sync = () => { const t = f.rule_type.value; $$("[data-for]", f).forEach((el) => el.classList.toggle("hidden", el.dataset.for !== t)); };
  f.rule_type.onchange = sync; sync(); count();
  f.addEventListener("change", (e) => { if (e.target.name === "st") count(); });
  $("#stAll").onclick = () => { $$("input[name=st]", f).forEach((c) => (c.checked = true)); count(); };
  $("#stNone").onclick = () => { $$("input[name=st]", f).forEach((c) => (c.checked = false)); count(); };
  f.onsubmit = async (e) => {
    e.preventDefault();
    const t = f.rule_type.value; const params = {};
    if (t === "HIGH_MATCH") params.min_score = +f.min_score.value || 90;
    if (t === "SALARY") params.min_salary = +f.min_salary.value || 0;
    if (t === "STATE") {
      params.states = $$("input[name=st]:checked", f).map((c) => c.value);
      if (!params.states.length) { $("#rfErr").textContent = "Select at least one state."; return; }
    }
    try {
      if (edit) await api(`/api/alerts/rules/${edit.id}`, { method: "PATCH", body: { rule_type: t, params, enabled: edit.enabled } });
      else await api("/api/alerts/rules", { method: "POST", body: { rule_type: t, params } });
      closeModal(); renderView("alerts");
    } catch (err) { $("#rfErr").textContent = err.message; }
  };
};

// ------------------------------------------------------------------ documents
async function viewDocuments() {
  const [docs, resumes] = await Promise.all([api("/api/documents"), api("/api/resumes")]);
  $("#view").innerHTML = `<div class="page-head"><div><h1>Documents</h1><p>Résumé versions and supporting documents for applications.</p></div></div>
  <div class="two"><div class="card"><h3>Upload document</h3><form class="form" id="df"><label>File<input type="file" name="file" required></label><label>Kind<select name="kind">${["COVER_LETTER", "LICENSE", "TRANSCRIPT", "CERTIFICATE", "RECOMMENDATION", "OTHER"].map((k) => `<option value="${k}">${title(k)}</option>`).join("")}</select></label><label>Notes<input name="notes"></label><button class="btn primary">Upload</button></form></div>
  <div class="card"><h3>Résumé versions</h3><table class="tbl"><tbody>${resumes.map((r) => `<tr><td><b>${esc(r.version_label)}</b> ${r.is_active ? `<span class="badge b-good">Active</span>` : ""}<div class="small">${esc(r.filename)}</div></td><td class="small">${fmtDT(r.uploaded_at)}</td></tr>`).join("") || `<tr><td class="muted">No résumé uploaded yet — the built-in profile is used for matching.</td></tr>`}</tbody></table>
  <button class="btn" style="margin-top:8px" onclick="$('#resumeFile').click()">Upload new résumé</button></div></div>
  <div class="card" style="margin-top:14px"><h3>Documents</h3><table class="tbl"><thead><tr><th>Name</th><th>Kind</th><th>Notes</th><th>Uploaded</th><th></th></tr></thead><tbody>${docs.map((d) => `<tr><td>${esc(d.name)}</td><td>${esc(title(d.kind))}</td><td>${esc(d.notes || "")}</td><td>${fmtDT(d.uploaded_at)}</td><td><a class="btn sm" href="/api/documents/${d.id}/download">Download</a></td></tr>`).join("") || `<tr><td colspan="5" class="muted">No documents yet.</td></tr>`}</tbody></table></div>`;
  $("#df").onsubmit = async (e) => { e.preventDefault(); await api("/api/documents", { method: "POST", body: new FormData(e.target) }); toast("Uploaded"); viewDocuments(); };
}

// ------------------------------------------------------------------ settings
async function viewSettings() {
  const [me, sch] = await Promise.all([api("/api/me"), api("/api/schedule")]);
  const p = me.profile;
  const list = (k) => esc((p[k] || []).map((x) => typeof x === "string" ? x : x.text + (x.status && x.status !== "completed" ? ` [${x.status}]` : "")).join("\n"));
  $("#view").innerHTML = `<div class="page-head"><div><h1>Settings</h1><p>Candidate profile, scan schedule and display options.</p></div></div>
  <div class="two"><div class="card"><h2>Candidate profile</h2><p class="small muted">Used for match scores and generated letters. One item per line. Saving recalculates every match score.</p>
    <form class="form" id="pf"><div class="cols"><label>Full name<input name="full_name" value="${esc(p.full_name || "")}"></label><label>Email<input name="email" value="${esc(p.email || "")}"></label></div>
    <div class="cols"><label>Years of teaching experience<input type="number" step="0.5" name="years_experience" value="${esc(p.years_experience ?? "")}"></label><label>Location<input name="location" value="${esc(p.location || "")}"></label></div>
    <label>Education (append [in progress] if not finished)<textarea name="education" style="min-height:100px">${list("education")}</textarea></label>
    <label>Licenses / certifications<textarea name="licenses" style="min-height:60px">${list("licenses")}</textarea></label>
    <label>Subjects taught<textarea name="subjects" style="min-height:90px">${list("subjects")}</textarea></label>
    <div class="cols"><label>Grade levels<textarea name="grade_levels" style="min-height:70px">${list("grade_levels")}</textarea></label><label>Leadership roles<textarea name="leadership" style="min-height:70px">${list("leadership")}</textarea></label></div>
    <div class="cols"><label>Technologies<textarea name="technologies" style="min-height:70px">${list("technologies")}</textarea></label><label>Research / STEM<textarea name="research_stem" style="min-height:70px">${list("research_stem")}</textarea></label></div>
    <label>Awards<textarea name="awards" style="min-height:50px">${list("awards")}</textarea></label>
    <div class="cols"><label>Preferred states (comma, optional)<input name="preferred_states" value="${esc((p.preferred_states || []).join(", "))}"></label><label>Minimum salary<input type="number" name="min_salary" value="${esc(p.min_salary ?? "")}"></label></div>
    <label class="row" style="font-weight:500"><input type="checkbox" name="has_us_license" ${p.has_us_license ? "checked" : ""} style="width:auto"> I hold a U.S. state teaching license</label>
    <button class="btn primary">Save profile & rescore</button></form></div>
  <div class="grid" style="align-content:start"><div class="card"><h2>Scheduled scans</h2><p class="small muted">Runs while the app is open. Manual buttons are always available.</p>
    <form class="form" id="sf">${Object.entries(sch.schedule).map(([k, v]) => `<div class="row between"><label class="row" style="font-weight:600"><input type="checkbox" name="${k}_on" ${v.enabled ? "checked" : ""} style="width:auto">${esc({ QUICK: "Quick scan", FULL: "Full national scan", VERIFY_CONTACTS: "Contact verification", J1: "J-1 verification", CLOSED_CHECK: "Closed job check", H1B: "H-1B sponsors check", ENG: "Engineering jobs search" }[k] || k)}</label><label class="row">every <input type="number" name="${k}_h" value="${v.hours}" style="width:70px"> h</label></div>`).join("")}
    <div class="tiny muted">${sch.next_runs.map((n) => `${esc(n.kind)} next: ${fmtDT(n.next_run?.slice(0, 19))}`).join(" · ")}</div><button class="btn">Save schedule</button></form></div>
    <div class="card"><h2>Display</h2><label class="row"><span>Theme</span><select id="theme"><option value="">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label>
      <label class="row" style="margin-top:10px"><input type="checkbox" id="demoMode" ${S.demo ? "checked" : ""} style="width:auto"> Show DEMO / FICTIONAL data instead of live results</label>
      <button class="btn sm" style="margin-top:8px" onclick="loadDemo()">Create demo records</button>
      <p class="tiny muted">Demo records are labeled and never mixed into live search results.</p></div></div></div>`;
  $("#theme").value = store.get("jh_theme", "");
  $("#theme").onchange = (e) => { store.set("jh_theme", e.target.value); applyTheme(); };
  $("#demoMode").onchange = (e) => { S.demo = e.target.checked; store.set("jh_demo", S.demo); S.facets = null; toast(S.demo ? "Demo mode on" : "Live data"); };
  $("#pf").onsubmit = async (e) => {
    e.preventDefault(); const f = e.target; const fd = Object.fromEntries(new FormData(f));
    const lines = (s) => (s || "").split("\n").map((x) => x.trim()).filter(Boolean);
    const body = { full_name: fd.full_name, email: fd.email, location: fd.location, years_experience: fd.years_experience ? +fd.years_experience : null,
      education: lines(fd.education).map((t) => { const m = t.match(/^(.*)\s\[(.+)\]$/); return m ? { text: m[1], status: m[2] } : { text: t, status: "completed" }; }),
      preferred_states: fd.preferred_states.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean), min_salary: fd.min_salary ? +fd.min_salary : null, has_us_license: f.has_us_license.checked };
    for (const k of ["licenses", "subjects", "grade_levels", "leadership", "technologies", "research_stem", "awards"]) body[k] = lines(fd[k]);
    const r = await api("/api/profile", { method: "PUT", body }); toast(`Profile saved — ${r.rescored} jobs rescored`);
  };
  $("#sf").onsubmit = async (e) => {
    e.preventDefault(); const f = e.target; const body = {};
    for (const k of Object.keys(sch.schedule)) body[k] = { enabled: f[`${k}_on`].checked, hours: +f[`${k}_h`].value || 24 };
    await api("/api/schedule", { method: "PUT", body }); toast("Schedule saved");
  };
}
window.loadDemo = async () => { const r = await api("/api/demo", { method: "POST" }); toast(r.created ? `Created ${r.created} demo records` : "Demo records already exist"); };
function applyTheme() { const t = store.get("jh_theme", ""); if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }

// ------------------------------------------------------------------ outbox (emails waiting for approval)
// New openings with a confirmed principal email get a ready email automatically; nothing is sent until approved.
async function checkOutbox(announce = true) {
  let n = 0;
  try { n = (await api("/api/outbox/count")).pending; } catch { return 0; }
  const seen = store.get("jh_outbox_seen", 0);
  if (announce && n > seen) {
    const added = n - seen;
    toast(`📨 ${added} new application email${added === 1 ? "" : "s"} waiting for your approval — open Outbox.`, 7000);
    try {
      if ("Notification" in window && Notification.permission === "granted") {
        const note = new Notification("USA Job Hunter — emails to approve", { body: `${n} application email${n === 1 ? "" : "s"} waiting in your Outbox. Nothing is sent until you approve.` });
        note.onclick = () => { window.focus(); location.hash = "#/outbox"; };
      }
    } catch { /* notifications are optional */ }
  }
  store.set("jh_outbox_seen", n);
  const badge = $("#nav a[href='#/outbox'] .count");
  if (badge) badge.textContent = n; else if (n) renderNav((location.hash.replace(/^#\/?/, "") || "dashboard").split("/")[0], S.unread || 0, n);
  S.outboxPending = n;
  return n;
}
async function viewOutbox() {
  const tab = store.get("jh_outbox_tab", "PENDING");
  const d = await api(`/api/outbox?status=${tab}`);
  const st = d.settings, c = d.counts || {};
  S.outbox = d;
  const ready = st.gmail_address && st.app_password_set;
  $("#view").innerHTML = `<div class="page-head"><div><h1>Outbox</h1><p>Application emails to principals, prepared automatically for new openings. <b>Nothing is sent until you approve it.</b></p></div>
    <div class="row">${st.enabled ? `<button class="btn" id="obRefresh">Check for new openings now</button>` : ""}</div></div>
    <div class="card" style="margin-bottom:14px">
      <div class="row between" style="align-items:flex-start"><div>
        <label class="row" style="gap:8px;font-weight:700;cursor:pointer"><input type="checkbox" id="obEnabled" ${st.enabled ? "checked" : ""} style="width:auto"> Auto-prepare emails for new openings</label>
        <div class="tiny muted" style="margin-top:4px">After every scan, each new opening whose principal is named by an official source and has an email the school's mail server confirmed gets a ready email
          ("Dear Principal [name]", the school's name, your text and portfolio link). You get a notification, then you decide: <b>Approve &amp; send</b> or <b>Skip</b>. One email per principal per 30 days.</div></div>
        <button class="btn sm" id="obNotify">${"Notification" in window && Notification.permission === "granted" ? "✓ Desktop notifications on" : "Turn on desktop notifications"}</button></div>
      <details style="margin-top:12px" ${ready ? "" : "open"}><summary style="cursor:pointer;font-weight:600">Gmail connection ${ready ? `<span class="badge b-good">✓ ${esc(st.gmail_address)}</span>` : `<span class="badge b-warn">Not connected — needed to send</span>`}</summary>
        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin-top:10px">
          <div class="small"><b>Approved emails are sent from your own Gmail.</b> Google requires an <b>app password</b> for this (not your normal password):
            <ol style="padding-left:18px;margin:6px 0"><li>Turn on <a target="_blank" rel="noopener" href="https://myaccount.google.com/signinoptions/twosv">2-Step Verification ↗</a> for your Google account (if it isn't on yet).</li>
              <li>Open <a target="_blank" rel="noopener" href="https://myaccount.google.com/apppasswords">App passwords ↗</a>, type a name such as "USA Job Hunter", click <b>Create</b>.</li>
              <li>Copy the 16-letter password and paste it here (spaces don't matter).</li></ol>
            <div class="tiny muted">Stored only in this app's database on your computer, never shown again in full. You can remove it or revoke it in your Google account at any time.</div></div>
          <div class="grid" style="gap:8px;align-content:start">
            <label class="small" style="display:grid;gap:3px">Gmail address<input id="obAddr" type="email" autocomplete="off" value="${esc(st.gmail_address || "")}" placeholder="yourname@gmail.com"></label>
            <label class="small" style="display:grid;gap:3px">App password<input id="obPw" type="password" autocomplete="off" placeholder="${st.app_password_set ? esc(st.app_password_hint) + " (saved — type to replace)" : "16-letter app password"}"></label>
            <label class="small row" style="gap:6px;cursor:pointer"><input type="checkbox" id="obResume" ${st.attach_resume ? "checked" : ""} style="width:auto"> Attach my résumé by default ${st.resume_name ? `<span class="muted">(${esc(st.resume_name)})</span>` : `<span style="color:var(--bad)">— no résumé uploaded yet (UPLOAD RESUME)</span>`}</label>
            <div class="row" style="gap:8px"><button class="btn primary" id="obSave">Save</button><button class="btn" id="obTest" ${ready ? "" : "disabled"}>Send me a test email</button>
              ${st.app_password_set ? `<button class="btn sm danger" id="obPwDel">Remove app password</button>` : ""}</div></div>
        </div></details></div>
    <div class="row" style="gap:6px;margin-bottom:10px">${[["PENDING", "Waiting for approval", (c.PENDING || 0) + (c.FAILED || 0)], ["SENT", "Sent", c.SENT || 0], ["SKIPPED", "Skipped", c.SKIPPED || 0]]
      .map(([k, l, n]) => `<button class="btn ${tab === k ? "primary" : ""}" data-tab="${k}">${l} <span class="badge ${tab === k ? "" : "b-info"}">${n}</span></button>`).join("")}</div>
    <div id="obList" class="grid" style="gap:12px"></div>`;
  $("#obList").innerHTML = d.items.map((e) => outboxCard(e, tab, ready)).join("") || `<div class="card empty"><b>${tab === "PENDING" ? "No emails waiting" : tab === "SENT" ? "Nothing sent yet" : "Nothing skipped"}</b>
    ${tab === "PENDING" ? (st.enabled ? "New openings with a confirmed principal email will appear here after scans, and you'll be notified." : "Tick “Auto-prepare emails for new openings” above to start.") : ""}</div>`;
  $$("[data-tab]").forEach((b) => b.onclick = () => { store.set("jh_outbox_tab", b.dataset.tab); viewOutbox(); });
  const saveSettings = async (body, msg) => {
    try { const r = await api("/api/outbox/settings", { method: "PUT", body }); toast(r.added ? `${msg} — ${r.added} email${r.added === 1 ? "" : "s"} prepared for your approval` : msg, 5000); }
    catch (e) { toast(e.message); }
    checkOutbox(false); viewOutbox();
  };
  $("#obEnabled").onchange = (e) => saveSettings({ enabled: e.target.checked }, e.target.checked ? "Auto-prepare is on" : "Auto-prepare is off");
  $("#obSave").onclick = () => {
    const body = { gmail_address: $("#obAddr").value, attach_resume: $("#obResume").checked };
    if ($("#obPw").value.trim()) body.app_password = $("#obPw").value;
    saveSettings(body, "Saved");
  };
  if ($("#obPwDel")) $("#obPwDel").onclick = () => saveSettings({ app_password: "" }, "App password removed");
  $("#obTest").onclick = async (ev) => {
    ev.target.disabled = true; ev.target.textContent = "Sending…";
    try { const r = await api("/api/outbox/test", { method: "POST" }); toast(`Test email sent to ${r.sent_to} — check your inbox.`, 6000); }
    catch (e) { toast(e.message, 7000); }
    ev.target.disabled = false; ev.target.textContent = "Send me a test email";
  };
  $("#obNotify").onclick = async () => {
    if (!("Notification" in window)) return toast("This browser doesn't support desktop notifications.");
    const p = await Notification.requestPermission();
    toast(p === "granted" ? "Desktop notifications on" : "Notifications were not allowed in the browser.");
    viewOutbox();
  };
  if ($("#obRefresh")) $("#obRefresh").onclick = async () => {
    try { const r = await api("/api/outbox/refresh", { method: "POST" }); toast(r.added ? `${r.added} new email${r.added === 1 ? "" : "s"} prepared` : "No new openings with a confirmed principal email right now.", 5000); }
    catch (e) { toast(e.message); }
    checkOutbox(false); viewOutbox();
  };
}
function outboxCard(e, tab, ready) {
  const pending = tab === "PENDING";
  return `<div class="card" data-ob="${e.id}">
    <div class="row between" style="align-items:flex-start;flex-wrap:nowrap"><div style="min-width:0">
      <div style="font-weight:700;font-size:15px">${e.job_id ? `<a href="#/job/${e.job_id}">${esc(e.job_title || "")}</a>` : esc(e.job_title || "")}</div>
      <div class="small">${esc([e.school, e.employer_name].filter(Boolean).join(" · "))}${e.state ? ` · <span class="badge b-info">${esc(e.state)}</span>` : ""}</div>
      <div class="tiny muted">${e.date_posted ? `Posted ${fmtDate(e.date_posted)} · ` : ""}${e.closing_text ? `Deadline ${esc(e.closing_text)} · ` : ""}prepared ${fmtDT(e.created_at)}${e.sent_at ? ` · <b>sent ${fmtDT(e.sent_at)}</b>` : ""}</div></div>
      ${e.match_score != null ? `<span class="match ${e.match_score >= 70 ? "hi" : e.match_score < 45 ? "lo" : ""}">${e.match_score}%<small>MATCH</small></span>` : ""}</div>
    ${e.job_status === "CLOSED" && pending ? `<div class="notice warn small" style="margin-top:8px">This posting has closed since the email was prepared — it won't be sent. Skip it.</div>`
      : e.status === "FAILED" && e.error ? `<div class="notice warn small" style="margin-top:8px"><b>Not sent:</b> ${esc(e.error)}</div>`
      : e.status === "SKIPPED" && e.error ? `<div class="tiny muted" style="margin-top:6px">${esc(e.error)}</div>` : ""}
    <div class="small" style="margin-top:8px"><b>To:</b> ${esc(e.to_name || "")} <span class="muted">(${esc(e.to_role || "Principal")})</span> &lt;${esc(e.to_email)}&gt; <span class="badge b-good">✓ Named by an official source</span> <span class="badge b-good">✓ Mailbox confirmed</span></div>
    ${pending ? `<label class="small" style="display:grid;gap:3px;margin-top:8px">Subject<input class="ob-subj" value="${esc(e.subject)}"></label>
      <label class="small" style="display:grid;gap:3px;margin-top:6px">Message<textarea class="ob-body" style="min-height:220px">${esc(e.body)}</textarea></label>
      <label class="small row" style="gap:6px;margin-top:6px;cursor:pointer"><input type="checkbox" class="ob-resume" ${e.attach_resume ? "checked" : ""} style="width:auto"> Attach my résumé</label>`
      : `<details style="margin-top:6px"><summary class="small" style="cursor:pointer">Subject: ${esc(e.subject)}</summary><div class="desc small" style="margin-top:6px">${esc(e.body)}</div></details>`}
    <div class="row" style="margin-top:10px;gap:8px">
      ${pending ? `<button class="btn good" onclick="obApprove(${e.id}, this)" ${ready && e.job_status !== "CLOSED" ? "" : "disabled"} title="${ready ? "Send this email from your Gmail now" : "Connect your Gmail above first"}">✓ Approve &amp; send</button>
        <button class="btn" onclick="obSkip(${e.id})">Skip</button>` : ""}
      ${tab === "SKIPPED" ? `<button class="btn" onclick="obRestore(${e.id})">Move back to waiting</button>` : ""}
      ${e.application_url ? `<a class="btn sm" target="_blank" rel="noopener" href="${esc(e.application_url)}">Official application ↗</a>` : ""}</div></div>`;
}
window.obApprove = async (id, btn) => {
  const card = btn.closest("[data-ob]");
  const e = S.outbox.items.find((x) => x.id === id);
  if (!confirm(`Send this email now from your Gmail to ${e.to_name} (${e.to_role || "Principal"}) <${e.to_email}>?`)) return;
  btn.disabled = true; btn.textContent = "Sending…";
  try {
    await api(`/api/outbox/${id}`, { method: "PUT", body: { subject: $(".ob-subj", card).value, body: $(".ob-body", card).value, attach_resume: $(".ob-resume", card).checked } });
    await api(`/api/outbox/${id}/approve`, { method: "POST" });
    S.facets = null;
    toast(`Sent to ${e.to_name} — marked applied. Opening Applications…`, 5000);
    checkOutbox(false);
    location.hash = "#/applications";   // the sent job now appears in the Applications table
    return;
  } catch (err) { toast(err.message, 8000); }
  checkOutbox(false); viewOutbox();
};
window.obSkip = async (id) => {
  await api(`/api/outbox/${id}/skip`, { method: "POST" });
  toastUndo("Skipped — it won't be sent.", async () => { await api(`/api/outbox/${id}/restore`, { method: "POST" }); checkOutbox(false); viewOutbox(); });
  checkOutbox(false); viewOutbox();
};
window.obRestore = async (id) => { await api(`/api/outbox/${id}/restore`, { method: "POST" }); toast("Moved back to waiting"); checkOutbox(false); viewOutbox(); };

// ------------------------------------------------------------------ engineering jobs
const ENG_LEVEL = { ENTRY: ["b-good", "Entry-level"], MID: ["b-warn", "Mid-level"], SENIOR: ["b-bad", "Senior"], UNKNOWN: ["b-unk", "Level not stated"] };
const ENG_SPONSOR = { OFFERED: ["b-good", "✓ Visa sponsorship mentioned"], NOT_OFFERED: ["b-bad", "✕ No visa sponsorship"], UNKNOWN: ["b-unk", "? Sponsorship not mentioned"] };
const ENG_CATS = { INDUSTRY: "Engineering Jobs", SOFTWARE: "Software / AI / Data Science Jobs", INSTRUCTOR: "Engineering Instructor Jobs" };
const ENG_MODE = { REMOTE: ["b-good", "🏠 Remote"], HYBRID: ["b-info", "🔀 Hybrid"], ONSITE: ["b-unk", "🏢 On-site"], UNKNOWN: ["b-unk", "Work mode not stated"] };
const ENG_SITE_QUERY = { INDUSTRY: "embedded systems engineer", SOFTWARE: "machine learning engineer", INSTRUCTOR: "engineering instructor" };
// Job sites that don't allow automated reading: open their own search results in a new tab.
function engSiteLinks(q, remote) {
  const e = encodeURIComponent(q), loc = remote ? "Remote" : "United States";
  return [
    ["LinkedIn", `https://www.linkedin.com/jobs/search/?keywords=${e}&location=United%20States&f_TPR=r604800&sortBy=DD${remote ? "&f_WT=2" : ""}`],
    ["Indeed", `https://www.indeed.com/jobs?q=${e}&l=${encodeURIComponent(loc)}&fromage=7&sort=date`],
    ["Glassdoor", `https://www.glassdoor.com/Job/jobs.htm?sc.keyword=${e}&locKeyword=United%20States&fromAge=7${remote ? "&remoteWorkType=1" : ""}`],
    ["ZipRecruiter", `https://www.ziprecruiter.com/jobs-search?search=${e}&location=${encodeURIComponent(remote ? "Remote (USA)" : "United States")}&days=7`],
    ["Dice", `https://www.dice.com/jobs?q=${e}&location=United%20States&filters.postedDate=SEVEN${remote ? "&filters.workplaceTypes=Remote" : ""}`],
    ["Google Jobs", `https://www.google.com/search?q=${encodeURIComponent(q + (remote ? " remote" : "") + " jobs United States")}&ibp=htl;jobs`],
    ["Built In", `https://builtin.com/jobs${remote ? "/remote" : ""}?search=${e}`],
    ["Wellfound (startups)", "https://wellfound.com/jobs"],
    ["Y Combinator startups", "https://www.workatastartup.com/jobs"],
    ["Monster", `https://www.monster.com/jobs/search?q=${e}&where=${encodeURIComponent(loc)}`],
    ["USAJOBS (federal)", `https://www.usajobs.gov/search/results/?k=${e}`],
    ["HigherEdJobs", `https://www.higheredjobs.com/search/?keyword=${e}`],
  ];
}
async function viewEngineering() {
  const f = Object.assign({ cat: "INDUSTRY", q: "", state: "", level: "", sponsor: "hide_citizen", sort: "fit", saved: false, paid: false, mode: "", age: "" },
    store.get("jh_eng", {}));
  if (!ENG_CATS[f.cat]) f.cat = "INDUSTRY";
  const d = await api(`/api/engineering?category=${f.cat}`);
  S.eng = d;
  // Skills added to the app later are checked by default, without undoing the user's own choices.
  const known = new Set(store.get("jh_eng_skills_known", d.skill_options.filter((s) => !/Deep learning|Data science|Cloud/.test(s))));
  const mySk = new Set(store.get("jh_eng_skills", d.default_skills));
  d.default_skills.forEach((s) => { if (!known.has(s)) mySk.add(s); });
  store.set("jh_eng_skills_known", d.skill_options);
  store.set("jh_eng_skills", [...mySk]);
  const states = [...new Set(d.items.map((x) => x.state).filter(Boolean))].sort();
  const STATE_NAMES = Object.fromEntries(((S.facets || {}).states || []).map((s) => [s.code, s.name]));
  const ls = d.last_scan;
  const industryLike = f.cat !== "INSTRUCTOR";
  const sel = (id, label, opts, val) => `<label class="small muted row" style="gap:6px">${label}<select id="${id}">${opts.map(([v, l]) => `<option value="${v}" ${val === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>`;
  $("#view").innerHTML = `<div class="page-head"><div><h1>Engineering Jobs</h1><p>U.S. engineering, software / AI / data science and engineering-instructor openings matched to your degrees and skills.</p></div>
    <button class="btn primary" onclick="startScan('ENG')">Search now</button></div>
    <div class="card" style="margin-bottom:12px"><div class="row" style="gap:18px;align-items:flex-start">
      <label class="small" style="display:grid;gap:4px;font-weight:600;min-width:300px">Show
        <select id="engcat" style="font-size:15px;font-weight:600;padding:9px 10px">
          ${Object.entries(ENG_CATS).map(([k, l]) => `<option value="${k}" ${f.cat === k ? "selected" : ""}>${l} (${d.counts[k] || 0})</option>`).join("")}
        </select></label>
      <div class="small" style="flex:1;min-width:260px"><b>Matched to:</b> ${esc(d.profile.degrees.join(" · "))}
        <div class="row" style="margin-top:8px;gap:8px"><b>Your skills</b><span class="tiny muted">Check the skills you want jobs matched on; scores and ranking update instantly.</span>
          <span class="grow"></span><button class="btn sm" id="engskall">Select all</button><button class="btn sm" id="engskreset">Reset</button></div>
        <div class="chips" id="engskills" style="margin-top:6px">${d.skill_options.map((s) => `<label class="chip skill-pick ${mySk.has(s) ? "on" : ""}"><input type="checkbox" value="${esc(s)}" ${mySk.has(s) ? "checked" : ""}>${esc(s)}</label>`).join("")}</div>
        <div class="tiny muted" style="margin-top:6px">${esc(d.profile.experience)}. ${industryLike ? "Entry-level roles score highest, and postings that ask for many years of industry experience are flagged." : "Instructor roles build on your teaching experience; postings that require a PhD are flagged."}</div></div>
    </div></div>
    ${industryLike ? `<div class="notice small" style="margin-bottom:12px">U.S. industry jobs usually need employer visa sponsorship (H-1B). Sponsorship and citizenship requirements below are read from each posting's own text; when a posting doesn't mention sponsorship, ask the employer. Roles requiring U.S. citizenship or a security clearance are hidden by default. <b>Remote – open worldwide</b> means the job board lists the role as open to applicants in any country.</div>` : ""}
    <div class="toolbar"><div class="search-box"><span aria-hidden="true">⌕</span><input id="engq" placeholder="Search title, company, skill, city…" value="${esc(f.q)}"></div>
      <label class="small muted row" style="gap:6px">State<select id="engstate"><option value="">All states</option>${states.map((s) => `<option value="${s}" ${f.state === s ? "selected" : ""}>${s}${STATE_NAMES[s] ? " – " + esc(STATE_NAMES[s]) : ""}</option>`).join("")}</select></label>
      ${sel("engmode", "Work", [["", "Remote & on-site"], ["REMOTE", "Remote only"], ["WORLDWIDE", "Remote – open worldwide"], ["HYBRID", "Hybrid"], ["ONSITE", "On-site"]], f.mode)}
      ${sel("engage", "Posted", [["", "Any time"], ["1", "Past 24 hours"], ["3", "Past 3 days"], ["7", "Past week"], ["14", "Past 2 weeks"], ["30", "Past month"]], f.age)}
      ${industryLike ? sel("englevel", "Level", [["", "All levels"], ["fit", "Entry-level & not stated"], ["ENTRY", "Entry-level only"]], f.level) : ""}
      ${sel("engsponsor", "Visa", [["hide_citizen", "Hide citizenship / clearance-only"], ["offered", "Sponsorship mentioned only"], ["", "Show everything"]], f.sponsor)}
      ${sel("engsort", "Sort", [["fit", "Best fit"], ["newest", "Newest posted"], ["salary", "Highest salary"]], f.sort)}
      <label class="small row" style="gap:6px;cursor:pointer"><input type="checkbox" id="engpaid" ${f.paid ? "checked" : ""} style="width:auto">Salary posted only</label>
      <label class="small row" style="gap:6px;cursor:pointer"><input type="checkbox" id="engsaved" ${f.saved ? "checked" : ""} style="width:auto">Saved only</label>
      <span class="grow"></span><span class="small muted" id="engcount"></span></div>
    <div id="englist"></div>
    <div class="card" id="engapis" style="margin-top:14px"></div>
    <details class="card" style="margin-top:10px"><summary style="cursor:pointer;font-weight:600">Open job sites yourself (LinkedIn, Indeed, Glassdoor, …)</summary>
      <div class="row" style="gap:10px;margin:10px 0"><div class="search-box" style="max-width:340px"><span aria-hidden="true">⌕</span><input id="engsiteq" value="${esc(store.get("jh_eng_siteq_" + f.cat, ENG_SITE_QUERY[f.cat]))}"></div>
        <label class="small row" style="gap:6px;cursor:pointer"><input type="checkbox" id="engsiteremote" ${store.get("jh_eng_siteremote", false) ? "checked" : ""} style="width:auto">Remote jobs</label></div>
      <div class="row" id="engsites" style="gap:8px"></div></details>
    <div class="tiny muted" style="margin-top:10px">${industryLike
      ? `Read automatically from the official job boards of ${d.sources.companies.length} U.S. companies (${esc(d.sources.companies.join(", "))}) and from ${esc(d.sources.boards.join(", "))}.`
      : `Sources: ${esc(d.sources.instructor.join(", "))}.`}
      ${ls ? ` · Last search ${fmtDT(ls.finished_at)}` : " · Not searched yet — click Search now"}</div>`;
  const drawSites = () => {
    const q = $("#engsiteq").value.trim() || ENG_SITE_QUERY[f.cat], remote = $("#engsiteremote").checked;
    store.set("jh_eng_siteq_" + f.cat, q); store.set("jh_eng_siteremote", remote);
    $("#engsites").innerHTML = engSiteLinks(q, remote).map(([n, u]) => `<a class="btn sm" target="_blank" rel="noopener" href="${esc(u)}">${esc(n)} ↗</a>`).join("");
  };
  $("#engsiteq").addEventListener("input", drawSites);
  $("#engsiteremote").onchange = drawSites;
  drawSites();
  engApis();
  let limit = 60;
  const render = (more) => {
    limit = more === true ? limit + 60 : more === "keep" ? limit : 60;
    const ff = { cat: $("#engcat").value, q: $("#engq").value.trim().toLowerCase(), state: $("#engstate").value,
      level: $("#englevel") ? $("#englevel").value : "", sponsor: $("#engsponsor").value, sort: $("#engsort").value,
      saved: $("#engsaved").checked, paid: $("#engpaid").checked, mode: $("#engmode").value, age: $("#engage").value };
    store.set("jh_eng", ff);
    if (ff.cat !== f.cat) { viewEngineering(); return; }
    S.engSkills = mySk;
    S.eng.items.forEach(engRescore);
    const maxAge = ff.age ? Number(ff.age) : null;
    let rows = S.eng.items.filter((x) => (!mySk.size || x.my_skills.length) && (!ff.q || [x.title, x.company, x.location, x.source, ...(x.skills || [])].join(" ").toLowerCase().includes(ff.q))
      && (!ff.state || x.state === ff.state)
      && (!ff.mode || (ff.mode === "WORLDWIDE" ? x.remote_scope === "WORLDWIDE" : x.work_mode === ff.mode))
      && (maxAge === null || (x.days_old !== null && x.days_old < maxAge))
      && (!ff.level || (ff.level === "ENTRY" ? x.level === "ENTRY" : ["ENTRY", "UNKNOWN"].includes(x.level)))
      && (ff.sponsor === "" || (ff.sponsor === "offered" ? x.sponsorship === "OFFERED" && !x.citizenship_required : !x.citizenship_required))
      && (!ff.saved || x.is_saved) && (!ff.paid || x.salary_text));
    if (ff.sort === "fit") rows.sort((a, b) => b.fit - a.fit || (b.posted || "").localeCompare(a.posted || ""));
    if (ff.sort === "newest") rows.sort((a, b) => (b.posted || "").localeCompare(a.posted || ""));
    if (ff.sort === "salary") rows.sort((a, b) => (b.salary_annual || 0) - (a.salary_annual || 0));
    $("#engcount").textContent = `${rows.length} opening${rows.length === 1 ? "" : "s"}`;
    $("#englist").innerHTML = rows.length ? `<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(360px,1fr))">${rows.slice(0, limit).map(engCard).join("")}</div>
      ${rows.length > limit ? `<div style="text-align:center;margin-top:12px"><button class="btn" id="engmore">Show more (${rows.length - limit} left)</button></div>` : ""}`
      : `<div class="card empty"><b>No openings match</b>${S.eng.items.length ? "Loosen the filters above." : "Click Search now (top right) to look for openings. It takes a few minutes."}</div>`;
    if ($("#engmore")) $("#engmore").onclick = () => render(true);
  };
  S.engRender = render;
  const saveSk = () => { store.set("jh_eng_skills", [...mySk]); $$("#engskills .skill-pick").forEach((l) => l.classList.toggle("on", mySk.has(l.querySelector("input").value))); render(); };
  $$("#engskills input").forEach((c) => c.onchange = () => { c.checked ? mySk.add(c.value) : mySk.delete(c.value); saveSk(); });
  $("#engskall").onclick = () => { $$("#engskills input").forEach((c) => { c.checked = true; mySk.add(c.value); }); saveSk(); };
  $("#engskreset").onclick = () => { mySk.clear(); d.default_skills.forEach((s) => mySk.add(s)); $$("#engskills input").forEach((c) => c.checked = mySk.has(c.value)); saveSk(); };
  $("#engq").addEventListener("input", () => render());
  ["#engcat", "#engstate", "#englevel", "#engsponsor", "#engsort", "#engsaved", "#engpaid", "#engmode", "#engage"].forEach((s) => { if ($(s)) $(s).onchange = () => render(); });
  render();
}
// Keyed job-search APIs: bring LinkedIn / Indeed / Glassdoor / ZipRecruiter listings into the app.
async function engApis() {
  const box = $("#engapis");
  if (!box) return;
  let d;
  try { d = await api("/api/engineering/apis"); } catch (e) {
    box.innerHTML = `<h3 style="margin-top:0">Show LinkedIn, Indeed, Glassdoor &amp; ZipRecruiter jobs inside this app</h3>
      <div class="notice warn small">This part of the page couldn't load (${esc(e.message)}). The app was probably started before this feature was added —
      close the USA Job Hunter window and start it again with <b>Start USA Job Hunter.bat</b>, then reopen this page.</div>`;
    return;
  }
  const st = (k) => Object.entries(d.last_status || {}).find(([n]) => n.startsWith(k))?.[1];
  const status = (k, set) => {
    const s = st(k);
    const b = (cls, txt) => `<div style="margin-top:6px"><span class="badge ${cls}" style="white-space:normal;line-height:1.35">${esc(txt)}</span></div>`;
    if (!set) return b("b-unk", "Not connected");
    if (!s) return b("b-info", "Key saved — click Search now");
    return b(s.startsWith("OK") ? "b-good" : s.startsWith("Error") ? "b-bad" : "b-info", s);
  };
  const field = (id, label, val) => `<label class="small" style="display:grid;gap:3px">${label}
    <input type="password" id="${id}" autocomplete="off" placeholder="${val ? esc(val) + " (saved — type to replace)" : "Paste here"}"></label>`;
  box.innerHTML = `<h3 style="margin-top:0">Show LinkedIn, Indeed, Glassdoor &amp; ZipRecruiter jobs inside this app</h3>
    <p class="small muted" style="margin-top:0">These sites don't allow apps to read their pages, but two official job-search APIs are licensed to share their listings.
      Each needs a <b>free key that you create yourself</b> (about 2 minutes). Paste the keys here once — every <b>Search now</b> then adds their jobs to the lists above,
      marked with where they were posted (for example "LinkedIn (via JSearch)"). Copies of jobs already found on an employer's own job page are skipped.</p>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px">
      <div class="card" style="background:var(--surface-2)"><b>JSearch</b>${status("JSearch", d.keys.jsearch_key)}
        <div class="small muted" style="margin:4px 0 8px">Google-for-Jobs listings: LinkedIn, Indeed, Glassdoor, ZipRecruiter and company sites.</div>
        <ol class="small" style="margin:0 0 8px;padding-left:18px"><li>Open <a target="_blank" rel="noopener" href="https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch">JSearch on RapidAPI ↗</a>, sign up, and subscribe to the free <b>Basic</b> plan.</li>
          <li>Copy your <b>X-RapidAPI-Key</b> and paste it below.</li></ol>
        ${field("apijs", "X-RapidAPI-Key", d.keys.jsearch_key)}
        <div class="tiny muted" style="margin-top:6px">The free plan has a monthly request limit, so JSearch runs at most about once a day (one request per search term).</div></div>
      <div class="card" style="background:var(--surface-2)"><b>Adzuna</b>${status("Adzuna", d.keys.adzuna_app_id && d.keys.adzuna_app_key)}
        <div class="small muted" style="margin:4px 0 8px">Large U.S. job aggregator collecting postings from thousands of job sites and employers.</div>
        <ol class="small" style="margin:0 0 8px;padding-left:18px"><li>Register at <a target="_blank" rel="noopener" href="https://developer.adzuna.com/signup">developer.adzuna.com ↗</a>.</li>
          <li>Copy the <b>Application ID</b> and <b>Application Key</b> from your dashboard.</li></ol>
        <div class="grid" style="gap:6px">${field("apiadzid", "Application ID", d.keys.adzuna_app_id)}${field("apiadzkey", "Application Key", d.keys.adzuna_app_key)}</div></div>
    </div>
    <label class="small" style="display:grid;gap:3px;margin-top:12px"><b>Search terms</b> <span class="tiny muted">one per line — used by both APIs (each line is one JSearch request)</span>
      <textarea id="apiq" rows="4" style="max-width:520px">${esc(d.queries.join("\n"))}</textarea></label>
    <div class="row" style="margin-top:10px;gap:8px"><button class="btn primary" id="apisave">Save</button>
      ${d.keys.jsearch_key ? `<button class="btn sm" id="apijsdel">Remove JSearch key</button>` : ""}
      ${d.keys.adzuna_app_id ? `<button class="btn sm" id="apiadzdel">Remove Adzuna keys</button>` : ""}
      <span class="tiny muted">Keys are stored only in this app's database on your computer and are never shown again in full.</span></div>`;
  const put = async (body, msg) => { await api("/api/engineering/apis", { method: "PUT", body }); toast(msg); engApis(); };
  $("#apisave").onclick = () => {
    const body = { queries: $("#apiq").value.split("\n") };
    if ($("#apijs").value.trim()) body.jsearch_key = $("#apijs").value;
    if ($("#apiadzid").value.trim()) body.adzuna_app_id = $("#apiadzid").value;
    if ($("#apiadzkey").value.trim()) body.adzuna_app_key = $("#apiadzkey").value;
    put(body, "Saved — click Search now to load the jobs");
  };
  if ($("#apijsdel")) $("#apijsdel").onclick = () => put({ jsearch_key: "" }, "JSearch key removed");
  if ($("#apiadzdel")) $("#apiadzdel").onclick = () => put({ adzuna_app_id: "", adzuna_app_key: "" }, "Adzuna keys removed");
}
// Re-score a posting against the skills the user has checked (other parts of the score are unchanged).
function engRescore(x) {
  x.my_skills = x.skills.filter((s) => S.engSkills.has(s));
  x.fit = Math.max(0, (x.match_score || 0) - (x.skill_points || 0) + Math.min(40, x.my_skills.length * 10));
  x.why_now = [...(x.my_skills.length ? [`Matches your checked skills: ${x.my_skills.join(", ")}`] : []), ...x.why.filter((w) => !w.startsWith("Matches your background"))];
}
// Google Jobs search for one specific posting (title + employer + city); its results link to the employer's
// own page, LinkedIn, Indeed, etc. Used for Adzuna, whose pages are blocked outside the U.S.
function engFindOriginal(x) {
  const city = (x.location || "").replace(/^Remote – /, "").split(",")[0];
  return `https://www.google.com/search?q=${encodeURIComponent([x.title, x.company, city].filter(Boolean).join(" "))}&ibp=htl;jobs`;
}
function engCard(x) {
  return `<div class="card" style="display:flex;flex-direction:column;gap:8px">
    <div class="row between" style="align-items:flex-start;flex-wrap:nowrap">
      <div style="min-width:0"><div style="font-weight:700;font-size:15px">${esc(x.title)}</div>
        <div class="small">${esc(x.company || "")}${x.location ? " · " + esc(x.location) : ""}</div>
        <div class="tiny muted">${esc(x.source)}</div></div>
      <span class="match ${x.fit >= 70 ? "hi" : x.fit < 45 ? "lo" : ""}" title="How well the posting fits your checked skills and profile">${x.fit}%<small>FIT</small></span></div>
    <div class="row small" style="gap:6px 16px">
      <span title="Pay exactly as posted by the employer">💵 ${x.salary_text ? `<b>${esc(x.salary_text)}</b>` : `<span class="muted">Salary not posted</span>`}</span>
      <span title="Date the employer posted this opening">📅 ${x.posted ? `Posted <b>${fmtDate(x.posted)}</b> <span class="muted">(${esc(ago(x.days_old))})</span>` : `<span class="muted">Posting date not listed</span>`}</span></div>
    <div class="row" style="gap:5px">${x.remote_scope === "WORLDWIDE" ? `<span class="badge b-good" title="The job board lists this remote role as open to applicants in any country">🌍 Remote – open worldwide</span>` : badge(ENG_MODE, x.work_mode)}
      ${x.category !== "INSTRUCTOR" ? badge(ENG_LEVEL, x.level) : ""}${badge(ENG_SPONSOR, x.sponsorship)}
      ${x.citizenship_required ? `<span class="badge b-bad">✕ U.S. citizenship / clearance</span>` : ""}${x.phd_required ? `<span class="badge b-warn">PhD mentioned</span>` : ""}
      ${x.years_required ? `<span class="badge b-info">${x.years_required}+ yrs experience</span>` : ""}${x.applied_on ? `<span class="badge b-good">Applied ${fmtDate(x.applied_on)}</span>` : ""}</div>
    ${x.skills.length ? `<div class="chips">${x.skills.map((s) => `<span class="chip ${S.engSkills.has(s) ? "chip-on" : "muted"}">${S.engSkills.has(s) ? "✓ " : ""}${esc(s)}</span>`).join("")}</div>` : ""}
    <details><summary class="small" style="cursor:pointer;font-weight:600">Why it fits / gaps</summary>
      <ul class="checks" style="margin-top:6px">${x.why_now.map((w) => `<li><span class="ok">✓</span>${esc(w)}</li>`).join("")}${x.gaps.map((g) => `<li><span class="no">⚠</span>${esc(g)}</li>`).join("")}</ul>
      ${x.snippet ? `<div class="desc small" style="max-height:160px;margin-top:6px">${esc(x.snippet)}…</div>` : ""}</details>
    <div class="row" style="margin-top:auto">${x.job_id ? `<a class="btn sm" href="#/job/${x.job_id}">View job</a>` : ""}
      ${x.source === "Adzuna"
        ? `<a class="btn sm primary" target="_blank" rel="noopener" href="${esc(engFindOriginal(x))}" title="Adzuna's own job pages only open from inside the U.S. This searches Google Jobs for the employer's original posting.">Find original posting ↗</a>
           <a class="btn sm" target="_blank" rel="noopener" href="${esc(x.url)}" title="Adzuna blocks visitors outside the U.S.">Adzuna page (U.S. only)</a>`
        : `<a class="btn sm primary" target="_blank" rel="noopener" href="${esc(x.url)}">View posting ↗</a>`}
      <button class="btn sm" onclick="engToggle(${x.id},'save')">${x.is_saved ? "♥ Saved" : "♡ Save"}</button>
      <button class="btn sm" onclick="engToggle(${x.id},'applied')">${x.applied_on ? "✓ Applied" : "Mark applied"}</button></div></div>`;
}
window.engToggle = async (id, what) => {
  const r = await api(`/api/engineering/${id}/${what === "save" ? "save" : "applied"}`, { method: "POST" });
  const i = S.eng.items.findIndex((x) => x.id === id); if (i >= 0) S.eng.items[i] = r;
  S.engRender("keep");
};

// ------------------------------------------------------------------ H-1B sponsors
const H1B_HOW = {
  LIVE: ["b-good", "● Live board"], SCANS_ONLY: ["b-info", "◐ From national scans"], UNREADABLE: ["b-unk", "○ Can't read automatically"],
};
async function viewH1B() {
  const d = await api("/api/h1b");
  S.h1b = d.employers;
  const f = store.get("jh_h1b", { q: "", show: "", sort: "rank" });
  const withJobs = d.employers.filter((e) => e.jobs.length), total = d.employers.reduce((n, e) => n + e.jobs.length, 0);
  const checked = d.employers.filter((e) => e.last_checked).map((e) => e.last_checked).sort().pop();
  $("#view").innerHTML = `<div class="page-head"><div><h1>H-1B Sponsors</h1><p>Employers from your H-1B sponsor list, checked for current Mathematics &amp; STEM teaching openings.</p></div>
    <button class="btn primary" onclick="startScan('H1B')">Check all now</button></div>
    <div class="notice small" style="margin-bottom:12px">Ranks, average salaries and H-1B history come from <b>your list</b>. A past H-1B filing doesn't guarantee sponsorship for a specific vacancy — confirm with each employer's HR before applying.</div>
    <div class="kpis" style="grid-template-columns:repeat(4,minmax(0,1fr))">
      <div class="kpi"><div class="lbl">Employers</div><div class="val">${d.employers.length}</div></div>
      <div class="kpi"><div class="lbl">With Math/STEM openings</div><div class="val">${withJobs.length}</div></div>
      <div class="kpi"><div class="lbl">Math/STEM openings</div><div class="val">${total}</div></div>
      <div class="kpi"><div class="lbl">Last checked</div><div class="val" style="font-size:16px;margin-top:10px">${checked ? fmtDT(checked) : "Not yet — click Check all now"}</div></div></div>
    <div class="toolbar"><div class="search-box"><span aria-hidden="true">⌕</span><input id="h1bq" placeholder="Search employer or state…" value="${esc(f.q)}"></div>
      <label class="small muted row" style="gap:6px">Show<select id="h1bshow">${[["", "All employers"], ["jobs", "With Math/STEM openings"], ["LIVE", "Live boards"], ["SCANS_ONLY", "From national scans"], ["UNREADABLE", "Can't read automatically"]].map(([v, l]) => `<option value="${v}" ${f.show === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="small muted row" style="gap:6px">Sort<select id="h1bsort">${[["rank", "Rank"], ["openings", "Most openings"], ["salary", "Highest salary"]].map(([v, l]) => `<option value="${v}" ${f.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <span class="grow"></span><span class="small muted" id="h1bcount"></span></div>
    <div class="card flush"><div class="scroll" style="max-height:calc(100vh - 360px)" id="h1btable"></div></div>`;
  const render = () => {
    const ff = { q: $("#h1bq").value.trim().toLowerCase(), show: $("#h1bshow").value, sort: $("#h1bsort").value };
    store.set("jh_h1b", ff);
    let rows = S.h1b.filter((e) => (!ff.q || `${e.name} ${e.state || ""}`.toLowerCase().includes(ff.q))
      && (!ff.show || (ff.show === "jobs" ? e.jobs.length : e.status === ff.show)));
    rows.sort({ rank: (a, b) => a.rank - b.rank, openings: (a, b) => b.jobs.length - a.jobs.length || a.rank - b.rank,
      salary: (a, b) => (b.avg_salary || 0) - (a.avg_salary || 0) }[ff.sort]);
    $("#h1bcount").textContent = `${rows.length} employer${rows.length === 1 ? "" : "s"}`;
    $("#h1btable").innerHTML = `<table class="tbl apptbl"><thead><tr><th>#</th><th>Employer</th><th>Avg salary (your list)</th><th>Math/STEM openings</th><th>How it's checked</th><th>Last checked</th><th></th></tr></thead><tbody>
      ${rows.map((e) => `<tr data-e="${e.id}">
        <td class="muted">${e.rank}</td>
        <td><b>${esc(e.name)}</b> ${e.state ? `<span class="badge b-info">${esc(e.state)}</span>` : ""}${e.total_openings != null ? `<div class="tiny muted">${e.total_openings} total posting${e.total_openings === 1 ? "" : "s"} on its board</div>` : ""}</td>
        <td class="nowrap">${e.avg_salary ? fmtMoney(e.avg_salary) : "—"}</td>
        <td>${e.jobs.length ? `<button class="btn sm primary" onclick="toggleH1B(${e.id})">${e.jobs.length} opening${e.jobs.length === 1 ? "" : "s"} ▾</button>` : `<span class="muted small">${e.last_checked ? "None right now" : "Not checked yet"}</span>`}</td>
        <td>${e.status ? badge(H1B_HOW, e.status) : `<span class="badge b-unk">○ Not checked</span>`}<div class="tiny muted" style="max-width:340px">${esc(e.status_detail || "")}</div></td>
        <td class="nowrap small">${e.last_checked ? fmtDT(e.last_checked) : "—"}</td>
        <td class="nowrap"><button class="btn sm" onclick="checkH1B(${e.id}, this)">Check now</button> <a class="btn sm" target="_blank" rel="noopener" href="${esc(e.board_url || e.careers_url)}">Careers ↗</a></td></tr>
        <tr class="h1b-jobs hidden" id="h1bj-${e.id}"><td></td><td colspan="6">${e.jobs.map((j) => `<div class="row" style="gap:8px;padding:5px 0;border-bottom:1px solid var(--line-2);flex-wrap:nowrap">
          <a class="btn sm" href="#/job/${j.id}">View job</a>
          <span style="flex:1;min-width:0"><a href="#/job/${j.id}"><b>${esc(j.job_title)}</b></a>${j.applied ? ` <span class="badge b-good">Applied</span>` : ""}
            <span class="small muted"> · ${esc([j.school, j.city, j.state].filter(Boolean).join(", "))}</span>
            <span class="tiny" style="display:block;color:var(--ink-2)">Posted ${esc(ago(j.days_old))}${j.date_posted ? " · " + fmtDate(j.date_posted) : ""}${j.salary_text ? " · " + esc(j.salary_text) : ""}</span></span>
          ${matchBox(j.match_score)}${j.application_url ? `<a class="btn sm primary" target="_blank" rel="noopener" href="${esc(j.application_url)}">Apply ↗</a>` : ""}</div>`).join("")}</td></tr>`).join("")
        || `<tr><td colspan="7" class="muted" style="padding:20px">No employers match.</td></tr>`}</tbody></table>`;
  };
  $("#h1bq").addEventListener("input", render);
  $("#h1bshow").onchange = render; $("#h1bsort").onchange = render;
  render();
}
window.toggleH1B = (id) => $(`#h1bj-${id}`).classList.toggle("hidden");
window.checkH1B = async (id, btn) => {
  btn.disabled = true; btn.textContent = "Checking…";
  try {
    const e = await api(`/api/h1b/${id}/check`, { method: "POST" });
    toast(`${e.name}: ${e.jobs.length} Math/STEM opening${e.jobs.length === 1 ? "" : "s"}${e.status === "UNREADABLE" ? " — " + (e.status_detail || "") : ""}`, 6000);
    const i = S.h1b.findIndex((x) => x.id === id); if (i >= 0) S.h1b[i] = e;
    $("#h1bq").dispatchEvent(new Event("input"));
  } catch (err) { toast(err.message); btn.disabled = false; btn.textContent = "Check now"; }
};

// ------------------------------------------------------------------ job sites
async function viewJobSites() {
  const sites = await api("/api/job-sites");
  const auto = sites.filter((s) => s.auto), manual = sites.filter((s) => !s.auto);
  const card = (s) => `<div class="card" style="display:flex;flex-direction:column;gap:8px">
    <div class="row between"><h2 style="margin:0">${esc(s.name)}</h2>${s.auto
      ? (s.enabled ? `<span class="badge b-good">✓ Scanned automatically</span>` : `<span class="badge b-unk">○ Turned off</span>`)
      : `<span class="badge b-info">↗ Open to browse</span>`}</div>
    <div class="small">${esc(s.note)}</div>
    ${s.auto ? `<div class="tiny muted">${s.last_scanned ? `Last scanned ${fmtDT(s.last_scanned)} · ${s.last_jobs_found ?? 0} math/STEM job${s.last_jobs_found === 1 ? "" : "s"} found${s.last_status ? " · " + esc(s.last_status) : ""}` : "Not scanned yet — runs on the next scan"}</div>` : ""}
    <div class="row" style="margin-top:auto">${s.url ? `<a class="btn sm ${s.auto ? "" : "primary"}" target="_blank" rel="noopener" href="${esc(s.url)}">Open site ↗</a>` : `<a class="btn sm" href="#/monitor">Add a career page</a>`}</div></div>`;
  $("#view").innerHTML = `<div class="page-head"><div><h1>Job Sites</h1><p>Where the app looks for Mathematics teaching jobs. Scanned sites are read on every scan; the others are quick links you open yourself.</p></div>
    <button class="btn primary" onclick="$('#scanNow').click()">SCAN USA NOW</button></div>
    <h3>Scanned automatically</h3><div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(320px,1fr));margin-bottom:18px">${auto.map(card).join("")}</div>
    <h3>Quick links (browse yourself)</h3><div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(320px,1fr))">${manual.map(card).join("")}</div>`;
}

// ------------------------------------------------------------------ scan monitor
async function viewMonitor() {
  const [runs, sources] = await Promise.all([api("/api/scans"), api("/api/sources")]);
  $("#view").innerHTML = `<div class="page-head"><div><h1>Scan Monitor</h1><p>Every request the scanner makes, its HTTP status, crawl and parser outcome. District ATS platforms change often — check here when a source stops returning jobs.</p></div>
    <div class="row"><button class="btn" onclick="startScan('QUICK')">Quick scan</button><button class="btn" onclick="startScan('FULL')">Full national scan</button><button class="btn" onclick="startScan('VERIFY_JOBS')">Verify jobs</button><button class="btn" onclick="startScan('CLOSED_CHECK')">Closed job check</button></div></div>
  <div class="tabs"><button class="on" data-t="runs">Scan runs</button><button data-t="sources">Sources (${sources.length})</button></div><div id="monBody"></div>`;
  const showRuns = () => {
    $("#monBody").innerHTML = `<div class="two"><div class="card flush"><div class="scroll" style="max-height:640px"><table class="tbl"><thead><tr><th>#</th><th>Kind</th><th>Status</th><th>Started</th><th>Summary</th></tr></thead><tbody>
      ${runs.map((r) => `<tr style="cursor:pointer" onclick="showRun(${r.id})"><td>${r.id}</td><td>${esc(title(r.kind))}<div class="tiny muted">${esc(r.trigger)}</div></td><td>${badge({ COMPLETED: ["b-good", "✓ Completed"], RUNNING: ["b-info", "◷ Running"], FAILED: ["b-bad", "✕ Failed"], CANCELLED: ["b-unk", "○ Cancelled"] }, r.status)}</td><td class="nowrap small">${fmtDT(r.started_at)}</td><td class="small">${r.stats?.unique_jobs !== undefined ? `${r.stats.unique_jobs} jobs · ${r.stats.sources_checked} requests` : r.stats?.jobs_checked !== undefined ? `${r.stats.jobs_checked} checked` : esc(r.progress || "")}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">No scans yet.</td></tr>`}</tbody></table></div></div><div id="runDetail" class="card"><div class="muted small">Select a run to see its summary and fetch log.</div></div></div>`;
    if (runs[0]) showRun(runs[0].id);
  };
  const showSources = () => {
    $("#monBody").innerHTML = `<div class="card flush"><div class="scroll" style="max-height:600px"><table class="tbl"><thead><tr><th>On</th><th>Source</th><th>Connector</th><th>Tier</th><th>State / City</th><th>Last scanned</th><th>Status</th><th>Jobs found</th><th>Error</th></tr></thead><tbody>
    ${sources.map((s) => `<tr><td><input type="checkbox" ${s.enabled ? "checked" : ""} onchange="toggleSource(${s.id},this.checked)" style="width:auto"></td><td><b>${esc(s.name)}</b><div class="tiny mono">${esc(s.config.board_url || s.config.url || (s.connector === "schoolspring" ? "api.schoolspring.com" : ""))}</div></td><td>${esc(s.connector)}</td><td>${s.tier}</td><td>${esc([s.state, s.city].filter(Boolean).join(" · "))}</td><td class="small nowrap">${fmtDT(s.last_scanned)}</td>
      <td>${s.last_status ? badge({ OK: ["b-good", "✓ OK"], ERROR: ["b-bad", "✕ Error"], ROBOTS_BLOCKED: ["b-warn", "⊘ robots.txt"] }, s.last_status) : `<span class="muted small">never</span>`}</td><td>${s.last_jobs_found ?? ""}</td><td class="small">${esc((s.last_error || "").slice(0, 160))}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="card" style="margin-top:14px"><h2>Add official source</h2><p class="small muted">Tier 1 = official district/school/state site; Tier 2 = official ATS. The scanner respects robots.txt and rate limits and never bypasses logins or CAPTCHAs.</p>
    <form class="form" id="srcf"><div class="cols"><label>Name<input name="name" required placeholder="Example ISD careers"></label><label>Connector<select name="connector"><option value="applitrack">Frontline AppliTrack board</option><option value="jsonld_page">Official careers page (schema.org JobPosting)</option></select></label></div>
    <div class="cols"><label>AppliTrack slug (applitrack.com/<b>slug</b>/onlineapp)<input name="client"></label><label>Official page URL (for JobPosting pages)<input name="url"></label></div>
    <div class="cols"><label>District name<input name="district_name"></label><label>Detail link regex (optional)<input name="link_pattern" placeholder="/jobs/\\d+"></label></div>
    <div class="cols"><label>State<input name="state" maxlength="2"></label><label>City<input name="city"></label></div><button class="btn primary">Add source</button></form></div>`;
    $("#srcf").onsubmit = async (e) => {
      e.preventDefault(); const b = Object.fromEntries(new FormData(e.target));
      const config = b.connector === "applitrack" ? { client: b.client.trim(), district_name: b.district_name || b.name, board_url: `https://www.applitrack.com/${b.client.trim()}/onlineapp/default.aspx` } : { url: b.url.trim(), employer_name: b.district_name || b.name, ...(b.link_pattern ? { link_pattern: b.link_pattern } : {}) };
      try { await api("/api/sources", { method: "POST", body: { name: b.name, connector: b.connector, config, state: b.state.toUpperCase() || null, city: b.city || null, tier: b.connector === "applitrack" ? 2 : 1 } }); toast("Source added"); viewMonitor(); }
      catch (err) { toast(err.message); }
    };
  };
  $$(".tabs button").forEach((b) => (b.onclick = () => { $$(".tabs button").forEach((x) => x.classList.toggle("on", x === b)); (b.dataset.t === "runs" ? showRuns : showSources)(); }));
  showRuns();
}
window.toggleSource = async (id, on) => { await api(`/api/sources/${id}`, { method: "PATCH", body: { enabled: on } }); toast(on ? "Enabled" : "Disabled"); };
window.showRun = async (id) => {
  const [r, logs] = await Promise.all([api(`/api/scans/${id}`), api(`/api/scans/${id}/logs`)]);
  $("#runDetail").innerHTML = `<h2>Run #${r.id} — ${esc(title(r.kind))}</h2>${scanSummary(r)}
    ${r.status === "RUNNING" ? `<button class="btn sm danger" style="margin-top:8px" onclick="api('/api/scans/${r.id}/cancel',{method:'POST'})">Cancel</button>` : ""}
    <h3 style="margin-top:14px">Fetch log (${r.log_count})</h3><div class="scroll" style="max-height:420px"><table class="tbl"><thead><tr><th>Source</th><th>URL</th><th>HTTP</th><th>Crawl</th><th>Parser</th><th>Jobs</th><th>ms</th><th>Error</th></tr></thead><tbody>
    ${logs.map((l) => `<tr><td class="small">${esc(l.source || "")}</td><td class="tiny mono"><a target="_blank" rel="noopener" href="${esc(l.url)}">${esc(l.url.length > 70 ? l.url.slice(0, 70) + "…" : l.url)}</a></td><td>${esc(l.http_status ?? "—")}</td><td>${esc(l.crawl_status)}</td><td>${esc(l.parser_status || "")}</td><td>${l.jobs_discovered || ""}</td><td>${l.elapsed_ms ?? ""}</td><td class="small">${esc(l.error || "")}</td></tr>`).join("")}</tbody></table></div>`;
};
window.api = api;

// ------------------------------------------------------------------ scanning
window.startScan = async (kind) => {
  try {
    const r = await api("/api/scans", { method: "POST", body: { kind } });
    if (r.dispatched) { toast(`${title(kind)} started in the cloud — results appear in about 15–30 minutes and you'll get an email.`, 7000); return; }
    S.scanRun = r.run_id; toast(`${title(kind)} started`); pollScan();
  }
  catch (e) { toast(e.message); }
};
$("#scanNow").onclick = async () => {
  const f = S.facets || await api("/api/jobs/facets");
  openModal(`<h2>SCAN USA</h2><p class="small muted">Searches official district job boards (Frontline) and SchoolSpring nationwide for Mathematics / STEM teaching vacancies, then de-duplicates and verifies them. Requests are rate-limited and respect robots.txt, so a full scan takes several minutes.</p>
  <form class="form" id="scanf"><label>Scope<select name="kind"><option value="QUICK">Quick scan — nationwide, main math keywords</option><option value="FULL">Full national scan — all search targets (Algebra, Calculus, STEM, Physics, CS…)</option></select></label>
  <label>Limit to states (optional, comma)<input name="states" placeholder="e.g. TX, LA, AZ, NC"></label><button class="btn primary">Start scan</button></form>`);
  $("#scanf").onsubmit = async (e) => {
    e.preventDefault(); const b = Object.fromEntries(new FormData(e.target));
    try { const r = await api("/api/scans", { method: "POST", body: { kind: b.kind, states: b.states.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean) } }); closeModal(); if (r.dispatched) { toast("Scan started in the cloud — you'll get an email with new openings in about 15–30 minutes.", 7000); return; } S.scanRun = r.run_id; toast("Scan started"); pollScan(); }
    catch (err) { toast(err.message); }
  };
};
async function pollScan() {
  clearTimeout(S._poll);
  try {
    const runs = await api("/api/scans");
    const running = runs.find((r) => r.status === "RUNNING");
    const pill = $("#scanPill");
    if (running) {
      S.scanRun = running.id;
      pill.textContent = `◷ ${title(running.kind)}: ${running.progress || "working"}`;
      pill.classList.remove("hidden");
      $("#scanNow").disabled = true;
      S._poll = setTimeout(pollScan, 3000);
    } else {
      pill.classList.add("hidden"); $("#scanNow").disabled = false;
      if (S.scanRun) {
        const done = runs.find((r) => r.id === S.scanRun); S.scanRun = null; S.facets = null;
        if (done) openModal(`<h2>${done.status === "COMPLETED" ? "SCAN COMPLETED" : "SCAN " + esc(done.status)}</h2>${scanSummary(done)}<p class="tiny muted">All counts come from this run's stored records.</p><div class="row" style="margin-top:10px"><button class="btn primary" onclick="closeModal();location.hash='#/jobs';route()">View jobs</button><button class="btn" onclick="closeModal();location.hash='#/monitor'">Open Scan Monitor</button></div>`);
        const cur = (location.hash.replace(/^#\/?/, "") || "dashboard").split("/")[0];
        if (["dashboard", "jobs", "map", "high", "monitor", "h1b", "engineering", "applications", "outbox"].includes(cur)) renderView(cur);
        else checkOutbox();
      }
    }
  } catch { S._poll = setTimeout(pollScan, 8000); }
}

// ------------------------------------------------------------------ résumé upload
$("#uploadResumeBtn").onclick = () => $("#resumeFile").click();
$("#resumeFile").onchange = async (e) => {
  const file = e.target.files[0]; if (!file) return;
  const fd = new FormData(); fd.append("file", file); fd.append("apply_to_profile", "true");
  toast("Parsing résumé…");
  try {
    const r = await api("/api/resumes", { method: "POST", body: fd });
    const p = r.parsed;
    const li = (k, l) => (p[k] && p[k].length) ? `<h3 style="margin-top:10px">${l}</h3><div class="chips">${p[k].map((x) => `<span class="chip">${esc(typeof x === "string" ? x : x.text)}</span>`).join("")}</div>` : "";
    openModal(`<h2>Résumé parsed</h2><p class="small">Profile updated from <b>${esc(file.name)}</b>; <b>${r.rescored_jobs}</b> job match scores recalculated. Review the extracted items in Settings and correct anything the parser misread.</p>
      <dl class="kv"><dt>Name</dt><dd>${esc(p.full_name || "—")}</dd><dt>Experience</dt><dd>${p.years_experience ? p.years_experience + " years" : "Not detected"}</dd></dl>
      ${li("education", "Education")}${li("licenses", "Licenses / certifications")}${li("subjects", "Subjects")}${li("grade_levels", "Grade levels")}${li("leadership", "Leadership")}${li("technologies", "Technologies")}${li("awards", "Awards")}${li("research_stem", "Research / STEM")}
      <div class="row" style="margin-top:12px"><button class="btn primary" onclick="closeModal();location.hash='#/settings'">Review profile</button><button class="btn" onclick="closeModal()">Close</button></div>`);
  } catch (err) { toast(err.message, 6000); }
  e.target.value = "";
};

// ------------------------------------------------------------------ misc wiring
let searchT;
$("#globalSearch").addEventListener("input", () => {
  clearTimeout(searchT);
  searchT = setTimeout(() => {
    const cur = (location.hash.replace(/^#\/?/, "") || "dashboard").split("/")[0];
    if (["jobs", "high", "saved"].includes(cur)) { S.page = 1; loadResults(cur); } else if (cur === "j1" && $("#results")) loadResults("j1");
    else location.hash = "#/jobs";
  }, 350);
});
$("#menuBtn").onclick = () => $("#sidebar").classList.toggle("open");
$("#logout").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); showAuth(); };
applyTheme();
boot().catch(() => showAuth());
