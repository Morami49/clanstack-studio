//! hub-core (D-089, D-095): one record that survives any single provider.
//!
//! A hub is a node that is always on and serves the record to others. This crate holds everything
//! a hub does that does not depend on where it runs, so Cloudflare, the PC node, Oracle and friends'
//! nodes all behave identically (D-091) and the rules live only in the engine (D-094).
//!
//! - `push`  : accept events in any order; the engine checks signatures, chains and authority.
//! - `pull`  : serve events after a cursor (this node's arrival order), so any node can catch up.
//! - `import`: stage A of D-095. Studio Web stays the original; each of its events is wrapped as a
//!             signed fact by the hub's importer key, keeping the Studio doc id for dedupe.

use foundation_core::event::{Event, Id, KeyPair, Realm};
use foundation_core::store::{Reject, Store};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashSet;

pub const IMPORT_KIND: &str = "studio.event";

#[derive(Serialize, Deserialize, Debug, PartialEq, Default)]
pub struct PushResult {
    /// Accepted now, in the order they were stored (persist these, in this order).
    pub added: Vec<Id>,
    /// Already held: harmless, so re-sending is always safe.
    pub duplicates: usize,
    /// Not accepted, with the engine's reason. Missing parents / unauthorised may succeed later.
    pub refused: Vec<(Id, String)>,
}

#[derive(Serialize, Deserialize, Debug, PartialEq)]
pub struct Page {
    pub events: Vec<Event>,
    /// Pass back as `after` to continue. Equal to `total` when caught up.
    pub next: usize,
    pub total: usize,
}

#[derive(Serialize, Deserialize, Debug, PartialEq)]
pub struct Status {
    pub events: usize,
    pub imported_studio_events: usize,
    pub verified: bool,
    pub detail: String,
}

#[derive(Default)]
pub struct Hub {
    store: Store,
    imported: HashSet<String>,
}

impl Hub {
    pub fn new() -> Self {
        Self::default()
    }

    /// Rebuild from persisted events (cold start). Persisted order is arrival order, so it always fits.
    pub fn restore(events: Vec<Event>) -> (Self, PushResult) {
        let mut h = Self::new();
        let r = h.push(events);
        (h, r)
    }

    pub fn push(&mut self, events: Vec<Event>) -> PushResult {
        let before = self.store.order.len();
        let mut dup = 0;
        let mut fresh = vec![];
        let mut seen = HashSet::new();
        for e in events {
            if self.store.events.contains_key(&e.id) || !seen.insert(e.id.clone()) {
                dup += 1;
            } else {
                fresh.push(e);
            }
        }
        let (_, refused) = self.store.add_all(fresh);
        let added: Vec<Id> = self.store.order[before..].to_vec();
        for id in &added {
            let ev = &self.store.events[id];
            if ev.u.kind == IMPORT_KIND {
                if let Some(d) = ev.u.body.get("doc_id").and_then(Value::as_str) {
                    self.imported.insert(d.to_string());
                }
            }
        }
        PushResult { added, duplicates: dup, refused }
    }

    pub fn pull(&self, after: usize, limit: usize) -> Page {
        let total = self.store.order.len();
        let start = after.min(total);
        let end = (start + limit.max(1)).min(total);
        let events = self.store.order[start..end].iter().map(|id| self.store.events[id].clone()).collect();
        Page { events, next: end, total }
    }

    pub fn get(&self, id: &str) -> Option<&Event> {
        self.store.events.get(id)
    }

    pub fn has_imported(&self, doc_id: &str) -> bool {
        self.imported.contains(doc_id)
    }

    pub fn status(&self) -> Status {
        let (verified, detail) = match self.store.verify() {
            Ok(n) => (true, format!("{n} events verified")),
            Err(e) => (false, e),
        };
        Status { events: self.store.order.len(), imported_studio_events: self.imported.len(), verified, detail }
    }

    /// Give the importer key its identity (first fact of that key). Idempotent.
    pub fn ensure_importer(&mut self, k: &KeyPair, label: &str, ts: i64) -> Result<Option<Event>, Reject> {
        if self.store.auth.roots.contains_key(&k.public) {
            return Ok(None);
        }
        self.store.fact(k, "identity.genesis", json!({ "label": label }), Realm::Real, None, ts, &[]).map(Some)
    }

    /// Wrap Studio Web events (doc id → event JSON) as signed facts. Already-imported doc ids are skipped,
    /// so running the export twice is harmless. Returns the new facts in order (persist them).
    pub fn import(&mut self, k: &KeyPair, docs: Vec<(String, Value)>, ts: i64) -> Result<Vec<Event>, Reject> {
        let mut out = vec![];
        if let Some(g) = self.ensure_importer(k, "studio-web importer", ts)? {
            out.push(g);
        }
        let mut docs = docs;
        // Studio's own timestamps first, then doc id: a stable order whoever runs the import.
        docs.sort_by(|a, b| {
            let ta = a.1.get("ts").and_then(Value::as_str).unwrap_or("");
            let tb = b.1.get("ts").and_then(Value::as_str).unwrap_or("");
            ta.cmp(tb).then(a.0.cmp(&b.0))
        });
        for (doc_id, ev) in docs {
            if self.imported.contains(&doc_id) {
                continue;
            }
            let e = self.store.fact(k, IMPORT_KIND, json!({ "doc_id": doc_id, "event": ev }), Realm::Real, None, ts, &[])?;
            self.imported.insert(doc_id);
            out.push(e);
        }
        Ok(out)
    }
}
