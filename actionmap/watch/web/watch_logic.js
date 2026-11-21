/* Nodach Watch: the UI's pure logic (no DOM, no fetch), so it can be tested with node:
     node actionmap/watch/tests/test_logic.js
   The same rules as watch_core.py (chip tags, what a send carries); test_watch.py checks both agree. */
(function (root) {
  "use strict";
  const CHIPS = {
    "looks-off": {label: "Looks off", bar: "select"},
    "mark-up": {label: "Mark up", bar: "markup"},
    "explain": {label: "Explain this", bar: "select"},
    "report": {label: "Report problem", bar: "select"},
  };
  const INCIDENT_FIELDS = ["what_happened", "known", "unknown", "state_changed", "affected", "recovery"];
  const COMPARE = ["none", "earlier", "reference", "design", "clip"];
  const SAVE = ["none", "personal", "developer"];
  const MARKUP_AS = ["line", "report", "for-claude"];
  const PRESETS = ["wrong-place", "steps", "design", "automation"];

  function esc(t) {
    return String(t == null ? "" : t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  /* the tag a chip puts in front of the line (same as watch_core.chip_fields) */
  function chipTag(chip, opts) {
    opts = opts || {};
    if (!chip) return "";
    if (!CHIPS[chip]) throw new Error("unknown chip " + chip);
    const base = chip === "mark-up" && opts.preset === "wrong-place" ? "wrong-place"
               : chip === "report" && opts.irreversible ? "irreversible" : chip;
    if (chip === "mark-up" && opts.as === "for-claude") return "[for-claude] [" + base + "]";
    return "[" + base + "]";
  }

  function lineText(text, chip, opts) {
    const t = String(text || "").replace(/\s+/g, " ").trim();
    const tag = chipTag(chip, opts);
    if (tag && !t.toLowerCase().startsWith(tag.split(" ")[0])) return (tag + " " + t).trim().slice(0, 2000);
    return t.slice(0, 2000);
  }

  function initial() {
    return {chip: null, opts: {}, bar: null, attach: null, picture: false, listening: false};
  }

  /* tapping a chip: on (with default options) or off again; the bar highlights the tool it needs */
  function applyChip(ui, chip) {
    const u = Object.assign({}, ui);
    if (u.chip === chip) { u.chip = null; u.opts = {}; u.bar = null; return u; }
    if (!CHIPS[chip]) throw new Error("unknown chip " + chip);
    u.chip = chip;
    u.bar = CHIPS[chip].bar;
    u.opts = chip === "looks-off" ? {compare: "none"}           // judged by eye unless he picks a comparison
           : chip === "explain" ? {save: "none"}                // asked each time, default: don't save
           : chip === "report" ? {irreversible: false}          // Claude may try to reproduce it unless ticked
           : {preset: null, as: "line"};
    return u;
  }

  function setOpt(ui, key, value) {
    const allowed = {compare: COMPARE, save: SAVE, as: MARKUP_AS, preset: [null, ""].concat(PRESETS)};
    if (allowed[key] && allowed[key].indexOf(value) < 0) throw new Error("bad " + key + ": " + value);
    const u = Object.assign({}, ui, {opts: Object.assign({}, ui.opts)});
    u.opts[key] = value === "" ? null : value;
    if (key === "compare" && value === "none") delete u.opts.compare_ref;
    return u;
  }

  /* 'Something can't be undone': the incident template, and nothing is reproduced */
  function setIrreversible(ui, on) {
    const u = Object.assign({}, ui, {opts: Object.assign({}, ui.opts, {irreversible: !!on})});
    if (on) u.opts.incident = Object.assign({}, ui.opts.incident || {}); else delete u.opts.incident;
    return u;
  }
  function setIncident(ui, key, value) {
    if (INCIDENT_FIELDS.indexOf(key) < 0) throw new Error("bad incident field " + key);
    if (!ui.opts.irreversible) throw new Error("tick 'Something can't be undone' first");
    const u = Object.assign({}, ui, {opts: Object.assign({}, ui.opts)});
    u.opts.incident = Object.assign({}, ui.opts.incident, {[key]: String(value || "").slice(0, 600)});
    return u;
  }
  function reproduceNote(ui) {
    if (ui.chip !== "report") return "";
    return ui.opts.irreversible ? "Nothing will be replayed. Claude records an irreversible incident and asks what's missing."
      : "Claude tries to reproduce it through Gate first, and may ask you to replay your steps.";
  }

  function attach(ui, ev) {
    return Object.assign({}, ui, {attach: ev ? {id: ev.id, kind: ev.kind, words: ev.words, picture: !!ev.picture, kept_out: ev.kept_out || null} : null,
                                  picture: false});
  }

  /* what Send posts to /api/send; null when there's nothing to send */
  function buildSend(ui, text) {
    const t = String(text || "").trim();
    if (!t && !ui.attach) return null;
    const body = {text: t, chip: ui.chip || null, opts: ui.chip ? Object.assign({}, ui.opts) : {}, attach: ui.attach ? ui.attach.id : null,
                  picture: !!(ui.picture && ui.attach && ui.attach.picture && !ui.attach.kept_out)};
    if (body.opts.preset === null) delete body.opts.preset;
    return body;
  }

  /* a mark-up's own buttons: Send as report / Hand to Claude */
  function buildMarkupSend(ui, text, as) {
    if (!ui.attach || ui.attach.kind !== "markup") return null;
    const u = ui.chip === "mark-up" ? ui : applyChip(ui, "mark-up");
    const b = buildSend(setOpt(u, "as", as), text);
    return b;
  }

  /* after a send: the chip and the attachment are used up (the save question is asked again next time) */
  function afterSend(ui) { return Object.assign(initial(), {listening: false}); }

  function stripText(strip) {
    if (!strip) return {watching: "…", gate: "", acting: ""};
    return {watching: strip.watching, gate: strip.gate === "paused" ? "Gate paused" : "Gate ok", acting: strip.acting || ""};
  }

  const ROUTES = {drafts: "Create drafts in the app", gate: "Do it through Gate", automation: "Build an automation, then run it"};

  /* U9: one card of a carousel (drafts mixing text, pictures, HTML snippets and video links) */
  function cardHtml(car, i) {
    const n = car.cards.length;
    i = Math.max(0, Math.min(i || 0, n - 1));
    const k = car.cards[i];
    let body = k.text ? '<p class="cardtext">' + esc(k.text) + "</p>" : "";
    if (k.kind === "image" && /^data:image\//.test(k.src || "")) body = '<img class="cardimg" alt="' + esc(k.title) + '" src="' + esc(k.src) + '">' + body;
    if (k.kind === "html") body += '<iframe class="cardhtml" sandbox="" title="' + esc(k.title || "snippet") + '" srcdoc="' + esc(k.html || "") + '"></iframe>';
    if ((k.kind === "video" || k.kind === "link") && k.url) body += '<button class="link" data-open="' + esc(k.url) + '">' + (k.kind === "video" ? "▶ Open video" : "Open link") + "</button>";
    return '<div class="card" data-car="' + esc(car.id) + '" data-card="' + esc(k.id) + '">' +
      '<div class="row"><b>' + esc(k.title || "Card " + (i + 1)) + '</b><span class="spacer"></span><span class="meta">' + (i + 1) + " / " + n + "</span></div>" +
      '<div class="cardbody">' + body + "</div>" +
      '<div class="row"><button data-car-prev="' + esc(car.id) + '"' + (i <= 0 ? " disabled" : "") + ">‹</button>" +
      '<button data-car-next="' + esc(car.id) + '"' + (i >= n - 1 ? " disabled" : "") + ">›</button><span class=\"spacer\"></span>" +
      '<button data-card-markup="' + esc(car.id) + '|' + esc(k.id) + '">✎ Mark up card</button></div>' +
      '<div class="row wrap routes">' + Object.keys(ROUTES).map(r => '<button class="link" data-route="' + r + '" data-route-car="' + esc(car.id) + '" data-route-card="' + esc(k.id) + '">' + esc(ROUTES[r]) + "</button>").join("") + "</div></div>";
  }

  function rowsHtml(rows, idx) {
    idx = idx || {};
    if (!rows || !rows.length) return '<li class="empty">No lines yet. Type, talk, or point.</li>';
    return rows.map(function (r) {
      const cls = r.kind === "line" ? "line" : r.kind === "step" ? "step" : r.kind === "reply" ? "reply" : "note";
      return '<li class="' + cls + (r.carousel ? " wide" : "") + '"><span class="meta">' + esc(r.time) + " · " + esc(r.who) + (r.via ? " · " + esc(r.via) : "") + "</span>" +
        '<span class="text">' + esc(r.text) + "</span>" + (r.words ? '<span class="chip small">' + esc(r.words) + "</span>" : "") +
        (r.carousel ? cardHtml(r.carousel, idx[r.carousel.id] || 0) : "") + "</li>";
    }).join("");
  }

  /* U9: a mark drawn on a card, in the card's own pixels (the same mark types as on screen) */
  function cardMark(tool, p0, p1, text) {
    const d = Math.abs(p1[0] - p0[0]) + Math.abs(p1[1] - p0[1]);
    if (tool === "box") return d < 6 ? null : {type: "box", rect: {left: Math.min(p0[0], p1[0]), top: Math.min(p0[1], p1[1]), right: Math.max(p0[0], p1[0]), bottom: Math.max(p0[1], p1[1])}};
    if (tool === "arrow") return d < 6 ? null : {type: "arrow", from: [p0[0], p0[1]], to: [p1[0], p1[1]]};
    if (tool === "text") return text ? {type: "text", at: [p0[0], p0[1]], text: String(text).slice(0, 300)} : null;
    throw new Error("unknown tool " + tool);
  }
  function routeBody(route, carousel, card, text, attachId) {
    if (!ROUTES[route]) throw new Error("unknown route " + route);
    return {carousel, route, card: card || null, text: String(text || "").trim(), attach: attachId || null};
  }

  function micLabel(listening, secs) {
    if (!listening) return "🎙 Mic";
    const s = Math.floor(secs || 0);
    return "■ Send " + Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  /* U16: the line the chat shows when Watch pauses itself or resumes (null when nothing changed) */
  function privacyNote(prev, now) {
    if ((prev || null) === (now || null)) return null;
    if (now) return "Watch paused itself: a " + now + " is in front. Claude can't see or act until it's gone.";
    return "Watch resumed: the " + prev + " is gone.";
  }
  function localRowHtml(text, time) {
    return '<li class="local"><span class="meta">' + esc(time || "") + " · Watch</span><span class=\"text\">" + esc(text) + "</span></li>";
  }
  /* U15: what 'Read out the last reply' reads */
  function lastReplyText(rows) {
    for (let i = (rows || []).length - 1; i >= 0; i--) if (rows[i].kind === "reply" && rows[i].text) return rows[i].who + " says: " + rows[i].text;
    return "";
  }

  const api = {privacyNote, localRowHtml, lastReplyText, ROUTES, cardHtml, cardMark, routeBody, CHIPS, COMPARE, SAVE, MARKUP_AS, PRESETS, INCIDENT_FIELDS, setIrreversible, setIncident, reproduceNote, esc, chipTag, lineText, initial, applyChip, setOpt, attach,
               buildSend, buildMarkupSend, afterSend, stripText, rowsHtml, micLabel};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WatchLogic = api;
})(typeof window !== "undefined" ? window : globalThis);
