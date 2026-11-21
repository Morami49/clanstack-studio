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
    assert.deepStrictEqual(L.buildSend(u, "hi"), {text: "hi", chip: "looks-off", opts: {compare: "none"}, attach: "PE-1", picture: false});
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
  "strip and mic labels"() {
    assert.deepStrictEqual(L.stripText({watching: "W", gate: "paused", acting: ""}), {watching: "W", gate: "Gate paused", acting: ""});
    assert.strictEqual(L.micLabel(false), "🎙 Mic");
    assert.strictEqual(L.micLabel(true, 75.4), "■ Send 1:15");
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(tests)) {
  try { fn(); console.log("ok   " + name); } catch (e) { failed++; console.log("FAIL " + name + "\n  " + (e.stack || e)); }
}
process.exit(failed ? 1 : 0);
