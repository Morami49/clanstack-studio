// Nodach Watch: the web UI's pure logic, headless (node actionmap/watch/tests/test_logic.js). Exits non-zero on failure.
"use strict";
const assert = require("assert");
const path = require("path");
const L = require(path.join(__dirname, "..", "web", "watch_logic.js"));

const tests = {
  "a chip turns on with defaults and highlights its tool"() {
    let u = L.applyChip(L.initial(), "looks-off");
    assert.deepStrictEqual([u.chip, u.bar, u.opts], ["looks-off", "select", {compare: "none"}]);
    u = L.applyChip(u, "looks-off");
    assert.deepStrictEqual([u.chip, u.bar], [null, null]);                       // tap again: off
    u = L.applyChip(L.initial(), "mark-up");
    assert.deepStrictEqual([u.bar, u.opts.as], ["markup", "line"]);
    u = L.applyChip(L.initial(), "explain");
    assert.strictEqual(u.opts.save, "none");                                    // default: don't save
    assert.throws(() => L.applyChip(L.initial(), "nope"));
  },
  "options are checked"() {
    let u = L.applyChip(L.initial(), "looks-off");
    u = L.setOpt(u, "compare", "earlier");
    u.opts.compare_ref = {id: "PE-1"};
    u = L.setOpt(u, "compare", "none");
    assert.strictEqual(u.opts.compare_ref, undefined);
    assert.throws(() => L.setOpt(u, "compare", "telepathy"));
    assert.throws(() => L.setOpt(u, "save", "cloud"));
  },
  "send carries the chip, the attachment and the picture tick only when it can"() {
    assert.strictEqual(L.buildSend(L.initial(), "  "), null);
    let u = L.attach(L.applyChip(L.initial(), "looks-off"), {id: "PE-1", kind: "pointer.desktop", words: "⌖ x", picture: true});
    assert.deepStrictEqual(L.buildSend(u, "hi"), {text: "hi", chip: "looks-off", opts: {compare: "none"}, attach: "PE-1", picture: true});   // 21 Nov: picture on by default
    u.picture = false;
    assert.strictEqual(L.buildSend(u, "").picture, false);
    u.picture = true;
    assert.strictEqual(L.buildSend(u, "").picture, true);
    u = L.attach(u, {id: "PE-2", kind: "area", words: "⌖", picture: true, kept_out: "password manager"});
    assert.strictEqual(u.picture, false);
    u.picture = true;
    assert.strictEqual(L.buildSend(u, "x").picture, false);                     // never a picture of a kept-out window
    const m = L.applyChip(L.initial(), "mark-up");
    assert.strictEqual("preset" in L.buildSend(m, "x").opts, false);
  },
  "a mark-up can go as a report or to Claude"() {
    let u = L.attach(L.initial(), {id: "PE-3", kind: "markup", words: "⌖ m", picture: true});
    const r = L.buildMarkupSend(u, "", "report");
    assert.deepStrictEqual([r.chip, r.opts.as, r.attach], ["mark-up", "report", "PE-3"]);
    const c = L.buildMarkupSend(u, "do it", "for-claude");
    assert.strictEqual(L.lineText(c.text, c.chip, c.opts), "[for-claude] [mark-up] do it");
    assert.strictEqual(L.buildMarkupSend(L.attach(L.initial(), {id: "P", kind: "area", words: ""}), "", "report"), null);
  },
  "report problem: reproduce unless it can't be undone"() {
    let u = L.applyChip(L.initial(), "report");
    assert.deepStrictEqual(u.opts, {irreversible: false});
    assert.ok(L.reproduceNote(u).startsWith("Claude tries to reproduce"));
    assert.throws(() => L.setIncident(u, "known", "x"));
    u = L.setIncident(L.setIrreversible(u, true), "what_happened", "paid twice");
    assert.ok(L.reproduceNote(u).startsWith("Nothing will be replayed"));
    assert.strictEqual(L.lineText("oops", "report", u.opts), "[irreversible] oops");
    assert.deepStrictEqual(L.buildSend(u, "oops").opts, {irreversible: true, incident: {what_happened: "paid twice"}});
    assert.throws(() => L.setIncident(u, "secret", "x"));
    assert.strictEqual("incident" in L.setIrreversible(u, false).opts, false);
  },
  "after a send the chip and the save question reset"() {
    const u = L.afterSend(L.setOpt(L.applyChip(L.initial(), "explain"), "save", "developer"));
    assert.deepStrictEqual([u.chip, u.attach, u.opts], [null, null, {}]);
  },
  "tags"() {
    assert.strictEqual(L.lineText("x", "mark-up", {preset: "wrong-place"}), "[wrong-place] x");
    assert.strictEqual(L.lineText("[explain] y", "explain", {}), "[explain] y");
    assert.strictEqual(L.lineText(" a  b ", null, {}), "a b");
  },
  "the stream is escaped"() {
    const h = L.rowsHtml([{kind: "reply", time: "10:00:00", who: "Claude", text: "<img src=x onerror=alert(1)>", words: ""},
                          {kind: "line", time: "10:00:01", who: "Nowed", text: "hi", words: "⌖ a › b", via: "watch"}]);
    assert.ok(!h.includes("<img") && h.includes("&lt;img") && h.includes('class="line"') && h.includes("⌖ a › b"));
    assert.ok(L.rowsHtml([]).includes("No lines yet"));
  },
  "carousel cards are escaped and navigable"() {
    const car = {id: "d1", cards: [{id: "c1", kind: "text", title: "<x>", text: "a\"b"},
                                   {id: "c2", kind: "html", title: "f", html: "<script>alert(1)</script>"},
                                   {id: "c3", kind: "image", title: "i", src: "https://e.com/x.png"}]};
    const h0 = L.cardHtml(car, 0);
    assert.ok(h0.includes("&lt;x&gt;") && h0.includes("1 / 3") && h0.includes("data-car-prev=\"d1\" disabled"));
    const h1 = L.cardHtml(car, 1);
    assert.ok(h1.includes('sandbox=""') && !h1.includes("<script>") && h1.includes("&lt;script&gt;"));
    assert.ok(!L.cardHtml(car, 2).includes("<img"));                 // only data: pictures are shown
    assert.ok(L.cardHtml(car, 9).includes("3 / 3"));
    assert.ok(L.rowsHtml([{kind: "reply", time: "", who: "Claude", text: "", carousel: car}], {d1: 1}).includes("2 / 3"));
    for (const r of Object.keys(L.ROUTES)) assert.ok(h0.includes('data-route="' + r + '"'));
  },
  "card marks and routes"() {
    assert.deepStrictEqual(L.cardMark("box", [50, 40], [10, 10]), {type: "box", rect: {left: 10, top: 10, right: 50, bottom: 40}});
    assert.strictEqual(L.cardMark("arrow", [1, 1], [2, 2]), null);
    assert.deepStrictEqual(L.cardMark("text", [3, 4], [3, 4], "note"), {type: "text", at: [3, 4], text: "note"});
    assert.strictEqual(L.cardMark("text", [3, 4], [3, 4], ""), null);
    assert.throws(() => L.cardMark("lasso", [0, 0], [9, 9]));
    assert.deepStrictEqual(L.routeBody("gate", "d1", "c1", " go ", "PE-1"), {carousel: "d1", route: "gate", card: "c1", text: "go", attach: "PE-1"});
    assert.throws(() => L.routeBody("fly", "d1"));
  },
  "privacy notes, local rows and read-out text"() {
    assert.strictEqual(L.privacyNote(null, null), null);
    assert.ok(L.privacyNote(null, "sign-in page").startsWith("Watch paused itself: a sign-in page"));
    assert.strictEqual(L.privacyNote("sign-in page", "sign-in page"), null);
    assert.strictEqual(L.privacyNote("payment form", null), "Watch resumed: the payment form is gone.");
    assert.ok(L.localRowHtml("<x>", "10:00").includes("&lt;x&gt;") && L.localRowHtml("a").includes('class="local"'));
    assert.strictEqual(L.lastReplyText([{kind: "reply", who: "Claude", text: "one"}, {kind: "line", who: "Nowed", text: "two"}]), "Claude says: one");
    assert.strictEqual(L.lastReplyText([]), "");
  },
  "strip and mic labels"() {
    assert.deepStrictEqual(L.stripText({watching: "W", gate: "paused", acting: ""}), {watching: "W", gate: "Gate paused", acting: ""});
    assert.strictEqual(L.micLabel(false), "🎙 Mic");
    assert.strictEqual(L.micLabel(true, 75.4), "■ Send 1:15");
  },
  "test inputs from Claude: taken once, fresh only on first look, grey note, ui report"() {
    const t = {seq: 2, note: "test input from Claude: <x>", age_s: 3, event: {id: "PE-1", kind: "area", words: "▭ 1 element(s)", picture: true}};
    assert.strictEqual(L.testToApply(0, t, false), t);
    assert.strictEqual(L.testToApply(2, t, false), null);                         // already taken
    assert.strictEqual(L.testToApply(0, Object.assign({}, t, {age_s: 60}), true), null);   // stale after a page reload
    assert.strictEqual(L.testToApply(0, t, true), t);
    assert.strictEqual(L.testToApply(0, null, false), null);
    const h = L.testRowHtml(t.note, "10:00:00");
    assert.ok(h.includes('class="local test"') && h.includes("&lt;x&gt;") && !h.includes("<x>"));
    let u = L.attach(L.applyChip(L.initial(), "looks-off"), t.event);
    u.picture = true;
    const r = L.uiReport(u, {controls: [{id: "send"}]});
    assert.deepStrictEqual([r.chip, r.compare, r.attach.id, r.picture, r.controls[0].id], ["looks-off", "none", "PE-1", true, "send"]);
    assert.strictEqual(L.uiReport(L.initial()).attach, null);
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(tests)) {
  try { fn(); console.log("ok   " + name); } catch (e) { failed++; console.log("FAIL " + name + "\n  " + (e.stack || e)); }
}
process.exit(failed ? 1 : 0);
