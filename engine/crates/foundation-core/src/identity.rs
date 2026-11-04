//! Identities without a blockchain (D-032): an identity is a key. It can grant
//! sub-identities and devices a set of capabilities; those can grant further,
//! never more than they hold. Grants and revocations are FACTS (they really
//! happened and can't be branched away). Who-approves-what *flows* are intents
//! (keys under `flow/...`), so they can be versioned and branched like anything else.
//!
//! Capabilities: fact.write, intent.write, branch, merge, grant, or "*".
//! A capability `a.b` is also satisfied by `a.*`.

use serde::{Deserialize, Serialize};

use crate::event::{Event, Id, PubKey};

#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    Identity,
    SubIdentity,
    Device,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Grant {
    pub id: Id,
    pub issuer: PubKey,
    pub subject: PubKey,
    pub role: Role,
    pub label: String,
    pub caps: Vec<String>,
    pub not_after: Option<i64>,
    pub ts: i64,
}

pub fn cap_covers(held: &str, want: &str) -> bool {
    held == "*" || held == want || (held.ends_with(".*") && want.starts_with(&held[..held.len() - 1]))
}

#[derive(Default, Clone, Debug)]
pub struct Authority {
    pub roots: std::collections::HashMap<PubKey, (Id, String)>, // key -> (genesis id, label)
    pub grants: Vec<Grant>,
    pub revoked: std::collections::HashMap<Id, i64>, // grant id -> revoked at ts
}

impl Authority {
    pub fn observe(&mut self, ev: &Event) {
        let b = &ev.u.body;
        match ev.u.kind.as_str() {
            "identity.genesis" => {
                let label = b.get("label").and_then(|v| v.as_str()).unwrap_or("").to_string();
                self.roots.insert(ev.u.author.clone(), (ev.id.clone(), label));
            }
            "grant" => {
                if let Ok(mut g) = serde_json::from_value::<GrantBody>(b.clone()).map(|gb| Grant {
                    id: ev.id.clone(),
                    issuer: ev.u.author.clone(),
                    subject: gb.subject,
                    role: gb.role,
                    label: gb.label,
                    caps: gb.caps,
                    not_after: gb.not_after,
                    ts: ev.u.ts,
                }) {
                    g.caps.sort();
                    self.grants.push(g);
                }
            }
            "revoke" => {
                if let Some(gid) = b.get("grant").and_then(|v| v.as_str()) {
                    self.revoked.entry(gid.to_string()).or_insert(ev.u.ts);
                }
            }
            _ => {}
        }
    }

    /// May `key` do `cap` at time `ts`? Returns the chain of grant ids that proves it.
    pub fn allows(&self, key: &str, cap: &str, ts: i64) -> Result<Vec<Id>, String> {
        self.walk(key, cap, ts, 0)
    }

    fn walk(&self, key: &str, cap: &str, ts: i64, depth: u8) -> Result<Vec<Id>, String> {
        if self.roots.contains_key(key) {
            return Ok(vec![]);
        }
        if depth > 8 {
            return Err("delegation chain too deep".into());
        }
        let mut why = format!("{} has no grant for {cap}", crate::event::short(key));
        for g in self.grants.iter().filter(|g| g.subject == key) {
            if g.ts > ts {
                continue;
            }
            if let Some(r) = self.revoked.get(&g.id) {
                if *r <= ts {
                    why = format!("grant {} was revoked", crate::event::short(&g.id));
                    continue;
                }
            }
            if g.not_after.is_some_and(|na| ts > na) {
                why = format!("grant {} expired", crate::event::short(&g.id));
                continue;
            }
            if !g.caps.iter().any(|c| cap_covers(c, cap)) {
                continue;
            }
            match self.walk(&g.issuer, cap, ts, depth + 1) {
                Ok(mut chain) => {
                    chain.push(g.id.clone());
                    return Ok(chain);
                }
                Err(e) => why = e,
            }
        }
        Err(why)
    }

    /// The identity a key ultimately acts for (first root found up its grant chain).
    pub fn root_of(&self, key: &str) -> Option<PubKey> {
        if self.roots.contains_key(key) {
            return Some(key.to_string());
        }
        let mut cur = key.to_string();
        for _ in 0..8 {
            let g = self.grants.iter().find(|g| g.subject == cur)?;
            if self.roots.contains_key(&g.issuer) {
                return Some(g.issuer.clone());
            }
            cur = g.issuer.clone();
        }
        None
    }
}

#[derive(Serialize, Deserialize)]
pub struct GrantBody {
    pub subject: PubKey,
    pub role: Role,
    #[serde(default)]
    pub label: String,
    pub caps: Vec<String>,
    #[serde(default)]
    pub not_after: Option<i64>,
}
