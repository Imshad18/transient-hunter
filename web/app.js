/* Transient Hunter front-end */
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 2) => (v === null || v === undefined || !isFinite(v) ? "—" : Number(v).toFixed(d));
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const BAND_COLOR = { g: "--c3", r: "--c2", i: "--c4" };
const D2R = Math.PI / 180;
const state = { scan: null, view: [], filter: "all", sort: { key: "score", dir: -1 }, sel: null, lat: 20, lon: 0 };

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 3500);
}
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
const mjdToDate = (m) => new Date((m - 40587) * 86400000);

/* ---------- observability ---------- */
function jd(d) { return d.getTime() / 86400000 + 2440587.5; }
function gmstDeg(d) { const T = (jd(d) - 2451545) / 36525; return (280.46061837 + 360.98564736629 * (jd(d) - 2451545) + 0.000387933 * T * T) % 360; }
function altitude(raDeg, decDeg, d, lat, lon) {
  const H = (gmstDeg(d) + lon - raDeg) * D2R;
  return Math.asin(Math.sin(lat * D2R) * Math.sin(decDeg * D2R) + Math.cos(lat * D2R) * Math.cos(decDeg * D2R) * Math.cos(H)) / D2R;
}
function sunRaDec(d) {
  const n = jd(d) - 2451545, L = (280.46 + 0.9856474 * n) % 360, g = (357.528 + 0.9856003 * n) * D2R;
  const lam = (L + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g)) * D2R, eps = 23.439 * D2R;
  return [Math.atan2(Math.cos(eps) * Math.sin(lam), Math.cos(lam)) / D2R, Math.asin(Math.sin(eps) * Math.sin(lam)) / D2R];
}
function tonightGrid() {
  // the next 16 hours in 10-minute steps; "dark" means the Sun is more than 12° below the horizon
  if (state.grid && Date.now() - state.grid.made < 600e3 && state.grid.lat === state.lat && state.grid.lon === state.lon) return state.grid;
  const t0 = Date.now(), times = [], dark = [];
  for (let k = 0; k <= 96; k++) {
    const d = new Date(t0 + k * 600e3), [sra, sdec] = sunRaDec(d);
    times.push(d); dark.push(altitude(sra, sdec, d, state.lat, state.lon) < -12);
  }
  state.grid = { times, dark, made: Date.now(), lat: state.lat, lon: state.lon };
  return state.grid;
}
function observableHours(c) {
  const g = tonightGrid();
  let n = 0;
  g.times.forEach((d, k) => { if (g.dark[k] && altitude(c.ra, c.dec, d, state.lat, state.lon) > 30) n++; });
  return n / 6;
}

/* ---------- scans ---------- */
async function loadScans(file) {
  const scans = await api("/api/scans");
  $("#scanSelect").innerHTML = scans.length ? scans.map((s) => `<option value="${esc(s.file)}">${esc(s.created.slice(0, 16).replace("T", " "))} UTC · ${s.days} d · ${s.n}</option>`).join("")
    : `<option value="">No scans yet</option>`;
  const f = file || scans[0]?.file;
  if (f) { $("#scanSelect").value = f; await openScan(f); }
}
$("#scanSelect").onchange = (e) => e.target.value && openScan(e.target.value);

async function openScan(file) {
  const s = await api(`/api/scans/${encodeURIComponent(file)}`);
  state.scan = s; state.scanFile = file;
  recompute();
  const c = s.candidates;
  const median = (a) => { const b = a.filter((x) => x != null).sort((x, y) => x - y); return b.length ? b[Math.floor(b.length / 2)] : null; };
  $("#metrics").innerHTML = [
    m("Transients analysed", c.length, `of ${s.queried} alerts, ${s.days} d window`),
    m("Still rising", c.filter((x) => x.rising).length, "brightening in the last week"),
    m("Brighter than 18.5", c.filter((x) => x.last_mag < 18.5).length, "reachable with small telescopes"),
    m("Under 5 days old", c.filter((x) => x.age_days < 5).length, "since first detection"),
    m("Median magnitude", fmt(median(c.map((x) => x.last_mag)), 1), "latest detection"),
    m("Scan", `${fmt(s.runtime_s, 0)} s`, s.created.slice(0, 16).replace("T", " ") + " UTC"),
  ].join("");
  applyFilter();
  sky();
  if (state.view.length) select(state.view[0]);
}
const m = (k, v, e) => `<div class="metric"><div class="k">${k}</div><div class="v">${v}</div><div class="e">${e}</div></div>`;
function recompute() { for (const c of state.scan?.candidates || []) c.tonight = observableHours(c); }

/* ---------- table ---------- */
function applyFilter() {
  const f = state.filter;
  state.view = state.scan.candidates.filter((c) =>
    f === "all" || (f === "rising" && c.rising) || (f === "bright" && c.last_mag < 18.5) || (f === "young" && c.age_days < 5) || (f === "tonight" && c.tonight >= 1));
  const { key, dir } = state.sort;
  const val = (c) => (key === "alerce" ? c.alerce?.class || "" : c[key] ?? (dir > 0 ? Infinity : -Infinity));
  state.view.sort((a, b) => (val(a) < val(b) ? -dir : val(a) > val(b) ? dir : 0));
  renderTable();
}
function renderTable() {
  const cols = [["score", "Score", 1], ["oid", "Object"], ["age_days", "Age", 1], ["last_mag", "Mag", 1], ["slope", "Trend", 1],
                ["color_gr", "g − r", 1], ["type_hint", "Light-curve hint"], ["alerce", "ALeRCE class"], ["tonight", "Tonight", 1]];
  const arrow = (k) => (state.sort.key === k ? (state.sort.dir > 0 ? " ↑" : " ↓") : "");
  $("#table").innerHTML = `<thead><tr>${cols.map(([k, l, n]) => `<th class="sort ${n ? "num" : ""}" data-k="${k}">${l}${arrow(k)}</th>`).join("")}</tr></thead><tbody>
    ${state.view.map((c, i) => `<tr data-i="${i}" class="${state.sel === c ? "sel" : ""}">
      <td class="num score"><b class="${c.score >= 55 ? "s-hi" : c.score >= 35 ? "s-mid" : "s-lo"}">${c.score}</b></td>
      <td class="mono">${esc(c.oid)}</td>
      <td class="num">${fmt(c.age_days, 1)} d</td>
      <td class="num">${fmt(c.last_mag, 2)}</td>
      <td class="num ${c.rising ? "up" : "down"}">${c.slope == null ? "—" : (c.slope < 0 ? "▲ " : "▼ ") + fmt(Math.abs(c.slope), 2)}</td>
      <td class="num">${fmt(c.color_gr, 2)}</td>
      <td>${esc(c.type_hint)}</td>
      <td>${c.alerce ? `${esc(c.alerce.class)} <span class="muted">${fmt(c.alerce.prob, 2)}</span>` : `<span class="muted">—</span>`}</td>
      <td class="num">${c.tonight >= 0.2 ? fmt(c.tonight, 1) + " h" : "—"}</td>
    </tr>`).join("")}</tbody>`;
}
$("#table").onclick = (e) => {
  const th = e.target.closest("th");
  if (th) { const k = th.dataset.k; state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : (k === "score" || k === "tonight" ? -1 : 1) }; applyFilter(); return; }
  const tr = e.target.closest("tr[data-i]"); if (tr) select(state.view[+tr.dataset.i]);
};
$("#filterTabs").onclick = (e) => {
  const f = e.target.dataset.f; if (!f) return;
  state.filter = f; document.querySelectorAll("#filterTabs .tab").forEach((t) => t.classList.toggle("on", t.dataset.f === f)); applyFilter();
};

/* ---------- detail ---------- */
const plotCfg = { displaylogo: false, responsive: true, displayModeBar: false };
function L(extra = {}) {
  return {
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", showlegend: false, hovermode: "closest",
    font: { color: css("--muted"), family: "IBM Plex Mono", size: 11 }, margin: { l: 46, r: 10, t: 8, b: 36 }, ...extra,
    xaxis: { gridcolor: css("--grid"), zerolinecolor: css("--zero"), linecolor: css("--line-2"), ...(extra.xaxis || {}) },
    yaxis: { gridcolor: css("--grid"), zerolinecolor: css("--zero"), linecolor: css("--line-2"), ...(extra.yaxis || {}) },
  };
}
function select(c) {
  state.sel = c; renderTable();
  const stamp = (t) => c.stamp_candid ? `https://avro.alerce.online/get_stamp?oid=${c.oid}&candid=${c.stamp_candid}&type=${t}&format=png` : "";
  const tns = `https://www.wis-tns.org/search?ra=${c.ra}&decl=${c.dec}&radius=5&coords_unit=arcsec`;
  const raH = c.ra / 15, h = Math.floor(raH), mi = (raH - h) * 60;
  $("#detail").innerHTML = `
    <div class="d-head"><div><h2>${esc(c.oid)}</h2>
      <div class="hint">${esc(c.type_hint)}${c.alerce ? ` · ALeRCE: ${esc(c.alerce.class)} (${fmt(c.alerce.prob, 2)})` : ""}</div>
      <div class="muted mono" style="font-size:12px">RA ${h}h ${fmt(mi, 2)}m (${fmt(c.ra, 4)}°) · Dec ${fmt(c.dec, 4)}°</div></div>
      <div class="links"><a class="btn small" target="_blank" rel="noopener" href="https://alerce.online/object/${c.oid}">ALeRCE ↗</a>
        <a class="btn small" target="_blank" rel="noopener" href="https://lasair-ztf.lsst.ac.uk/objects/${c.oid}/">Lasair ↗</a>
        <a class="btn small" target="_blank" rel="noopener" href="${tns}">TNS search ↗</a></div></div>
    <div class="reasons">${(c.score_reasons.length ? c.score_reasons : ["no strong follow-up drivers"]).map((r) => `<span>${esc(r)}</span>`).join("")}</div>
    <div id="lcPlot"></div>
    ${c.stamp_candid ? `<div class="stamps">${["science", "template", "difference"].map((t) => `<figure><img loading="lazy" src="${stamp(t)}" alt="${t}"><figcaption>${t}</figcaption></figure>`).join("")}</div>` : ""}
    <table class="kv">
      <tr><td>First detected</td><td>${mjdToDate(c.first_mjd).toISOString().slice(0, 16).replace("T", " ")} UTC (${fmt(c.age_days, 1)} d ago)</td></tr>
      <tr><td>Last non-detection before that</td><td>${c.last_nondet_mjd ? `${fmt(c.first_mjd - c.last_nondet_mjd, 1)} d earlier, fainter than ${fmt(c.last_nondet_mag, 1)}` : "none in prior 10 d"}</td></tr>
      <tr><td>Latest / brightest magnitude</td><td>${fmt(c.last_mag, 2)} / ${fmt(c.peak_mag, 2)}</td></tr>
      <tr><td>Trend (last week)</td><td>${c.slope == null ? "—" : `${c.slope < 0 ? "brightening" : "fading"} ${fmt(Math.abs(c.slope), 3)} mag/day`}</td></tr>
      <tr><td>Rise time / decline</td><td>${c.rise_days != null ? fmt(c.rise_days, 1) + " d" : "peak not reached"} / ${c.decline_mag_day != null ? fmt(c.decline_mag_day, 3) + " mag/d" : "—"}</td></tr>
      <tr><td>Colour g − r</td><td>${fmt(c.color_gr, 2)}</td></tr>
      <tr><td>Detections</td><td>${c.ndet} · SN stamp probability ${fmt(c.sn_prob, 2)}</td></tr>
    </table>
    <div class="label" style="margin-top:14px">Altitude from your location, next 16 h</div>
    <div id="obsPlot"></div>`;
  lightCurve(c); obsPlot(c);
  renderContrib(c);
}
function lightCurve(c) {
  const traces = [], now = state.scan.now_mjd;
  for (const [b, d] of Object.entries(c.bands)) {
    const col = css(BAND_COLOR[b]);
    const fit = c.fits[b];
    if (fit) traces.push({ x: fit.curve.mjd.map((t) => t - now), y: fit.curve.mag, mode: "lines", line: { color: col, width: 1.2, dash: "dot" }, hoverinfo: "skip" });
    traces.push({ x: d.lim_mjd.map((t) => t - now), y: d.lim_mag, mode: "markers", marker: { symbol: "triangle-down-open", size: 7, color: col, opacity: .55 },
      hovertemplate: `${b} limit %{y:.2f}<extra></extra>` });
    traces.push({ x: d.mjd.map((t) => t - now), y: d.mag, mode: "markers", name: b, marker: { size: 7, color: col },
      error_y: { type: "data", array: d.err, color: col, thickness: 1, width: 0 }, hovertemplate: `${b} %{y:.2f} at %{x:.1f} d<extra></extra>` });
  }
  const mags = Object.values(c.bands).flatMap((d) => d.mag);
  const lo = Math.min(...mags) - 0.5, hi = Math.max(...mags, ...Object.values(c.bands).flatMap((d) => d.lim_mag.length ? [Math.min(...d.lim_mag)] : [])) + 0.5;
  Plotly.react("lcPlot", traces, L({ xaxis: { title: "Days from now", range: [c.first_mjd - now - 12, 1] }, yaxis: { title: "Magnitude", range: [Math.min(hi, 22), lo] },
    annotations: Object.keys(c.bands).map((b, k) => ({ xref: "paper", yref: "paper", x: 0.02 + k * 0.06, y: 0.98, text: `● ${b}`, showarrow: false, font: { color: css(BAND_COLOR[b]) } })) }), plotCfg);
}
function obsPlot(c) {
  const g = tonightGrid();
  const alt = g.times.map((d) => altitude(c.ra, c.dec, d, state.lat, state.lon));
  const shapes = [];
  let start = null;
  g.dark.forEach((dk, k) => {
    if (dk && start === null) start = g.times[k];
    if ((!dk || k === g.dark.length - 1) && start !== null) { shapes.push({ type: "rect", x0: start, x1: g.times[k], yref: "paper", y0: 0, y1: 1, fillcolor: css("--panel-2"), line: { width: 0 }, layer: "below" }); start = null; }
  });
  shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: 30, y1: 30, line: { color: css("--line-2"), dash: "dot" } });
  Plotly.react("obsPlot", [{ x: g.times, y: alt, mode: "lines", line: { color: css("--accent"), width: 1.6 }, hovertemplate: "%{x|%H:%M}<br>alt %{y:.0f}°<extra></extra>" }],
    L({ shapes, xaxis: { tickformat: "%H:%M" }, yaxis: { title: "Alt (°)", range: [0, 90] }, margin: { l: 46, r: 10, t: 4, b: 30 } }), plotCfg);
}

/* ---------- contribute ---------- */
const ls = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
function authorFields(prefix) {
  const a = ls("author", {});
  return `<input id="${prefix}Name" placeholder="Your name (as it should appear)" value="${esc(a.name || "")}">
    <input id="${prefix}Aff" placeholder="Affiliation or Independent" value="${esc(a.affiliation || "")}">
    <input id="${prefix}Email" placeholder="Email" value="${esc(a.email || "")}">
    <input id="${prefix}Orcid" placeholder="ORCID (optional)" value="${esc(a.orcid || "")}">`;
}
function readAuthor(prefix) {
  const a = { name: $(`#${prefix}Name`).value.trim(), affiliation: $(`#${prefix}Aff`).value.trim(), email: $(`#${prefix}Email`).value.trim(), orcid: $(`#${prefix}Orcid`).value.trim() };
  lsSet("author", a); return a;
}
function creds() { return ls("tns", { bot_id: "", bot_name: "", api_key: "", groupid: "0", sandbox: true }); }
function readCreds() {
  const c = { bot_id: $("#tBotId").value.trim(), bot_name: $("#tBotName").value.trim(), api_key: $("#tKey").value.trim(),
              groupid: $("#tGroup").value.trim() || "0", sandbox: $("#tSandbox").checked };
  lsSet("tns", c); return c;
}
async function tnsChoices() { if (!state.tnsChoices) state.tnsChoices = await api("/api/tns/choices"); return state.tnsChoices; }

function renderContrib(c) {
  const t = creds(), host = t.sandbox ? "sandbox.wis-tns.org" : "www.wis-tns.org";
  const box = document.createElement("div");
  box.className = "contrib";
  box.innerHTML = `
    <h3>Contribute</h3>
    <div class="cstep"><h4>1. Your details and TNS bot</h4>
      <p>The Transient Name Server credits reports to you. Register at <a target="_blank" rel="noopener" href="https://www.wis-tns.org/">wis-tns.org</a>, then create a bot on the
        <a target="_blank" rel="noopener" href="https://www.wis-tns.org/bots">Bots page</a> to get its id, name and API key. Saved in this browser only.</p>
      <div class="creds">${authorFields("a")}</div>
      <div class="creds"><input id="tBotId" placeholder="Bot id" value="${esc(t.bot_id)}"><input id="tBotName" placeholder="Bot name" value="${esc(t.bot_name)}">
        <input id="tKey" type="password" placeholder="API key" value="${esc(t.api_key)}"><input id="tGroup" placeholder="Your TNS group id (0 = none)" value="${esc(t.groupid)}"></div>
      <label class="muted"><input type="checkbox" id="tSandbox" ${t.sandbox ? "checked" : ""}> use the TNS sandbox (test server, wiped weekly)</label></div>

    <div class="cstep"><h4>2. Is it already on TNS?</h4>
      <p>Most ZTF transients are reported automatically by brokers within hours. Discovery credit goes to whoever reports first.</p>
      <div class="row"><button class="btn" id="tCheck">Check TNS</button><a class="btn" target="_blank" rel="noopener" href="https://${host}/search?ra=${c.ra}&decl=${c.dec}&radius=5&coords_unit=arcsec">Open TNS search ↗</a></div>
      <div id="tCheckOut" class="muted" style="margin-top:6px"></div></div>

    <div class="cstep"><h4>3. Report it as a new transient</h4>
      <p>Only if step 2 found nothing. The report uses the public ZTF photometry, credits ZTF as the data source and you as the reporter, and TNS assigns an AT name.</p>
      <div class="row"><button class="btn" id="tPrev">Prepare discovery report</button></div><div id="tRepOut"></div></div>

    <div class="cstep"><h4>4. Observe it and report your photometry</h4>
      <p>Your measurements are added to the TNS record under your name. No telescope? Remote ones are available through
        <a target="_blank" rel="noopener" href="https://lco.global/education/partners/">Las Cumbres Global Sky Partners</a> (free for education projects) or
        <a target="_blank" rel="noopener" href="https://www.itelescope.net/">iTelescope</a>.
        Finder: <a target="_blank" rel="noopener" href="https://www.legacysurvey.org/viewer?ra=${c.ra}&dec=${c.dec}&layer=ls-dr10&zoom=15&mark=${c.ra},${c.dec}">Legacy Survey ↗</a></p>
      <div class="row"><button class="btn" id="tPhotAdd">Add a measurement</button></div><div id="tPhot"></div></div>

    <div class="cstep"><h4>5. Write an AstroNote</h4>
      <p>A short public note on TNS, credited to you, that points others to an interesting object. Post it from the AstroNotes page while logged in.</p>
      <div class="row"><button class="btn" id="tNote">Draft AstroNote</button><a class="btn" target="_blank" rel="noopener" href="https://www.wis-tns.org/astronotes">AstroNotes ↗</a></div><div id="tNoteOut"></div></div>

    <div class="cstep"><h4>6. Citizen science with discovery credit</h4>
      <p>Volunteers who flag real transients in these projects are named in the TNS discovery reports.</p>
      <div class="row"><a class="btn" target="_blank" rel="noopener" href="https://www.zooniverse.org/projects/nova-van/kilonova-seekers">Kilonova Seekers ↗</a>
        <a class="btn" target="_blank" rel="noopener" href="https://www.zooniverse.org/projects/dwright04/supernova-hunters">Supernova Hunters ↗</a></div></div>`;
  $("#detail").appendChild(box);
  for (const id of ["#tBotId", "#tBotName", "#tKey", "#tGroup", "#tSandbox"]) $(id).onchange = readCreds;
  for (const id of ["#aName", "#aAff", "#aEmail", "#aOrcid"]) $(id).onchange = () => readAuthor("a");
  const need = () => { const k = readCreds(); if (!k.bot_id || !k.bot_name || !k.api_key) { toast("Enter your TNS bot id, name and API key in step 1"); return null; } return k; };

  $("#tCheck").onclick = async () => {
    const k = need(); if (!k) return;
    $("#tCheckOut").textContent = "Searching TNS…";
    try {
      const r = await api("/api/tns/check", { method: "POST", body: JSON.stringify({ scan: state.scanFile, oid: c.oid, creds: k, sandbox: k.sandbox }) });
      $("#tCheckOut").innerHTML = r.matches.length ? r.matches.map((m) => `<div><a target="_blank" rel="noopener" href="${esc(m.url)}"><b>${esc(m.objname)}</b></a>
          ${m.type ? `· ${esc(m.type)}` : "· unclassified"} · reported by ${esc(m.reporting_group || m.discoverer || "?")}${m.discovery_date ? ` on ${esc(m.discovery_date.slice(0, 10))}` : ""}</div>`).join("")
          + `<div>Already on TNS. You can still add follow-up photometry (step 4) or an AstroNote (step 5)${r.matches.some((m) => !m.type) ? "; it is still unclassified, so a spectrum would be valuable" : ""}.</div>`
        : `<span class="ok-note">Not on TNS within 3″. You can report it (step 3).</span>`;
    } catch (e) { $("#tCheckOut").innerHTML = `<span class="err-note">${esc(e.message)}</span>`; }
  };

  const showReport = (rep, label) => {
    $("#tRepOut").innerHTML = `<textarea class="json-box" id="tJson">${esc(JSON.stringify(rep, null, 2))}</textarea>
      <div class="row"><button class="btn primary" id="tSend">${label}</button><span id="tSendOut" class="muted"></span></div>`;
    $("#tSend").onclick = async () => {
      const k = need(); if (!k) return;
      let report; try { report = JSON.parse($("#tJson").value); } catch { toast("The report is not valid JSON"); return; }
      if (!confirm(`Submit this report to ${k.sandbox ? "the TNS SANDBOX (test)" : "the real Transient Name Server"} as ${report.at_report["0"].reporter}?`)) return;
      $("#tSendOut").textContent = "Submitting… TNS processes reports in a few seconds.";
      try {
        const r = await api("/api/tns/submit", { method: "POST", body: JSON.stringify({ report, creds: k, sandbox: k.sandbox }) });
        $("#tSendOut").innerHTML = `<span class="ok-note">Accepted (report ${esc(r.report_id)})${r.objnames.length ? `: object ${r.objnames.map((n) => `<a target="_blank" rel="noopener" href="https://${k.sandbox ? "sandbox" : "www"}.wis-tns.org/object/${esc(n)}">${esc(n)}</a>`).join(", ")}` : ""}.</span>`
          + `<details><summary>TNS reply</summary><pre class="console">${esc(JSON.stringify(r.reply, null, 1))}</pre></details>`;
      } catch (e) { $("#tSendOut").innerHTML = `<span class="err-note">${esc(e.message)}</span>`; }
    };
  };
  $("#tPrev").onclick = async () => {
    const a = readAuthor("a"); if (!a.name) { toast("Enter your name in step 1"); return; }
    const rep = await api("/api/tns/preview", { method: "POST", body: JSON.stringify({ scan: state.scanFile, oid: c.oid, reporter: a.name, reporting_groupid: readCreds().groupid }) });
    showReport(rep, "Submit discovery report");
  };

  $("#tPhotAdd").onclick = async () => {
    const ch = await tnsChoices();
    const opt = (list, sel) => list.map((x) => `<option value="${x.id}" ${x.id === sel ? "selected" : ""}>${esc(x.name)}</option>`).join("");
    const row = document.createElement("div");
    row.className = "phot-grid"; row.style.marginTop = "6px";
    row.innerHTML = `<input type="datetime-local" class="pDate" step="1"><input class="pMag" placeholder="mag"><input class="pErr" placeholder="± err">
      <select class="pFilt">${opt(ch.filters, "1")}</select><select class="pInst">${opt(ch.instruments, "0")}</select>`;
    $("#tPhot").appendChild(row);
    if (!$("#tPhotSend")) {
      const b = document.createElement("div"); b.className = "row"; b.style.marginTop = "6px";
      b.innerHTML = `<button class="btn" id="tPhotSend">Prepare photometry report</button><span class="muted">time in UTC; choose "Other" if your instrument isn't listed</span>`;
      $("#tPhot").after(b);
      $("#tPhotSend").onclick = async () => {
        const a = readAuthor("a"); if (!a.name) { toast("Enter your name in step 1"); return; }
        const points = [...document.querySelectorAll("#tPhot .phot-grid")].map((r) => ({
          obsdate: r.querySelector(".pDate").value, mag: r.querySelector(".pMag").value, err: r.querySelector(".pErr").value,
          filterid: r.querySelector(".pFilt").value, instrumentid: r.querySelector(".pInst").value, observer: a.name })).filter((p) => p.obsdate && p.mag);
        if (!points.length) { toast("Fill in date and magnitude"); return; }
        const rep = await api("/api/tns/preview", { method: "POST", body: JSON.stringify({ scan: state.scanFile, oid: c.oid, reporter: a.name, reporting_groupid: readCreds().groupid, kind: "photometry", points }) });
        showReport(rep, "Submit photometry report");
        $("#tRepOut").scrollIntoView({ behavior: "smooth", block: "center" });
      };
    }
  };

  $("#tNote").onclick = async () => {
    const r = await api(`/api/astronote/${encodeURIComponent(state.scanFile)}/${encodeURIComponent(c.oid)}`, { method: "POST", body: JSON.stringify(readAuthor("a")) });
    $("#tNoteOut").innerHTML = `<textarea class="json-box" id="tNoteText">${esc(r.text)}</textarea><div class="row"><button class="btn small" id="tNoteCopy">Copy</button></div>`;
    $("#tNoteCopy").onclick = () => { navigator.clipboard.writeText($("#tNoteText").value); toast("Copied"); };
  };
}

function initShare() {
  $("#authorBox").innerHTML = authorFields("s");
  const z = ls("zenodo", { sandbox: true });
  $("#zToken").value = z.token || ""; $("#zSandbox").checked = z.sandbox !== false;
  const saveZ = () => { const v = { token: $("#zToken").value.trim(), sandbox: $("#zSandbox").checked }; lsSet("zenodo", v); return v; };
  $("#zToken").onchange = saveZ; $("#zSandbox").onchange = saveZ;
  $("#pkgBtn").onclick = async () => {
    if (!state.scanFile) return;
    const res = await fetch(`/api/package/${encodeURIComponent(state.scanFile)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(readAuthor("s")) });
    const a = document.createElement("a"); a.href = URL.createObjectURL(await res.blob()); a.download = state.scanFile.replace(".json", ".zip"); a.click();
  };
  $("#zBtn").onclick = async () => {
    const zz = saveZ(), au = readAuthor("s");
    if (!zz.token) { $("#zNote").textContent = "Paste a Zenodo token first."; return; }
    if (!au.name) { $("#zNote").textContent = "Enter your name first."; return; }
    $("#zNote").textContent = "Uploading…";
    try {
      const d = await api(`/api/zenodo/${encodeURIComponent(state.scanFile)}`, { method: "POST", body: JSON.stringify({ author: au, token: zz.token, sandbox: zz.sandbox }) });
      $("#zNote").innerHTML = `Draft ready${d.doi ? ` (DOI ${esc(d.doi)})` : ""}. <a target="_blank" rel="noopener" href="${esc(d.html)}">Review ↗</a> <button class="btn small" id="zPub">Publish</button>`;
      $("#zPub").onclick = async () => {
        if (!confirm(`Publish on ${zz.sandbox ? "the Zenodo TEST server" : "Zenodo"}? Published records and DOIs are permanent.`)) return;
        try { const p = await api("/api/zenodo-publish", { method: "POST", body: JSON.stringify({ id: d.id, token: zz.token, sandbox: zz.sandbox }) });
          $("#zNote").innerHTML = `<span class="ok-note">Published: <a target="_blank" rel="noopener" href="${esc(p.url)}">${esc(p.doi)}</a></span>`; }
        catch (e) { $("#zNote").innerHTML = `<span class="err-note">${esc(e.message)}</span>`; }
      };
    } catch (e) { $("#zNote").innerHTML = `<span class="err-note">${esc(e.message)}</span>`; }
  };
}

/* ---------- sky map ---------- */
function sky() {
  const c = state.scan.candidates;
  Plotly.react("skyPlot", [{ type: "scattergeo", lon: c.map((x) => 180 - x.ra), lat: c.map((x) => x.dec), text: c.map((x) => `${x.oid} · score ${x.score} · ${fmt(x.last_mag, 1)} mag`), customdata: c.map((_, i) => i),
    mode: "markers", marker: { size: 7, color: c.map((x) => x.score), colorscale: [[0, css("--point")], [1, css("--accent")]], line: { width: 0 } },
    hovertemplate: "%{text}<extra></extra>" }],
    { paper_bgcolor: "rgba(0,0,0,0)", margin: { l: 0, r: 0, t: 0, b: 0 }, showlegend: false,
      geo: { projection: { type: "mollweide" }, showland: false, showcoastlines: false, showframe: true, framecolor: css("--line-2"), bgcolor: css("--panel"),
        lonaxis: { showgrid: true, gridcolor: css("--grid"), dtick: 30 }, lataxis: { showgrid: true, gridcolor: css("--grid"), dtick: 30 } } }, plotCfg);
  if (!sky.bound) { sky.bound = true; $("#skyPlot").on("plotly_click", (e) => { const p = e.points?.[0]; if (p) select(state.scan.candidates[p.customdata]); }); }
}

/* ---------- scan jobs ---------- */
async function watch(id) {
  $("#jobBox").classList.remove("hidden"); $("#scanBtn").disabled = true;
  const j = await api(`/api/jobs/${id}`);
  $("#jobBar").style.width = j.pct + "%"; $("#jobMsg").textContent = j.log.at(-1) || "Queued…";
  $("#scanBtn").textContent = j.status === "running" ? `Scanning… ${Math.round(j.pct)}%` : "Queued…";
  if (j.status === "done") { $("#scanBtn").disabled = false; $("#scanBtn").textContent = "Run scan"; $("#jobBox").classList.add("hidden"); toast("Scan finished"); return loadScans(j.file); }
  if (j.status === "error") { $("#scanBtn").disabled = false; $("#scanBtn").textContent = "Run scan"; toast(j.error); return; }
  setTimeout(() => watch(id), 1200);
}
$("#scanBtn").onclick = async () => {
  const j = await api("/api/scan", { method: "POST", body: JSON.stringify({ days: +$("#optDays").value, min_prob: +$("#optProb").value, max_objects: +$("#optMax").value }) });
  toast("Scan started"); watch(j.id);
};

/* ---------- location ---------- */
function setLocation(lat, lon) {
  state.lat = lat; state.lon = lon; $("#lat").value = fmt(lat, 1); $("#lon").value = fmt(lon, 1);
  try { localStorage.setItem("loc", JSON.stringify([lat, lon])); } catch {}
  if (state.scan) { recompute(); applyFilter(); if (state.sel) obsPlot(state.sel); }
}
$("#lat").onchange = () => setLocation(+$("#lat").value, +$("#lon").value);
$("#lon").onchange = () => setLocation(+$("#lat").value, +$("#lon").value);
$("#geoBtn").onclick = () => navigator.geolocation?.getCurrentPosition((p) => setLocation(p.coords.latitude, p.coords.longitude), () => toast("Location not available"));

/* ---------- theme ---------- */
function initTheme() {
  try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch {}
  $("#themeBtn").onclick = () => {
    const dark = css("--bg") === "#111214";
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch {}
    if (state.scan) { sky(); if (state.sel) select(state.sel); }
  };
}

(async function main() {
  initTheme();
  initShare();
  let loc = null;
  try { loc = JSON.parse(localStorage.getItem("loc")); } catch {}
  // default: longitude from the browser's time zone, mid-northern latitude
  setLocation(loc ? loc[0] : 30, loc ? loc[1] : Math.round(-new Date().getTimezoneOffset() / 4));
  const jobs = await api("/api/jobs").catch(() => []);
  const active = jobs.find((j) => ["queued", "running"].includes(j.status));
  await loadScans().catch(() => {});
  if (active) watch(active.id);
  else if (!state.scan) toast("No scans yet; press Run scan");
})();
