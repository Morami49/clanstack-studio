//! The store: accepts only valid, authorised, causally complete events.
//! Holds the fact ledger (per-author chains) and the intent tree (DAG of branches).
//! Storage-agnostic: export/import is plain JSON, so any transport (HTTP, WebSocket,
//! iroh, a pasted file) can sync two stores; arrival order doesn't matter.

use std::collections::{BTreeSet, HashMap, HashSet};

use serde::Serialize;
use serde_json::{json, Value};

use crate::event::{check_signature, short, Event, Id, KeyPair, Layer, PubKey, Realm, Unsigned};
use crate::identity::Authority;

#[derive(Debug, Clone, PartialEq)]
pub enum Reject {
    Duplicate,
    MissingParents(Vec<Id>),
    /// The signer isn't (yet) authorised. During sync the grant may simply not have arrived yet.
    Unauthorised(String),
    Invalid(String),
}

impl std::fmt::Display for Reject {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Reject::Duplicate => write!(f, "already have it"),
            Reject::MissingParents(p) => write!(f, "missing parents: {}", p.iter().map(|x| short(x)).collect::<Vec<_>>().join(",")),
            Reject::Unauthorised(s) => write!(f, "unauthorised: {s}"),
            Reject::Invalid(s) => write!(f, "invalid: {s}"),
        }
    }
}

#[derive(Serialize, Clone, Debug)]
pub struct Branch {
    pub id: Id,
    pub name: String,
    pub parent: Option<Id>,
    /// The intent it was forked from (None = started from the parent's very beginning).
    pub fork: Option<Id>,
    /// Facts visible on this branch: real facts up to this time, plus facts recorded in its own
    /// lanes, plus its own rehearsal facts. None = all real facts ("live").
    pub horizon: Option<i64>,
    pub created_by: PubKey,
    pub ts: i64,
}

#[derive(Default)]
pub struct Store {
    pub events: HashMap<Id, Event>,
    pub order: Vec<Id>, // arrival order on this node (not part of any hash)
    children: HashMap<Id, Vec<Id>>,
    fact_tip: HashMap<PubKey, (u64, Id)>,
    pub branches: HashMap<Id, Branch>,
    pub auth: Authority,
}

pub const CAP_FACT: &str = "fact.write";
pub const CAP_INTENT: &str = "intent.write";

impl Store {
    pub fn new() -> Self {
        Self::default()
    }

    // ------------------------------------------------------------------ ingest
    pub fn add(&mut self, ev: Event) -> Result<(), Reject> {
        if self.events.contains_key(&ev.id) {
            return Err(Reject::Duplicate);
        }
        check_signature(&ev).map_err(Reject::Invalid)?;
        let missing: Vec<Id> = ev.u.parents.iter().filter(|p| !self.events.contains_key(*p)).cloned().collect();
        if !missing.is_empty() {
            return Err(Reject::MissingParents(missing));
        }
        let u = &ev.u;
        for p in &u.parents {
            if self.events[p].u.lamport >= u.lamport {
                return Err(Reject::Invalid("lamport must exceed every parent".into()));
            }
        }
        self.authorise(&ev)?;
        match u.layer {
            Layer::Fact => {
                let (n, tip) = self.fact_tip.get(&u.author).cloned().unwrap_or((0, String::new()));
                if u.seq != n + 1 {
                    return Err(Reject::Invalid(format!("fact chain gap: have {n}, got {}", u.seq)));
                }
                if n > 0 && u.parents.first() != Some(&tip) {
                    return Err(Reject::Invalid("first parent must be the author's previous fact".into()));
                }
                if let Realm::Rehearsal(b) = &u.realm {
                    if !self.branches.contains_key(b) {
                        return Err(Reject::Invalid("rehearsal on unknown branch".into()));
                    }
                }
            }
            Layer::Intent => {
                if u.realm != Realm::Real {
                    return Err(Reject::Invalid("intents are not rehearsed; branch instead".into()));
                }
                if u.kind != "branch.create" || u.branch.is_some() {
                    let b = u.branch.as_ref().ok_or_else(|| Reject::Invalid("intent needs a branch".into()))?;
                    if !self.branches.contains_key(b) {
                        return Err(Reject::MissingParents(vec![b.clone()]));
                    }
                }
                if u.parents.iter().any(|p| self.events[p].u.layer == Layer::Fact) {
                    return Err(Reject::Invalid("intent parents must be intents".into()));
                }
            }
        }
        // accepted
        let ev_id = ev.id.clone();
        if ev.u.layer == Layer::Fact {
            self.fact_tip.insert(ev.u.author.clone(), (ev.u.seq, ev_id.clone()));
            self.auth.observe(&ev);
        }
        if ev.u.kind == "branch.create" {
            let b = &ev.u.body;
            self.branches.insert(
                ev_id.clone(),
                Branch {
                    id: ev_id.clone(),
                    name: b.get("name").and_then(Value::as_str).unwrap_or("branch").to_string(),
                    parent: ev.u.branch.clone(),
                    fork: ev.u.parents.first().cloned(),
                    horizon: b.get("horizon").and_then(Value::as_i64),
                    created_by: ev.u.author.clone(),
                    ts: ev.u.ts,
                },
            );
        }
        for p in &ev.u.parents {
            self.children.entry(p.clone()).or_default().push(ev_id.clone());
        }
        self.order.push(ev_id.clone());
        self.events.insert(ev_id, ev);
        Ok(())
    }

    fn authorise(&self, ev: &Event) -> Result<(), Reject> {
        let u = &ev.u;
        let need = match (u.layer, u.kind.as_str()) {
            (Layer::Fact, "identity.genesis") => {
                return if u.seq == 1 { Ok(()) } else { Err(Reject::Invalid("genesis must be a key's first fact".into())) };
            }
            (Layer::Fact, "grant") | (Layer::Fact, "revoke") => "grant",
            (Layer::Fact, _) => CAP_FACT,
            (Layer::Intent, "branch.create") => "branch",
            (Layer::Intent, "branch.merge") => "merge",
            (Layer::Intent, _) => CAP_INTENT,
        };
        if u.kind == "revoke" {
            // only the grant's issuer (or someone who could have issued it) may revoke
            let gid = u.body.get("grant").and_then(Value::as_str).unwrap_or("");
            let g = self.auth.grants.iter().find(|g| g.id == gid).ok_or_else(|| Reject::Invalid("unknown grant".into()))?;
            if g.issuer != u.author && self.auth.root_of(&g.subject) != Some(u.author.clone()) {
                return Err(Reject::Invalid("only the issuer or the root identity may revoke".into()));
            }
        }
        if u.kind == "grant" {
            // can't hand out what you don't hold
            if let Some(caps) = u.body.get("caps").and_then(Value::as_array) {
                for c in caps.iter().filter_map(Value::as_str) {
                    if c != "grant" && self.auth.allows(&u.author, c, u.ts).is_err() && !self.auth.roots.contains_key(&u.author) {
                        return Err(Reject::Invalid(format!("cannot grant {c}: issuer doesn't hold it")));
                    }
                }
            }
        }
        self.auth.allows(&u.author, need, u.ts).map(|_| ()).map_err(Reject::Unauthorised)
    }

    /// Add many events in any order; keeps retrying until nothing more fits.
    /// Returns (added, [(event id, reason)] for what was refused).
    pub fn add_all(&mut self, mut evs: Vec<Event>) -> (usize, Vec<(Id, String)>) {
        let mut added = 0;
        let mut refused = vec![];
        loop {
            let mut progress = false;
            let mut rest = vec![];
            for ev in evs {
                match self.add(ev.clone()) {
                    Ok(()) => {
                        added += 1;
                        progress = true
                    }
                    Err(Reject::Duplicate) => {}
                    Err(e @ (Reject::MissingParents(_) | Reject::Unauthorised(_))) => rest.push((ev, e)),
                    Err(e) => refused.push((ev.id.clone(), e.to_string())),
                }
            }
            if rest.is_empty() || !progress {
                refused.extend(rest.into_iter().map(|(ev, e)| (ev.id, e.to_string())));
                return (added, refused);
            }
            evs = rest.into_iter().map(|(ev, _)| ev).collect();
        }
    }

    // ------------------------------------------------------------------ write helpers
    fn next_lamport(&self, parents: &[Id]) -> u64 {
        parents.iter().map(|p| self.events[p].u.lamport).max().unwrap_or(0) + 1
    }

    pub fn fact(&mut self, k: &KeyPair, kind: &str, body: Value, realm: Realm, lane_branch: Option<Id>, ts: i64, causes: &[Id]) -> Result<Event, Reject> {
        let (n, tip) = self.fact_tip.get(&k.public).cloned().unwrap_or((0, String::new()));
        let mut parents = if n > 0 { vec![tip] } else { vec![] };
        for c in causes {
            if !parents.contains(c) {
                parents.push(c.clone());
            }
        }
        let ev = k.seal(Unsigned {
            v: 1, layer: Layer::Fact, realm, author: k.public.clone(), ts,
            lamport: self.next_lamport(&parents), seq: n + 1, parents, branch: lane_branch, kind: kind.into(), body,
        });
        self.add(ev.clone())?;
        Ok(ev)
    }

    pub fn intent(&mut self, k: &KeyPair, branch: &Id, kind: &str, body: Value, ts: i64, extra_parents: &[Id]) -> Result<Event, Reject> {
        let mut parents = self.heads(branch);
        for p in extra_parents {
            if !parents.contains(p) {
                parents.push(p.clone());
            }
        }
        let ev = k.seal(Unsigned {
            v: 1, layer: Layer::Intent, realm: Realm::Real, author: k.public.clone(), ts,
            lamport: self.next_lamport(&parents), seq: 0, parents, branch: Some(branch.clone()), kind: kind.into(), body,
        });
        self.add(ev.clone())?;
        Ok(ev)
    }

    /// Start a branch. `from` = the intent to fork at (any point in the tree); None = parent's current head.
    pub fn branch(&mut self, k: &KeyPair, parent: Option<&Id>, from: Option<&Id>, name: &str, horizon: Option<i64>, ts: i64) -> Result<Id, Reject> {
        let parents: Vec<Id> = match (from, parent) {
            (Some(f), _) => vec![f.clone()],
            (None, Some(p)) => self.heads(p),
            (None, None) => vec![],
        };
        let ev = k.seal(Unsigned {
            v: 1, layer: Layer::Intent, realm: Realm::Real, author: k.public.clone(), ts,
            lamport: self.next_lamport(&parents), seq: 0, parents, branch: parent.cloned(),
            kind: "branch.create".into(), body: json!({"name": name, "horizon": horizon}),
        });
        self.add(ev.clone())?;
        Ok(ev.id)
    }

    // ------------------------------------------------------------------ tree queries
    /// Latest intents of a branch (more than one = parallel lanes wrote concurrently; fine).
    pub fn heads(&self, branch: &Id) -> Vec<Id> {
        let mut on: Vec<&Id> = self.order.iter().filter(|id| {
            let e = &self.events[*id];
            e.u.layer == Layer::Intent && (e.u.branch.as_ref() == Some(branch) || *id == branch)
        }).collect();
        on.retain(|id| !self.children.get(*id).is_some_and(|cs| cs.iter().any(|c| {
            let e = &self.events[c];
            e.u.layer == Layer::Intent && e.u.branch.as_ref() == Some(branch)
        })));
        let mut out: Vec<Id> = on.into_iter().cloned().collect();
        out.sort();
        out
    }

    /// All intents that shape a branch: its own + everything reachable through parents
    /// (the parent branch up to the fork point, and any merged branches).
    pub fn reachable(&self, branch: &Id) -> BTreeSet<Id> {
        let mut seen = BTreeSet::new();
        let mut stack = self.heads(branch);
        while let Some(id) = stack.pop() {
            if !seen.insert(id.clone()) {
                continue;
            }
            for p in &self.events[&id].u.parents {
                if self.events[p].u.layer == Layer::Intent {
                    stack.push(p.clone());
                }
            }
        }
        seen
    }

    pub fn visible_facts(&self, branch: &Id) -> Vec<&Event> {
        let b = self.branches.get(branch);
        let horizon = b.and_then(|b| b.horizon);
        let lineage: HashSet<Id> = self.lineage(branch).into_iter().collect();
        self.order.iter().map(|id| &self.events[id]).filter(|e| e.u.layer == Layer::Fact).filter(|e| match &e.u.realm {
            Realm::Rehearsal(rb) => rb == branch,
            Realm::Real => match horizon {
                None => true,
                Some(h) => e.u.ts <= h || e.u.branch.as_ref().is_some_and(|lb| lineage.contains(lb) && lb == branch),
            },
        }).collect()
    }

    pub fn lineage(&self, branch: &Id) -> Vec<Id> {
        let mut out = vec![];
        let mut cur = Some(branch.clone());
        while let Some(c) = cur {
            out.push(c.clone());
            cur = self.branches.get(&c).and_then(|b| b.parent.clone());
        }
        out
    }

    pub fn main_branch(&self) -> Option<Id> {
        self.order.iter().find(|id| self.branches.get(*id).is_some_and(|b| b.parent.is_none())).cloned()
    }

    // ------------------------------------------------------------------ verify + export
    /// Re-check every event from scratch in a fresh store (ids, signatures, chains, authority).
    pub fn verify(&self) -> Result<usize, String> {
        let mut fresh = Store::new();
        for id in &self.order {
            fresh.add(self.events[id].clone()).map_err(|e| format!("{}: {e}", short(id)))?;
        }
        Ok(fresh.events.len())
    }

    pub fn export(&self) -> Vec<Event> {
        self.order.iter().map(|id| self.events[id].clone()).collect()
    }

    pub fn export_since(&self, have: &HashSet<Id>) -> Vec<Event> {
        self.order.iter().filter(|id| !have.contains(*id)).map(|id| self.events[id].clone()).collect()
    }
}
