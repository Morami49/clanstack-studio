/* Nodach Watch: the window's DOM and calls to the local server (watch_server.py). The rules are in watch_logic.js. */
(function () {
  "use strict";
  const L = window.WatchLogic;
  const $ = s => document.querySelector(s);
  const KEY = (location.hash.match(/key=([^&]+)/) || [])[1] || "";
  let ui = L.initial(), state = null, lastOffer = null, privacyWas = null, localRows = [], carIdx = {}, lastRows = [], marking = null, micT0 = 0, micTimer = null, ref = null;

  async function api(path, body) {
    const opt = {headers: {"X-Watch-Key": KEY}};
    if (body !== undefined) { opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(path, opt);
    const j = await r.json().catch(() => ({error: "no answer"}));
    if (!r.ok) throw new Error(j.error || ("error " + r.status));
    return j;
  }
  function info(msg) { err(msg, true); }
  function err(msg, ok) { const e = $("#err"); e.classList.toggle("info", !!ok); e.textContent = msg || ""; e.hidden = !msg; if (msg) setTimeout(() => { if (e.textContent === msg) e.hidden = true; }, 8000); }
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
    $("#endSession").hidden = s.role !== "owner" || !(s.sessions || []).some(x => x.id === s.session && x.state === "live");
    const pn = L.privacyNote(privacyWas, s.strip.privacy);
    if (pn) { localRows.push(L.localRowHtml(pn, new Date().toTimeString().slice(0, 8))); privacyWas = s.strip.privacy || null; $("#chat").dataset.html = ""; }
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
    lastRows = r.rows;
    if (marking) return;                                  // don't redraw under a card being marked up
    const html = L.rowsHtml(r.rows, carIdx) + localRows.join("");
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
    if (r) { $("#text").value = ""; ui = L.afterSend(ui); ref = null; renderUi(); if (r.switched) info("That session had ended: sent to " + r.session); await refresh(); }
  }
  $("#send").onclick = () => doSend(L.buildSend(ui, $("#text").value));
  $("#text").onkeydown = e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#send").click(); } };
  $("#attPic").onchange = e => { ui.picture = e.target.checked; };
  $("#attClear").onclick = () => { ui = L.attach(ui, null); renderUi(); };
  $("#attReport").onclick = () => doSend(L.buildMarkupSend(ui, $("#text").value, "report"));
  $("#attClaude").onclick = () => doSend(L.buildMarkupSend(ui, $("#text").value, "for-claude"));
  $("#attExport").onclick = async () => {
    const r = await run(() => api("/api/export", {id: ui.attach.id, note: $("#text").value}));
    if (r) info("Saved " + r.html + " and " + r.zip + " in " + r.folder);
  };

  /* ------------------------------------------------------------ tools */
  async function capture(mode, preset) {
    const r = await run(() => api("/api/capture", {mode, preset: preset || null}));
    if (r && r.event) { ui = L.attach(ui, r.event); renderUi(); $("#text").focus(); }
  }
  $("#point").onclick = () => capture("point");
  $("#select").onclick = () => capture("area");
  $("#markup").onclick = () => { if (ui.chip !== "mark-up") { ui = L.applyChip(ui, "mark-up"); syncOptInputs(); renderUi(); } capture("markup", ui.opts.preset); };
  $("#clip").onclick = () => run(() => api("/api/clip", {})).then(r => r && info("Gate keeps the last 10 s (in nodach-gate/clips)."));
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

  /* ------------------------------------------------------------ U9/U10: carousel cards */
  function redrawChat() { const h = L.rowsHtml(lastRows, carIdx) + localRows.join(""); $("#chat").innerHTML = h; $("#chat").dataset.html = h; }
  $("#chat").addEventListener("click", async e => {
    const t = e.target.closest("button"); if (!t || marking) return;
    if (t.dataset.carPrev) { carIdx[t.dataset.carPrev] = Math.max(0, (carIdx[t.dataset.carPrev] || 0) - 1); redrawChat(); }
    else if (t.dataset.carNext) { carIdx[t.dataset.carNext] = (carIdx[t.dataset.carNext] || 0) + 1; redrawChat(); }
    else if (t.dataset.open) { window.open(t.dataset.open, "_blank", "noopener"); }
    else if (t.dataset.route) {
      const b = L.routeBody(t.dataset.route, t.dataset.routeCar, t.dataset.routeCard, $("#text").value, ui.attach ? ui.attach.id : null);
      const r = await run(() => api("/api/route", b));
      if (r) { $("#text").value = ""; ui = L.afterSend(ui); renderUi(); refresh(); }
    } else if (t.dataset.cardMarkup) { startCardMarkup(t.closest(".card"), ...t.dataset.cardMarkup.split("|")); }
  });
  const NS = "http://www.w3.org/2000/svg";
  function startCardMarkup(cardEl, carousel, card) {
    const body = cardEl.querySelector(".cardbody"), box = body.getBoundingClientRect();
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "cardsvg"); svg.setAttribute("width", box.width); svg.setAttribute("height", box.height);
    body.classList.add("marking"); body.append(svg);
    const tools = document.createElement("div"); tools.className = "row wrap cardtools";
    tools.innerHTML = '<button data-t="box" class="on">▭ Box</button><button data-t="arrow">→ Arrow</button><button data-t="text">T Note</button>' +
      '<span class="spacer"></span><button data-t="undo">Undo</button><button data-t="done" class="primary">Done</button><button data-t="cancel">Cancel</button>';
    cardEl.append(tools);
    marking = {tool: "box", marks: [], p0: null, live: null};
    const shapes = [];
    const pt = ev => { const r = svg.getBoundingClientRect(); return [Math.round(ev.clientX - r.left), Math.round(ev.clientY - r.top)]; };
    function shape(m) {
      let el;
      if (m.type === "box") { el = document.createElementNS(NS, "rect"); el.setAttribute("x", m.rect.left); el.setAttribute("y", m.rect.top); el.setAttribute("width", m.rect.right - m.rect.left); el.setAttribute("height", m.rect.bottom - m.rect.top); }
      else if (m.type === "arrow") { el = document.createElementNS(NS, "line"); el.setAttribute("x1", m.from[0]); el.setAttribute("y1", m.from[1]); el.setAttribute("x2", m.to[0]); el.setAttribute("y2", m.to[1]); }
      else { el = document.createElementNS(NS, "text"); el.setAttribute("x", m.at[0]); el.setAttribute("y", m.at[1]); el.textContent = m.text; }
      el.setAttribute("class", "mk"); svg.append(el); return el;
    }
    svg.onpointerdown = ev => {
      const p = pt(ev);
      if (marking.tool === "text") { const m = L.cardMark("text", p, p, window.prompt("Note") || ""); if (m) { marking.marks.push(m); shapes.push(shape(m)); } return; }
      marking.p0 = p; svg.setPointerCapture(ev.pointerId);
    };
    svg.onpointermove = ev => {
      if (!marking.p0) return;
      if (marking.live) marking.live.remove();
      const m = L.cardMark(marking.tool, marking.p0, pt(ev));
      marking.live = m ? shape(m) : null;
    };
    svg.onpointerup = ev => {
      if (!marking.p0) return;
      if (marking.live) { marking.live.remove(); marking.live = null; }
      const m = L.cardMark(marking.tool, marking.p0, pt(ev)); marking.p0 = null;
      if (m) { marking.marks.push(m); shapes.push(shape(m)); }
    };
    function end() { svg.remove(); tools.remove(); body.classList.remove("marking"); marking = null; redrawChat(); }
    tools.onclick = async ev => {
      const b = ev.target.closest("button"); if (!b) return;
      const t = b.dataset.t;
      if (["box", "arrow", "text"].includes(t)) { marking.tool = t; tools.querySelectorAll("[data-t]").forEach(x => x.classList.toggle("on", x === b)); }
      else if (t === "undo") { marking.marks.pop(); const s2 = shapes.pop(); if (s2) s2.remove(); }
      else if (t === "cancel") end();
      else if (t === "done") {
        if (!marking.marks.length) { end(); return; }
        const r = await run(() => api("/api/card-markup", {carousel, card, marks: marking.marks, size: [Math.round(box.width), Math.round(box.height)]}));
        end();
        if (r && r.event) { ui = L.attach(ui, r.event); renderUi(); $("#text").focus(); }
      }
    };
  }

  /* ------------------------------------------------------------ U15: read out, enlarge, plain list */
  function say(text) {
    if (!text) { err("Nothing to read out yet."); return; }
    if (!window.speechSynthesis) { err("This window can't read aloud."); return; }
    speechSynthesis.cancel(); speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }
  $("#accessBtn").onclick = () => { $("#access").hidden = !$("#access").hidden; };
  $("#accClose").onclick = () => { $("#access").hidden = true; };
  $("#readLast").onclick = () => say(L.lastReplyText(lastRows));
  $("#bigText").onchange = e => document.body.classList.toggle("big", e.target.checked);
  $("#enlarge").onclick = async () => {
    if (!ui.attach || !ui.attach.picture) { err("Point or Select first: Enlarge shows that capture bigger."); return; }
    const r = await fetch("/api/shot?id=" + encodeURIComponent(ui.attach.id), {headers: {"X-Watch-Key": KEY}});
    if (!r.ok) { err("No picture for that capture."); return; }
    const url = URL.createObjectURL(await r.blob());
    $("#accView").innerHTML = '<div class="zoom"><img alt="Enlarged capture"></div>';
    $("#accView img").src = url;
  };
  $("#plainList").onclick = async () => {
    if (!ui.attach) { err("Select a window or area first: the list shows what can be done there."); return; }
    const r = await run(() => api("/api/plain?id=" + encodeURIComponent(ui.attach.id)));
    const acts = (r && r.actions) || [];
    $("#accView").innerHTML = acts.length ? "<ol>" + acts.map(a => "<li>" + L.esc(a) + "</li>").join("") + '</ol><button id="readList">🔊 Read the list</button>'
      : '<p class="meta">No named elements there.</p>';
    const b = $("#readList"); if (b) b.onclick = () => say(acts.join(". "));
  };

  /* ------------------------------------------------------------ U14: end, and maybe keep as a lesson */
  $("#endSession").onclick = () => { $("#endAsk").hidden = false; };
  $("#endCancel").onclick = () => { $("#endAsk").hidden = true; };
  async function endIt(lesson) {
    $("#endAsk").hidden = true;
    const r = await run(() => api("/api/session/end", {lesson}));
    if (r) { if (r.lesson) info("Ended. Kept in Studio as lesson " + r.lesson + "."); refresh(); }
  }
  $("#endLesson").onclick = () => endIt(true);
  $("#endOnly").onclick = () => endIt(false);

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
