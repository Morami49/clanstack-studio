/* Nodach Watch: the window's DOM and calls to the local server (watch_server.py). The rules are in watch_logic.js. */
(function () {
  "use strict";
  const L = window.WatchLogic;
  const $ = s => document.querySelector(s);
  const KEY = (location.hash.match(/key=([^&]+)/) || [])[1] || "";
  let ui = L.initial(), state = null, lastOffer = null, micT0 = 0, micTimer = null, ref = null;

  async function api(path, body) {
    const opt = {headers: {"X-Watch-Key": KEY}};
    if (body !== undefined) { opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(path, opt);
    const j = await r.json().catch(() => ({error: "no answer"}));
    if (!r.ok) throw new Error(j.error || ("error " + r.status));
    return j;
  }
  function err(msg) { const e = $("#err"); e.textContent = msg || ""; e.hidden = !msg; if (msg) setTimeout(() => { if (e.textContent === msg) e.hidden = true; }, 8000); }
  async function run(fn) { try { err(""); return await fn(); } catch (e) { err(e.message); return null; } }

  /* ------------------------------------------------------------ state and stream */
  async function refresh() {
    const s = await api("/api/state").catch(e => { err(e.message); return null; });
    if (!s) return;
    state = s;
    const t = L.stripText(s.strip);
    $("#watching").textContent = t.watching;
    const gp = $("#gatePill"); gp.textContent = t.gate; gp.classList.toggle("paused", s.strip.gate === "paused");
    $("#acting").hidden = !t.acting; $("#acting").textContent = t.acting;
    $("#frame").classList.toggle("acting", !!t.acting); $("#frame").classList.toggle("paused", s.strip.gate === "paused");
    $("#hubName").textContent = "Hub: " + s.hub + (s.role ? " · signed in as " + s.role : " · not signed in");
    $("#onTop").checked = !!s.on_top; $("#stuckOn").checked = !!(s.stuck && s.stuck.on);
    if (s.error && !s.role) err(s.error);
    const sel = $("#session");
    const opts = (s.sessions || []).map(x => '<option value="' + L.esc(x.id) + '"' + (x.id === s.session ? " selected" : "") + ">" + L.esc(x.id) + (x.state === "live" ? " ● live" : " · " + L.esc(x.state)) + "</option>");
    const html = opts.join("") || '<option value="">no session</option>';
    if (sel.dataset.html !== html) { sel.innerHTML = html; sel.dataset.html = html; }
    $("#startSession").hidden = s.role !== "owner";
    if (s.offer) {
      const g = s.offer.reason === "glitch";
      $("#offerText").textContent = g ? "Gate kept a clip: " + s.offer.detail : "Looks like Claude is stuck (" + s.offer.detail + "). Show what's wrong?";
      $("#offerReport").hidden = !g; $("#offer").hidden = false; lastOffer = s.offer;
    }
    $("#mic").title = "Click to talk, click to send · voice " + s.voice;
    await stream();
  }
  async function stream() {
    if (!state || !state.session) { $("#chat").innerHTML = L.rowsHtml([]); return; }
    const r = await api("/api/stream?session=" + encodeURIComponent(state.session)).catch(() => null);
    if (!r) return;
    const box = $("#chatWrap"), atEnd = box.scrollTop + box.clientHeight >= box.scrollHeight - 10;
    const html = L.rowsHtml(r.rows);
    if ($("#chat").dataset.html !== html) { $("#chat").innerHTML = html; $("#chat").dataset.html = html; if (atEnd) box.scrollTop = box.scrollHeight; }
  }

  /* ------------------------------------------------------------ chips */
  function renderUi() {
    document.querySelectorAll(".chipbtn").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.chip === ui.chip)));
    $("#chipOpts").hidden = !ui.chip;
    $("#optLooks").hidden = ui.chip !== "looks-off"; $("#optMark").hidden = ui.chip !== "mark-up"; $("#optExplain").hidden = ui.chip !== "explain";
    $("#optReport").hidden = ui.chip !== "report";
    $("#incident").hidden = !(ui.chip === "report" && ui.opts.irreversible);
    $("#reproNote").textContent = L.reproduceNote(ui);
    $("#earlier").hidden = !(ui.chip === "looks-off" && ui.opts.compare === "earlier");
    $("#refName").textContent = ref && ui.opts.compare_ref ? ref.name || ref.id : "";
    document.querySelectorAll(".bar button").forEach(b => b.classList.remove("hint"));
    if (ui.bar === "select") $("#select").classList.add("hint");
    if (ui.bar === "markup") $("#markup").classList.add("hint");
    const a = ui.attach;
    $("#attRow").hidden = !a;
    if (a) {
      $("#attWords").textContent = a.words;
      $("#picLabel").hidden = !a.picture || !!a.kept_out; $("#attPic").checked = !!ui.picture;
      $("#attReport").hidden = $("#attClaude").hidden = a.kind !== "markup";
      $("#attExport").hidden = !!a.kept_out;
    }
    $("#text").placeholder = ui.chip ? L.chipTag(ui.chip, ui.opts) + " … what you see" : "Type a line · task: … or build: … drafts a task";
  }
  document.querySelectorAll(".chipbtn").forEach(b => b.onclick = () => { ui = L.applyChip(ui, b.dataset.chip); syncOptInputs(); renderUi(); });
  function syncOptInputs() {
    if (ui.chip === "looks-off") $("#compare").value = ui.opts.compare || "none";
    if (ui.chip === "mark-up") { $("#preset").value = ui.opts.preset || ""; $("#markAs").value = ui.opts.as || "line"; }
    if (ui.chip === "report") { $("#irreversible").checked = !!ui.opts.irreversible; document.querySelectorAll("[data-inc]").forEach(i => { i.value = (ui.opts.incident || {})[i.dataset.inc] || ""; }); }
    if (ui.chip === "explain") document.querySelector('input[name=save][value="' + (ui.opts.save || "none") + '"]').checked = true;
  }
  $("#compare").onchange = async e => {
    ui = L.setOpt(ui, "compare", e.target.value);
    const v = e.target.value;
    if (v === "earlier") {
      const r = await run(() => api("/api/shots"));
      const shots = (r && r.shots) || [];
      $("#earlier").innerHTML = shots.map(s => '<option value="' + L.esc(s.id) + '">' + L.esc((s.at || "").slice(11, 19) + " " + s.words) + "</option>").join("") || "<option value=''>no earlier captures</option>";
      if (shots[0]) { ui.opts.compare_ref = {id: shots[0].id, kind: shots[0].kind, words: shots[0].words, at: shots[0].at}; }
    } else if (v === "reference" || v === "design") {
      const r = await run(() => api("/api/reference", {}));
      if (r && r.reference) { ref = r.reference; ui.opts.compare_ref = {id: ref.id, kind: v, name: ref.name, sha256: ref.sha256, at: ref.at}; }
    } else if (v === "clip") {
      const r = await run(() => api("/api/clip", {}));
      if (r) { ref = r.ref; ui.opts.compare_ref = r.ref; }
    }
    renderUi();
  };
  $("#earlier").onchange = e => { const o = e.target.selectedOptions[0]; if (o && o.value) ui.opts.compare_ref = {id: o.value, kind: "earlier", words: o.textContent}; };
  $("#preset").onchange = e => { ui = L.setOpt(ui, "preset", e.target.value); renderUi(); };
  $("#markAs").onchange = e => { ui = L.setOpt(ui, "as", e.target.value); renderUi(); };
  $("#irreversible").onchange = e => { ui = L.setIrreversible(ui, e.target.checked); syncOptInputs(); renderUi(); };
  document.querySelectorAll("[data-inc]").forEach(i => i.oninput = () => { ui = L.setIncident(ui, i.dataset.inc, i.value); });
  document.querySelectorAll("input[name=save]").forEach(r => r.onchange = e => { ui = L.setOpt(ui, "save", e.target.value); });

  /* ------------------------------------------------------------ sending */
  async function doSend(body) {
    if (!body) { err("Type a line or add a point first."); return; }
    const r = await run(() => api("/api/send", body));
    if (r) { $("#text").value = ""; ui = L.afterSend(ui); ref = null; renderUi(); if (r.switched) err("That session had ended: sent to " + r.session); await refresh(); }
  }
  $("#send").onclick = () => doSend(L.buildSend(ui, $("#text").value));
  $("#text").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#send").click(); } };
  $("#attPic").onchange = e => { ui.picture = e.target.checked; };
  $("#attClear").onclick = () => { ui = L.attach(ui, null); renderUi(); };
  $("#attReport").onclick = () => doSend(L.buildMarkupSend(ui, $("#text").value, "report"));
  $("#attClaude").onclick = () => doSend(L.buildMarkupSend(ui, $("#text").value, "for-claude"));
  $("#attExport").onclick = async () => {
    const r = await run(() => api("/api/export", {id: ui.attach.id, note: $("#text").value}));
    if (r) err("Saved " + r.html + " and " + r.zip + " in " + r.folder);
  };

  /* ------------------------------------------------------------ tools */
  async function capture(mode, preset) {
    const r = await run(() => api("/api/capture", {mode, preset: preset || null}));
    if (r && r.event) { ui = L.attach(ui, r.event); renderUi(); $("#text").focus(); }
  }
  $("#point").onclick = () => capture("point");
  $("#select").onclick = () => capture("area");
  $("#markup").onclick = () => { if (ui.chip !== "mark-up") { ui = L.applyChip(ui, "mark-up"); syncOptInputs(); renderUi(); } capture("markup", ui.opts.preset); };
  $("#clip").onclick = () => run(() => api("/api/clip", {})).then(r => r && err("Gate keeps the last 10 s (in nodach-gate/clips)."));
  $("#stop").onclick = () => run(() => api("/api/stop", {})).then(refresh);
  $("#mic").onclick = async () => {
    if (!ui.listening) {
      const r = await run(() => api("/api/mic", {action: "start"}));
      if (!r) return;
      ui.listening = true; micT0 = Date.now();
      micTimer = setInterval(() => { $("#mic").textContent = L.micLabel(true, (Date.now() - micT0) / 1000); }, 500);
      $("#mic").classList.add("on");
    } else {
      clearInterval(micTimer); ui.listening = false; $("#mic").classList.remove("on"); $("#mic").textContent = L.micLabel(false);
      const b = L.buildSend(ui, $("#text").value) || {text: "", chip: ui.chip, opts: ui.opts, attach: null, picture: false};
      const r = await run(() => api("/api/mic", Object.assign({action: "stop"}, b)));
      if (r && r.sent) { $("#text").value = ""; ui = L.afterSend(ui); renderUi(); refresh(); }
      else if (r && !r.text) err("No speech heard.");
    }
  };

  /* ------------------------------------------------------------ keep-out */
  async function koRender() {
    const r = await run(() => api("/api/keepout"));
    const list = (r && r.list) || [];
    $("#koList").innerHTML = list.map(e => '<li><span class="what" title="' + L.esc(e.added + " by " + e.by) + '">' + L.esc(e.words) +
      '</span><button class="link" data-ko="' + L.esc(e.id) + '">Remove</button></li>').join("") || '<li class="meta">Nothing kept out yet.</li>';
    $("#koList").querySelectorAll("[data-ko]").forEach(b => b.onclick = () => run(() => api("/api/keepout/remove", {id: b.dataset.ko})).then(koRender).then(refresh));
  }
  function choices(items) {
    const ul = $("#koChoices"); ul.hidden = !items.length;
    ul.innerHTML = items.map((c, i) => '<li><span class="what">' + L.esc(c.label) + '</span>' + (c.out ? '<span class="meta">already out</span>' : '<button data-i="' + i + '">Keep out</button>') + "</li>").join("");
    ul.querySelectorAll("[data-i]").forEach(b => b.onclick = async () => {
      const c = items[+b.dataset.i];
      const r = await run(() => api("/api/keepout/add", {entry: c.entry}));
      if (r) { ul.hidden = true; koRender(); refresh(); }
    });
  }
  function openKo() { $("#keepout").hidden = false; koRender(); }
  $("#watching").onclick = () => { $("#keepout").hidden ? openKo() : ($("#keepout").hidden = true); };
  $("#keepOutBtn").onclick = openKo;
  $("#koClose").onclick = () => { $("#keepout").hidden = true; };
  $("#koPick").onclick = async () => {
    const r = await run(() => api("/api/keepout/pick", {}));
    if (!r || r.cancelled) return;
    if (r.already_out) { err("That window is already out (" + r.already_out + ")."); return; }
    choices(r.choices || []);
  };
  $("#koFromList").onclick = async () => {
    const r = await run(() => api("/api/windows"));
    const ws = (r && r.windows) || [];
    choices(ws.map(w => ({label: w.out ? w.app + " (" + w.out + ")" : w.app + ": " + w.title, out: w.out,
      entry: {kind: w.title ? "window" : "app", process: w.app, title: w.title}})));
  };
  $("#koAddFolder").onclick = async () => {
    const p = $("#koFolder").value.trim(); if (!p) return;
    const r = await run(() => api("/api/keepout/add", {entry: {kind: "folder", path: p}}));
    if (r) { $("#koFolder").value = ""; koRender(); refresh(); }
  };

  /* ------------------------------------------------------------ settings, sessions, offers */
  $("#settingsBtn").onclick = () => { $("#settings").hidden = !$("#settings").hidden; };
  $("#onTop").onchange = e => run(() => api("/api/ontop", {on: e.target.checked}));
  $("#stuckOn").onchange = e => run(() => api("/api/settings", {stuck: e.target.checked}));
  $("#signIn").onclick = () => run(() => api("/api/signin", {})).then(refresh);
  $("#session").onchange = e => run(() => api("/api/session", {id: e.target.value})).then(refresh);
  $("#startSession").onclick = () => run(() => api("/api/session/start", {})).then(refresh);
  $("#offerReport").onclick = () => { $("#offer").hidden = true; ui = L.applyChip(L.initial(), "report");
    $("#text").value = "The screen changed with nothing done" + (lastOffer && lastOffer.app ? " in " + lastOffer.app : "") + " (Gate kept the clip " + ((lastOffer && lastOffer.clip) || "") + ").";
    syncOptInputs(); renderUi(); $("#text").focus(); };
  $("#offerNo").onclick = () => { $("#offer").hidden = true; };
  $("#offerMark").onclick = () => { $("#offer").hidden = true; $("#markup").click(); };
  $("#offerExplain").onclick = () => { $("#offer").hidden = true; ui = L.applyChip(L.initial(), "explain"); syncOptInputs(); renderUi(); $("#text").focus(); };

  renderUi();
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 2500);   // like Studio's fast poll while a session is live
})();
