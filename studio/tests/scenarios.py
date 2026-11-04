"""Clanstack Studio scenario tests: simulated people, states and organisations.

Each scenario is a person in a situation (tired, on a phone, view-only, a
collaborator, an outside AI relaying answers, two people at once, a store
that fails...) doing something they need to work. It passes only if the
page behaves the way that person would need it to.

    python tests/scenarios.py [path/to/index.html]

Runs the real page in Chromium against an in-memory store shared by every
open page, so multi-person scenarios are real concurrency, not mocks of it.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
PAGE = (Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "index.html").resolve()
GENESIS = json.loads((HERE / "genesis.json").read_text())
OUT = Path(os.environ.get("STUDIO_TEST_OUT", HERE / "out"))
OUT.mkdir(parents=True, exist_ok=True)
# Wrap the page in the same skeleton the Artifact host adds at publish time.
WRAPPED = OUT / "page.html"
WRAPPED.write_text('<!doctype html><html><head><meta charset=utf8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">'
                   '<style>:root{color-scheme:light}body{margin:0;font:14px system-ui}img{max-width:100%}[hidden]{display:none!important}</style></head><body>'
                   + PAGE.read_text() + '</body></html>')

MOCK = r"""
(() => {
const C = window.__cfg;
let seq = 0;
const snapOf = e => ({id:e._id, data:()=>e, metadata:{fromCache:false}});
const listeners = [];
window.__evs = C.paths || {events: C.events || []};
window.__push = (path, evs) => { window.__evs[path] = evs; listeners.forEach(f => f()); };
const mine = path => !path.startsWith("data/users/") || path.startsWith("data/users/" + C.me + "/");
function query(path, dir, lim){
  const q = {
    orderBy:(f,d)=>query(path, d||"asc", lim), limit:n=>query(path, dir, n),
    onSnapshot:(next, err)=>{ const f=()=>{ let a=mine(path) ? [...(window.__evs[path]||[])] : []; a.sort((x,y)=>x.ts<y.ts?-1:x.ts>y.ts?1:0); if(dir==="desc")a.reverse(); if(lim)a=a.slice(0,lim);
        next({docs:a.map(snapOf), size:a.length, empty:!a.length, metadata:{fromCache:false}, docChanges:()=>[]}); };
      listeners.push(f); setTimeout(f, 30); return ()=>{}; },
    add: async d => { if (C.failWrites) throw {code:"unavailable", message:"offline"}; if (C.readOnly || !mine(path)) throw {code:"invalid_argument", message:"no"};
      const e = {...d, _id:"e"+Date.now().toString(36)+(seq++)}; await window.__bridgeAdd(path, e); return {id:e._id}; },
  };
  return q;
}
window.claude = { use: async n => {
  if (n === "user") return { id: async()=>C.me, isOwner: async()=>C.owner, canEdit: async()=>C.canEdit,
      can: async k => k==="data.write" ? C.canWrite : null,
      profiles: async ids => Object.fromEntries(ids.map(i => [i, {id:i, name:(C.names||{})[i]||""}])), me: async()=>({id:C.me}) };
  if (n === "db") return { doc: p => ({ onSnapshot:(next)=>{ setTimeout(()=>next({exists:true, data:()=>C.genesis, metadata:{fromCache:false}}), 20); return ()=>{}; } }),
                           collection: p => query(p, "asc", null) };
  return null; } };
})();
"""


class Store:
    """One in-memory database shared by every open page. Paths under data/users/<id>/ reach only that person's pages."""
    def __init__(self, events=None):
        self.paths = {"events": list(events or [])}
        self.pages = []

    @property
    def events(self):
        return self.paths["events"]

    def all(self):
        return [e for v in self.paths.values() for e in v]

    async def add(self, path, ev):
        self.paths.setdefault(path, []).append(ev)
        for p in self.pages:
            if path.startswith("data/users/") and not path.startswith(f"data/users/{p.me}/"):
                continue
            try:
                await p.evaluate("([path, evs]) => window.__push(path, evs)", [path, self.paths[path]])
            except Exception:
                pass


async def open_page(browser, store: Store, cfg: dict, width=1440, height=900, name="p"):
    ctx = await browser.new_context(viewport={"width": width, "height": height})
    page = await ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    full = {"genesis": GENESIS, "me": "u_nowed", "owner": True, "canEdit": True, "canWrite": True,
            "names": {"u_nowed": "Nowed", "u_rad": "Rad"}, **cfg, "paths": store.paths}
    await page.expose_function("__bridgeAdd", store.add)
    await page.add_init_script("window.__cfg = " + json.dumps(full) + ";" + MOCK)
    await page.goto(WRAPPED.as_uri())
    await page.wait_for_timeout(900)
    page.me = full["me"]
    store.pages.append(page)
    page.errors = errors
    return page


def ev(kind, item, body, who="u_nowed", ts="2026-11-01T15:00:00.000Z", branch="main", label="Nowed"):
    return {"_id": f"x{abs(hash((kind, item, ts, who))) % 10**9}", "ts": ts, "kind": kind, "item": item, "branch": branch,
            "body": body, "author": {"id": who, "label": label, "role": "owner" if who == "u_nowed" else "member"}}


async def exists(page, sel):
    return await page.locator(sel).count() > 0


async def visible_text(page):
    return await page.evaluate("document.body.innerText")


# ---------------------------------------------------------------- scenarios
async def s01_tired_misclick(b):
    """Tired, clicks Challenge with nothing typed. Nothing irreversible should happen; it asks for a reason."""
    st = Store(); p = await open_page(b, st, {})
    await p.evaluate("select('A-actionmap-v02')"); await p.wait_for_timeout(200)
    await p.click("#mkChallenge"); await p.wait_for_timeout(300)
    return len(st.events) == 0, f"{len(st.events)} events written by an empty challenge"


async def s02_undo(b):
    """Changes their mind right after answering. One tap undoes it; history keeps both (no silent overwrite)."""
    st = Store(); p = await open_page(b, st, {})
    await p.evaluate("select('Q-layers')"); await p.wait_for_timeout(200)
    await p.fill("#reply", "A"); await p.click("#sendAnswer"); await p.wait_for_timeout(300)
    if not await exists(p, "[data-undo]"):
        return False, "no undo control after answering"
    await p.click("[data-undo]"); await p.wait_for_timeout(300)
    ans = await p.evaluate("F.items.get('Q-layers').answers.length")
    return ans == 0 and len(st.events) == 2, f"answers shown after undo: {ans}; events kept: {len(st.events)}"


async def s03_stable_codes(b):
    """An outside AI answers from yesterday's pack. Codes must still point at the same items after new questions appear and others close."""
    st = Store(); p = await open_page(b, st, {})
    before = await p.evaluate("codeOf('Q-confirm-budget')")
    await st.add("events", ev("item.create", None, {"id": "Q-new1", "type": "question", "title": "New early question", "body": "", "status": "open"}, ts="2026-11-04T15:01:00.000Z"))
    await st.add("events", ev("status", "Q-layers", {"status": "closed"}, ts="2026-11-04T15:02:00.000Z"))
    await p.wait_for_timeout(300)
    after = await p.evaluate("codeOf('Q-confirm-budget')")
    return before == after and before is not None, f"code before {before}, after {after}"


async def s04_past_view_lock(b):
    """Looking at last week to remember a decision. Typing there must not silently write into today."""
    st = Store([ev("comment", "D-001", {"text": "hi"})]); p = await open_page(b, st, {})
    await p.evaluate("S.asof='0'; refresh(); select('Q-layers')"); await p.wait_for_timeout(300)
    dis = await p.evaluate("!!document.querySelector('#sendAnswer')?.disabled")
    banner = "Return to live" in await visible_text(p)
    return dis and banner, f"answer disabled={dis}, return-to-live shown={banner}"


async def s05_branch_awareness(b):
    """Exploring an idea on a branch. They must see that changes stay on the branch until merged."""
    st = Store([ev("branch.create", None, {"name": "try-quiet", "fork_ts": "2026-11-04T15:00:00.000Z", "from": "main"})])
    p = await open_page(b, st, {})
    await p.evaluate("S.branch='try-quiet'; refresh()"); await p.wait_for_timeout(200)
    t = await visible_text(p)
    ok = "try-quiet" in t and "until" in t.lower() and "merged" in t.lower()
    return ok, "branch banner explains merging" if ok else "no branch banner explaining merge"


async def s06_view_only_client(b):
    """A client opened a shared link with view-only access. They should know before typing that they can't change things."""
    st = Store(); p = await open_page(b, st, {"me": "u_client", "owner": False, "canEdit": False, "canWrite": False, "readOnly": True})
    await p.evaluate("select('Q-layers')"); await p.wait_for_timeout(200)
    dis = await p.evaluate("!!document.querySelector('#sendAnswer')?.disabled")
    banner = "view only" in (await visible_text(p)).lower()
    return dis and banner, f"answer disabled={dis}, view-only notice={banner}"


async def s07_names(b):
    """A co-founder answered. Nowed must see who it was, not 'Member'."""
    st = Store([ev("answer", "Q-layers", {"code": "Q1", "text": "B"}, who="u_rad", label="Member")])
    p = await open_page(b, st, {})
    await p.evaluate("select('Q-layers')"); await p.wait_for_timeout(400)
    t = await p.inner_text("#insp")
    return "Rad" in t, "author shown by name" if "Rad" in t else "author shown as generic label"


async def s08_long_history(b):
    """A busy community after months: 1,200 changes. The newest must still show."""
    evs = [ev("comment", "D-001", {"text": f"c{i}"}, ts=f"2026-11-{4 + i // 1000:02d}T{(i // 60) % 24:02d}:{i % 60:02d}:00.000Z") for i in range(1200)]
    evs.append(ev("answer", "Q-layers", {"code": "Q1", "text": "NEWEST"}, ts="2026-12-30T00:00:00.000Z"))
    st = Store(evs); p = await open_page(b, st, {})
    await p.wait_for_timeout(500)
    n = await p.evaluate("F.items.get('Q-layers').answers.length")
    return n == 1, f"newest answer visible: {n == 1}"


async def s09_ai_relay(b):
    """Pasting ChatGPT's reply. Multiple lines, a new idea, and the source recorded."""
    st = Store(); p = await open_page(b, st, {})
    await p.click("#tabs button[data-v=ask]")
    src = await exists(p, "#codeSource")
    if src:
        await p.select_option("#codeSource", "chatgpt")
    await p.fill("#codes", "Q1 A\nQ3 B, quieter at night\nNEW let voice notes become captures")
    await p.click("#codesGo"); await p.wait_for_timeout(500)
    kinds = sorted(e["kind"] for e in st.events)
    sourced = all((e["body"] or {}).get("source") == "chatgpt" for e in st.events) if st.events else False
    ok = kinds.count("answer") == 2 and "item.create" in kinds and sourced
    return ok, f"events {kinds}, source recorded={sourced}"


async def s10_keyboard_list(b):
    """Keyboard-only or screen-reader user. Every item must be reachable without the canvas."""
    st = Store(); p = await open_page(b, st, {})
    if not await exists(p, "#tabs button[data-v=list]"):
        return False, "no list view"
    await p.click("#tabs button[data-v=list]"); await p.wait_for_timeout(200)
    btns = await p.locator("#listView button[data-open]").count()
    await p.locator("#listView button[data-open]").first.focus(); await p.keyboard.press("Enter"); await p.wait_for_timeout(200)
    return btns >= 150 and await p.evaluate("!!S.sel"), f"{btns} items reachable by keyboard"


async def s11_offline_capture(b):
    """On a train with no signal, captures an idea. The text must not be lost."""
    st = Store(); p = await open_page(b, st, {"failWrites": True})
    await p.click("#tabs button[data-v=capture]")
    await p.fill("#capTitle", "Train idea"); await p.fill("#capBody", "Pools for community kitchens")
    await p.click("#capGo"); await p.wait_for_timeout(300)
    kept = await p.input_value("#capBody") == "Pools for community kitchens"
    await p.reload(); await p.wait_for_timeout(900)
    await p.click("#tabs button[data-v=capture]")
    survived = await p.input_value("#capBody") == "Pools for community kitchens"
    return kept and survived, f"kept after failure={kept}, survived reload={survived}"


async def s12_member_rights(b):
    """A collaborator can answer and propose, but marking things agreed is the owner's (charter)."""
    st = Store(); p = await open_page(b, st, {"me": "u_rad", "owner": False, "canEdit": False})
    await p.evaluate("select('T-scope')"); await p.wait_for_timeout(200)
    can_answer = await exists(p, "#sendAnswer") and not await p.evaluate("document.querySelector('#sendAnswer').disabled")
    no_agree = not await exists(p, "#mkAgreed")
    return can_answer and no_agree, f"can answer={can_answer}, agree hidden={no_agree}"


async def s13_two_people_at_once(b):
    """Nowed and Rad answer the same question at the same time. Both answers survive and both see them."""
    st = Store()
    a = await open_page(b, st, {}); c = await open_page(b, st, {"me": "u_rad", "owner": False, "canEdit": False})
    for pg, txt in ((a, "A from Nowed"), (c, "B from Rad")):
        await pg.evaluate("select('Q-delegation')"); await pg.fill("#reply", txt)
    await asyncio.gather(a.click("#sendAnswer"), c.click("#sendAnswer")); await a.wait_for_timeout(500)
    na = await a.evaluate("F.items.get('Q-delegation').answers.length"); nc = await c.evaluate("F.items.get('Q-delegation').answers.length")
    return na == 2 and nc == 2, f"answers seen: Nowed {na}, Rad {nc}"


async def s14_phone(b):
    """Mid-shift on a phone: opens on Capture, nothing scrolls sideways, and the Ask tab says how much needs him."""
    st = Store(); p = await open_page(b, st, {}, width=390, height=800)
    overflow = await p.evaluate("document.documentElement.scrollWidth > innerWidth")
    view = await p.evaluate("S.view")
    badge = await p.inner_text("#tabs button[data-v=ask]")
    has_badge = any(ch.isdigit() for ch in badge)
    await p.screenshot(path=str(OUT / "phone.png"))
    return (not overflow) and view == "capture" and has_badge, f"overflow={overflow}, view={view}, ask tab='{badge}'"


async def s15_undo_old_status(b):
    """Nowed's real case: a status set by mistake earlier must be revertible from its history line."""
    st = Store([ev("comment", "A-actionmap-v02", {"text": "⚑ Challenged"}), ev("status", "A-actionmap-v02", {"status": "challenged"}, ts="2026-11-01T15:00:01.000Z")])
    p = await open_page(b, st, {})
    await p.evaluate("select('A-actionmap-v02')"); await p.wait_for_timeout(200)
    if not await exists(p, "[data-revert]"):
        return False, "no revert on history lines"
    await p.locator("[data-revert]").last.click(); await p.wait_for_timeout(300)
    status = await p.evaluate("F.items.get('A-actionmap-v02').status")
    return status == "built", f"status after revert: {status}"


async def s16_overwhelm(b):
    """Low on energy, opens Ask. The badge counts only what truly needs him, and 28 proposed terms can be agreed in one go (and undone)."""
    st = Store(); p = await open_page(b, st, {})
    badge = await p.inner_text("#askBadge")
    await p.click("#tabs button[data-v=ask]")
    has_all = await exists(p, "[data-agreeall]")
    if has_all:
        await p.click("[data-agreeall]"); await p.wait_for_timeout(2500)
    left = await p.evaluate("askable().filter(i=>i.type==='term').length")
    undo = await exists(p, ".toast [data-undo]")
    undone = None
    if undo:
        await p.click(".toast [data-undo]"); await p.wait_for_timeout(2500)
        undone = await p.evaluate("askable().filter(i=>i.type==='term').length")
    ok = badge.isdigit() and int(badge) <= 15 and has_all and left == 0 and undo and undone == 28
    return ok, f"badge={badge}, agree-all={has_all}, terms left={left}, undo offered={undo}, back after undo={undone}"


async def s17_disagreement(b):
    """Nowed and Rad gave different answers. The card must say so instead of hiding the conflict."""
    st = Store([ev("answer", "Q-layers", {"code": "Q1", "text": "A"}), ev("answer", "Q-layers", {"code": "Q1", "text": "B"}, who="u_rad", ts="2026-11-01T15:05:00.000Z")])
    p = await open_page(b, st, {})
    await p.click("#tabs button[data-v=ask]")
    t = await p.inner_text("#askList")
    ok = "answered differently" in t
    return ok, "conflict surfaced on the card" if ok else "conflict not surfaced"


async def s18_clock_skew(b):
    """A device with a fast clock wrote in the 'future'. Reverting it from a correct device must still win."""
    st = Store([ev("status", "A-actionmap-v02", {"status": "challenged"}, ts="2027-01-01T00:00:00.000Z")])
    p = await open_page(b, st, {})
    await p.evaluate("select('A-actionmap-v02')"); await p.wait_for_timeout(200)
    await p.locator("[data-revert]").last.click(); await p.wait_for_timeout(300)
    status = await p.evaluate("F.items.get('A-actionmap-v02').status")
    return status == "built", f"status after revert: {status} (device clocks disagree; needs the Core's causal clock)"


async def s19_private_area(b):
    """Nowed notes something personal. It lands in his private area: invisible to a co-founder, left out of the AI pack unless he opts in."""
    st = Store()
    a = await open_page(b, st, {}); c = await open_page(b, st, {"me": "u_rad", "owner": False, "canEdit": False})
    await a.click("#tabs button[data-v=capture]")
    await a.check("#capPrivate"); await a.fill("#capTitle", "Sleep after night shifts"); await a.fill("#capBody", "private note")
    await a.click("#capGo"); await a.wait_for_timeout(500)
    in_private = len(st.paths.get("data/users/u_nowed/vault/events", [])) == 1 and len(st.events) == 0
    a_sees = await a.evaluate("[...F.items.values()].some(i=>i.title==='Sleep after night shifts' && i.private)")
    c_sees = await c.evaluate("[...F.items.values()].some(i=>i.title==='Sleep after night shifts')")
    await a.click("#tabs button[data-v=pack]"); pack = await a.inner_text("#pack")
    in_pack = "Sleep after night shifts" in pack
    await a.check("#packPriv"); in_pack_opt = "Sleep after night shifts" in await a.inner_text("#pack")
    ok = in_private and a_sees and not c_sees and not in_pack and in_pack_opt
    return ok, f"stored privately={in_private}, owner sees={a_sees}, co-founder sees={c_sees}, in pack by default={in_pack}, with opt-in={in_pack_opt}"


SCENARIOS = [s01_tired_misclick, s02_undo, s03_stable_codes, s04_past_view_lock, s05_branch_awareness, s06_view_only_client,
             s07_names, s08_long_history, s09_ai_relay, s10_keyboard_list, s11_offline_capture, s12_member_rights,
             s13_two_people_at_once, s14_phone, s15_undo_old_status, s16_overwhelm, s17_disagreement, s18_clock_skew, s19_private_area]


async def main():
    results = []
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        for sc in SCENARIOS:
            try:
                ok, note = await sc(b)
            except Exception as e:
                ok, note = False, f"crashed: {type(e).__name__}: {str(e)[:140]}"
            results.append({"id": sc.__name__.split("_")[0], "who": sc.__doc__.strip().split(".")[0], "pass": bool(ok), "note": note})
            print(("PASS " if ok else "FAIL ") + sc.__name__ + " — " + note)
        await b.close()
    (OUT / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"\n{sum(r['pass'] for r in results)}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
