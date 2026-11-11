/* Nodach Studio served by the hub (D-171 S1, Q21 A).
 *
 * The Studio page talks to its host through window.claude.use("db" | "user" | "mcp" | "assets").
 * Inside claude.ai the artifact host provides that. When the hub serves the page itself, this file
 * provides the same interface backed by the hub:
 *   db      shared "events" ↔ the hub's record (/studio/api/events), genesis ↔ /studio/api/genesis.
 *           Private paths (data/users/<id>/vault/...) never leave this browser (localStorage): the hub
 *           stores nothing private (F-23, D-055).
 *   user    the GitHub login you signed in with (id "github:<login>", the same id the connector uses).
 *   mcp     none: the page is already talking to the hub, so there is nothing to sync.
 *   assets  none yet (uploads are not part of S1).
 * Sign-in is a cookie the page cannot read; every write also sends a header other sites cannot send.
 */
(() => {
  if (window.claude && window.claude.use) return; // inside claude.ai: the real host wins

  const API = (window.__nodachApi || "/studio/api/");
  const POLL_MS = window.__nodachPollMs ?? 15000;
  const toLogin = () => { try { window.location.assign("/studio/login"); } catch {} };

  async function api(path, opts = {}) {
    let r;
    try { r = await fetch(API + path, { credentials: "same-origin", cache: "no-store", ...opts }); }
    catch { throw { code: "unavailable", message: "can't reach the hub" }; }
    if (r.status === 401) { toLogin(); throw { code: "unauthenticated", message: "signed out" }; }
    if (r.status === 400 || r.status === 403) { const t = await r.text().catch(() => ""); throw { code: "invalid_argument", message: t }; }
    if (!r.ok) throw { code: "unavailable", message: "hub answered " + r.status };
    return r.json();
  }

  /* ---------------------------------------------------------------- the shared record, kept in memory */
  const shared = [];            // Studio events, each with _id = doc id
  const seen = new Set();
  let cursor = 0, pulling = null;
  const listeners = new Set();
  const notify = () => listeners.forEach(f => { try { f(); } catch {} });

  function take(docs) {
    let n = 0;
    for (const d of docs || []) {
      if (!d || !d.doc_id || !d.event || typeof d.event !== "object" || seen.has(d.doc_id)) continue;
      seen.add(d.doc_id); shared.push({ ...d.event, _id: d.doc_id }); n++;
    }
    return n;
  }

  function pull() {
    if (pulling) return pulling;
    pulling = (async () => {
      let added = 0;
      for (let guard = 0; guard < 1000; guard++) {
        const p = await api(`events?after=${cursor}&limit=500`);
        added += take(p.events);
        const moved = p.next > cursor;
        cursor = p.next;
        if (!moved || cursor >= p.total) break;
      }
      if (added) notify();
      return added;
    })().finally(() => { pulling = null; });
    return pulling;
  }

  let timer = null;
  function startPolling() {
    if (timer || !POLL_MS) return;
    timer = setInterval(() => { if (!document.hidden) pull().catch(() => {}); }, POLL_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) pull().catch(() => {}); });
  }

  const newId = () => "w" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);

  async function writeShared(id, ev) {
    const event = { ...ev }; delete event._id;
    await api("events", {
      method: "POST",
      headers: { "content-type": "application/json", "x-nodach-studio": "1" },
      body: JSON.stringify({ doc_id: id, event }),
    });
    if (!seen.has(id)) { seen.add(id); shared.push({ ...event, _id: id }); }
    notify();
    pull().catch(() => {});
    return { id };
  }

  /* ---------------------------------------------------------------- private areas: this browser only */
  const isPrivate = path => path.startsWith("data/users/");
  const privKey = path => "nodach.priv." + path;
  function privRows(path) { try { return JSON.parse(localStorage.getItem(privKey(path)) || "[]"); } catch { return []; } }
  function privAdd(path, ev) {
    const rows = privRows(path); rows.push(ev);
    try { localStorage.setItem(privKey(path), JSON.stringify(rows)); }
    catch { throw { code: "quota_exceeded", message: "this browser's storage is full" }; }
    notify();
  }

  /* ---------------------------------------------------------------- the db interface the page expects */
  const snap = e => { const data = { ...e }; delete data._id; return { id: e._id, data: () => data, metadata: { fromCache: false } }; };

  function query(path, dir, lim, filters) {
    const rows = () => {
      let a = isPrivate(path) ? privRows(path) : path === "events" ? [...shared] : [];
      for (const f of filters) a = a.filter(f);
      a.sort((x, y) => x.ts < y.ts ? -1 : x.ts > y.ts ? 1 : 0);
      if (dir === "desc") a.reverse();
      if (lim) a = a.slice(0, lim);
      return a;
    };
    const result = () => { const a = rows(); return { docs: a.map(snap), size: a.length, empty: !a.length, metadata: { fromCache: false }, docChanges: () => [] }; };
    return {
      orderBy: (_f, d) => query(path, d || "asc", lim, filters),
      limit: n => query(path, dir, n, filters),
      where: (f, op, v) => query(path, dir, lim, [...filters, e => op === "<" ? e[f] < v : op === ">" ? e[f] > v : op === "<=" ? e[f] <= v : op === ">=" ? e[f] >= v : e[f] === v]),
      get: async () => { if (!isPrivate(path)) await pull().catch(() => {}); return result(); },
      onSnapshot: (next, err) => {
        let live = true;
        const f = () => { if (live) next(result()); };
        listeners.add(f);
        if (isPrivate(path)) setTimeout(f, 0);
        else pull().then(() => { f(); startPolling(); }).catch(e => { if (err) err(e); });
        return () => { live = false; listeners.delete(f); };
      },
      add: async d => {
        const id = newId();
        if (isPrivate(path)) { privAdd(path, { ...d, _id: id }); return { id }; }
        if (path !== "events") throw { code: "invalid_argument", message: "unknown collection " + path };
        return writeShared(id, d);
      },
      doc: id => ({
        set: async d => {
          if (isPrivate(path)) { privAdd(path, { ...d, _id: id }); return; }
          if (path !== "events") throw { code: "invalid_argument", message: "unknown collection " + path };
          await writeShared(id, d);
        },
      }),
    };
  }

  const db = {
    doc: p => ({
      onSnapshot: (next, err) => {
        if (p !== "seed/genesis") { setTimeout(() => next({ exists: false, data: () => null, metadata: { fromCache: false } }), 0); return () => {}; }
        api("genesis").then(g => next({ exists: true, data: () => g, metadata: { fromCache: false } })).catch(e => { if (err) err(e); });
        return () => {};
      },
    }),
    collection: p => query(p, "asc", null, []),
  };

  let meP = null;
  const me = () => (meP = meP || api("me"));
  const user = {
    id: async () => (await me()).id,
    isOwner: async () => !!(await me()).owner,
    canEdit: async () => true,
    can: async k => (k === "data.write" ? true : null),
    me: async () => ({ id: (await me()).id }),
    profiles: async ids => { const m = await me(); return Object.fromEntries(ids.map(i => [i, { id: i, name: i === m.id ? m.login : "" }])); },
  };

  /* ---------------------------------------------------------------- release rules (Q26 C)
   * The hub tells the page its build and whether it is staging. The page never reloads itself: when the hub
   * is running a newer build it shows a banner, and the person reloads when they're ready (nothing half-typed
   * is lost). Staging always wears a ribbon, so a test record is never mistaken for the real one. */
  const BUILD = window.__nodachBuild || null;
  const ENV = window.__nodachEnv === "staging" ? "staging" : "production";
  const VERSION_MS = window.__nodachVersionMs ?? 60000;
  let staleShown = false;

  function whenBody(f) {
    if (typeof document.createElement !== "function") return;
    if (document.body) f(); else document.addEventListener("DOMContentLoaded", f);
  }
  function bar(id, text, css, button) {
    whenBody(() => {
      if (document.getElementById(id)) return;
      const d = document.createElement("div");
      d.id = id; d.setAttribute("role", "status");
      d.style.cssText = "position:fixed;left:0;right:0;z-index:9999;padding:6px 12px;font:13px system-ui;text-align:center;" + css;
      d.textContent = text;
      if (button) {
        const b = document.createElement("button");
        b.textContent = button.label; b.style.cssText = "margin-left:10px;font:inherit;padding:2px 10px;cursor:pointer";
        b.onclick = button.onclick; d.append(b);
      }
      document.body.append(d);
    });
  }
  if (ENV === "staging") bar("nodach-staging", `Staging · test record, not your real one · build ${BUILD || "?"}`, "top:0;background:#7a3e00;color:#fff");

  async function checkVersion() {
    let live = null;
    try { const r = await fetch("/health", { cache: "no-store" }); live = (await r.text()).trim().split(/\s+/)[1] || null; } catch {}
    const stale = !!(BUILD && live && live !== BUILD);
    if (stale && !staleShown) {
      staleShown = true;
      bar("nodach-update", `A new version of Nodach Studio is live (${live}). Save what you're writing, then reload.`,
        "bottom:0;background:#1f3a5f;color:#fff", { label: "Reload now", onclick: () => location.reload() });
    }
    return { current: BUILD, live, stale };
  }
  if (VERSION_MS && BUILD) {
    setInterval(() => { if (!document.hidden) checkVersion(); }, VERSION_MS);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) checkVersion(); });
  }

  window.__nodach = { pull, shared, standalone: true, checkVersion, env: ENV, build: BUILD };
  window.claude = {
    use: async n => {
      if (n === "db") { try { await me(); return db; } catch { return null; } }
      if (n === "user") { try { await me(); return user; } catch { return null; } }
      return null; // mcp, assets: not part of S1
    },
  };
})();
