//! Browser binding for foundation-core. Everything crosses the boundary as JSON
//! strings so any JS (or Leptos, later) can drive it. Errors come back as
//! `{"error": "..."}` rather than exceptions.

use std::collections::HashMap;

use foundation_core::{self as core, KeyPair, Realm, Store};
use serde_json::{json, Value};
use wasm_bindgen::prelude::*;

#[wasm_bindgen]
pub struct Node {
    store: Store,
    keys: HashMap<String, KeyPair>,
}

fn ok(v: Value) -> String {
    v.to_string()
}
fn err(e: impl std::fmt::Display) -> String {
    json!({"error": e.to_string()}).to_string()
}
fn parse(s: &str) -> Value {
    serde_json::from_str(s).unwrap_or(Value::Null)
}

#[wasm_bindgen]
impl Node {
    #[wasm_bindgen(constructor)]
    pub fn new() -> Node {
        Node { store: Store::new(), keys: HashMap::new() }
    }

    /// Load a key from 32 random bytes (hex). Returns its public key.
    pub fn key(&mut self, seed_hex: &str) -> String {
        let bytes: [u8; 32] = match hex_decode(seed_hex) {
            Some(b) => b,
            None => return err("seed must be 64 hex chars"),
        };
        let k = KeyPair::from_seed(bytes);
        let p = k.public.clone();
        self.keys.insert(p.clone(), k);
        ok(json!({"public": p}))
    }

    fn k(&self, public: &str) -> Result<&KeyPair, String> {
        self.keys.get(public).ok_or_else(|| err("unknown local key"))
    }

    pub fn fact(&mut self, author: &str, kind: &str, body: &str, rehearsal_branch: &str, lane_branch: &str, ts: f64) -> String {
        let k = match self.k(author) { Ok(k) => KeyPair::from_seed_clone(k), Err(e) => return e };
        let realm = if rehearsal_branch.is_empty() { Realm::Real } else { Realm::Rehearsal(rehearsal_branch.into()) };
        let lane = (!lane_branch.is_empty()).then(|| lane_branch.to_string());
        match self.store.fact(&k, kind, parse(body), realm, lane, ts as i64, &[]) {
            Ok(e) => ok(json!({"id": e.id})),
            Err(e) => err(e),
        }
    }

    pub fn intent(&mut self, author: &str, branch: &str, kind: &str, body: &str, ts: f64) -> String {
        let k = match self.k(author) { Ok(k) => KeyPair::from_seed_clone(k), Err(e) => return e };
        match self.store.intent(&k, &branch.to_string(), kind, parse(body), ts as i64, &[]) {
            Ok(e) => ok(json!({"id": e.id})),
            Err(e) => err(e),
        }
    }

    /// parent "" = new root branch; from "" = fork at the parent's current head; horizon < 0 = live.
    pub fn branch(&mut self, author: &str, parent: &str, from: &str, name: &str, horizon: f64, ts: f64) -> String {
        let k = match self.k(author) { Ok(k) => KeyPair::from_seed_clone(k), Err(e) => return e };
        let parent = (!parent.is_empty()).then(|| parent.to_string());
        let from = (!from.is_empty()).then(|| from.to_string());
        let horizon = (horizon >= 0.0).then_some(horizon as i64);
        match self.store.branch(&k, parent.as_ref(), from.as_ref(), name, horizon, ts as i64) {
            Ok(id) => ok(json!({"id": id})),
            Err(e) => err(e),
        }
    }

    pub fn view(&self, branch: &str) -> String {
        if !self.store.branches.contains_key(branch) {
            return err("unknown branch");
        }
        ok(serde_json::to_value(core::view(&self.store, &branch.to_string())).unwrap())
    }

    pub fn view_at(&self, intent: &str) -> String {
        if !self.store.events.contains_key(intent) {
            return err("unknown intent");
        }
        ok(serde_json::to_value(core::view_at(&self.store, &intent.to_string())).unwrap())
    }

    pub fn merge_preview(&self, from: &str, into: &str) -> String {
        ok(serde_json::to_value(core::merge_preview(&self.store, &from.to_string(), &into.to_string())).unwrap())
    }

    pub fn merge(&mut self, author: &str, from: &str, into: &str, resolutions: &str, ts: f64) -> String {
        let k = match self.k(author) { Ok(k) => KeyPair::from_seed_clone(k), Err(e) => return e };
        let res = parse(resolutions).as_array().cloned().unwrap_or_default();
        match core::merge(&mut self.store, &k, &from.to_string(), &into.to_string(), &res, ts as i64) {
            Ok(e) => ok(json!({"id": e.id})),
            Err(e) => err(e),
        }
    }

    pub fn tree(&self) -> String {
        ok(core::tree(&self.store))
    }

    pub fn identities(&self) -> String {
        let a = &self.store.auth;
        ok(json!({
            "roots": a.roots.iter().map(|(k, (_, l))| json!({"key": k, "label": l})).collect::<Vec<_>>(),
            "grants": a.grants.iter().map(|g| json!({"id": g.id, "issuer": g.issuer, "subject": g.subject, "role": g.role,
                        "label": g.label, "caps": g.caps, "revoked": a.revoked.get(&g.id)})).collect::<Vec<_>>()
        }))
    }

    /// Everything this node holds, as JSON (any transport can carry it).
    pub fn export(&self) -> String {
        serde_json::to_string(&self.store.export()).unwrap()
    }

    /// Merge in another node's export. Order doesn't matter; invalid events are refused.
    pub fn import(&mut self, events: &str) -> String {
        match serde_json::from_str::<Vec<core::Event>>(events) {
            Ok(evs) => {
                let (n, refused) = self.store.add_all(evs);
                ok(json!({"added": n, "refused": refused}))
            }
            Err(e) => err(e),
        }
    }

    pub fn verify(&self) -> String {
        match self.store.verify() {
            Ok(n) => ok(json!({"ok": true, "events": n})),
            Err(e) => ok(json!({"ok": false, "error": e})),
        }
    }
}

impl Default for Node {
    fn default() -> Self {
        Self::new()
    }
}

fn hex_decode(s: &str) -> Option<[u8; 32]> {
    if s.len() != 64 {
        return None;
    }
    let mut out = [0u8; 32];
    for i in 0..32 {
        out[i] = u8::from_str_radix(&s[2 * i..2 * i + 2], 16).ok()?;
    }
    Some(out)
}

trait CloneKey {
    fn from_seed_clone(k: &KeyPair) -> KeyPair;
}
impl CloneKey for KeyPair {
    fn from_seed_clone(k: &KeyPair) -> KeyPair {
        KeyPair::from_seed(k.seed())
    }
}
