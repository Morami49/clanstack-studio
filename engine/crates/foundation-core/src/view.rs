//! Views (state of a branch) and merges.
//!
//! Intents are small operations on keys. The key's first segment is its TYPE, and
//! the type decides how a merge treats disagreements (D-028: controllable between
//! "always ask me" and "rules per type"):
//!   set   {key, value}        register: one current value
//!   unset {key}
//!   add   {key, value}        set: items accumulate (each add is its own item)
//!   remove{key, item}
//!   lane.open {label, device} / lane.close {lane}
//!   branch.merge {from, resolutions:[{key, value|null}]}
//! Merge policy for a type lives in the state itself under `policy/merge/<type>` =
//! "auto" | "ask", so every branch can carry its own rules and changing them is versioned.

use std::collections::{BTreeMap, BTreeSet};

use serde::Serialize;
use serde_json::{json, Value};

use crate::event::{short, Event, Id, KeyPair};
use crate::store::{Reject, Store};

pub fn default_policy(ty: &str) -> &'static str {
    match ty {
        "note" | "list" | "profile" | "label" => "auto",
        _ => "ask", // mode, handoff, privacy, policy, flow, identity, anything new
    }
}

pub fn key_type(key: &str) -> &str {
    key.split('/').next().unwrap_or(key)
}

#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct Reg {
    pub value: Value,
    pub by: String,
    pub at: Id,
    pub lamport: u64,
}

#[derive(Serialize, Clone, Debug, Default)]
pub struct View {
    pub branch: Id,
    pub registers: BTreeMap<String, Reg>,
    pub sets: BTreeMap<String, BTreeMap<Id, Value>>,
    pub lanes: BTreeMap<Id, Value>,
    pub merges: Vec<Value>,
    pub intents: usize,
    pub facts: usize,
}

impl View {
    pub fn policy(&self, ty: &str) -> String {
        self.registers
            .get(&format!("policy/merge/{ty}"))
            .and_then(|r| r.value.as_str().map(String::from))
            .unwrap_or_else(|| default_policy(ty).to_string())
    }
    pub fn get(&self, key: &str) -> Option<&Value> {
        self.registers.get(key).map(|r| &r.value)
    }
}

fn sorted<'a>(store: &'a Store, ids: &BTreeSet<Id>) -> Vec<&'a Event> {
    let mut evs: Vec<&Event> = ids.iter().map(|i| &store.events[i]).collect();
    evs.sort_by(|a, b| (a.u.lamport, &a.id).cmp(&(b.u.lamport, &b.id))); // lamport order is causal order
    evs
}

pub fn fold_ids(store: &Store, branch: &Id, ids: &BTreeSet<Id>) -> View {
    let mut v = View { branch: branch.clone(), ..Default::default() };
    for e in sorted(store, ids) {
        let b = &e.u.body;
        let key = b.get("key").and_then(Value::as_str).unwrap_or("").to_string();
        let reg = |val: Value| Reg { value: val, by: e.u.author.clone(), at: e.id.clone(), lamport: e.u.lamport };
        match e.u.kind.as_str() {
            "set" => {
                v.registers.insert(key, reg(b.get("value").cloned().unwrap_or(Value::Null)));
            }
            "unset" => {
                v.registers.remove(&key);
            }
            "add" => {
                v.sets.entry(key).or_default().insert(e.id.clone(), b.get("value").cloned().unwrap_or(Value::Null));
            }
            "remove" => {
                if let Some(item) = b.get("item").and_then(Value::as_str) {
                    if let Some(s) = v.sets.get_mut(&key) {
                        s.remove(item);
                    }
                }
            }
            "lane.open" => {
                v.lanes.insert(e.id.clone(), json!({"label": b.get("label"), "device": b.get("device"), "by": short(&e.u.author), "ts": e.u.ts}));
            }
            "lane.close" => {
                if let Some(l) = b.get("lane").and_then(Value::as_str) {
                    v.lanes.remove(l);
                }
            }
            "branch.merge" => {
                for r in b.get("resolutions").and_then(Value::as_array).cloned().unwrap_or_default() {
                    let k = r.get("key").and_then(Value::as_str).unwrap_or("").to_string();
                    match r.get("value") {
                        Some(Value::Null) | None => {
                            v.registers.remove(&k);
                        }
                        Some(val) => {
                            v.registers.insert(k, reg(val.clone()));
                        }
                    }
                }
                v.merges.push(json!({"id": e.id, "from": b.get("from"), "by": short(&e.u.author)}));
            }
            _ => {}
        }
        v.intents += 1;
    }
    v
}

pub fn view(store: &Store, branch: &Id) -> View {
    let mut v = fold_ids(store, branch, &store.reachable(branch));
    v.facts = store.visible_facts(branch).len();
    v
}

/// View of a branch as it was at a given intent (any point in the tree).
pub fn view_at(store: &Store, at: &Id) -> View {
    let mut seen = BTreeSet::new();
    let mut stack = vec![at.clone()];
    while let Some(id) = stack.pop() {
        if seen.insert(id.clone()) {
            stack.extend(store.events[&id].u.parents.iter().filter(|p| store.events[*p].u.layer == crate::event::Layer::Intent).cloned());
        }
    }
    let br = store.events[at].u.branch.clone().unwrap_or_else(|| at.clone());
    fold_ids(store, &br, &seen)
}

#[derive(Serialize, Clone, Debug)]
pub struct Conflict {
    pub key: String,
    pub base: Option<Value>,
    pub ours: Option<Value>,
    pub theirs: Option<Value>,
    pub policy: String,
}

#[derive(Serialize, Clone, Debug)]
pub struct MergePlan {
    pub from: Id,
    pub into: Id,
    /// changes that apply by themselves (one side changed, or the type's policy is auto)
    pub auto: Vec<Value>,
    /// disagreements a human must settle (policy = ask)
    pub conflicts: Vec<Conflict>,
    pub new_intents: usize,
}

pub fn merge_preview(store: &Store, from: &Id, into: &Id) -> MergePlan {
    let rs = store.reachable(from);
    let rt = store.reachable(into);
    let common: BTreeSet<Id> = rs.intersection(&rt).cloned().collect();
    let base = fold_ids(store, into, &common);
    let theirs = fold_ids(store, from, &rs);
    let ours = fold_ids(store, into, &rt);
    let keys: BTreeSet<&String> = base.registers.keys().chain(theirs.registers.keys()).chain(ours.registers.keys()).collect();
    let (mut auto, mut conflicts) = (vec![], vec![]);
    for k in keys {
        let (b, o, t) = (base.get(k), ours.get(k), theirs.get(k));
        if t == b || t == o {
            continue; // they didn't change it, or both ended up the same
        }
        if o == b {
            auto.push(json!({"key": k, "value": t, "why": "only their side changed it"}));
            continue;
        }
        let policy = ours.policy(key_type(k));
        if policy == "auto" {
            let (lo, lt) = (ours.registers.get(k).map(|r| r.lamport).unwrap_or(0), theirs.registers.get(k).map(|r| r.lamport).unwrap_or(0));
            auto.push(json!({"key": k, "value": if lt > lo { t } else { o }, "why": "both changed; type merges automatically (latest wins)"}));
        } else {
            conflicts.push(Conflict { key: k.clone(), base: b.cloned(), ours: o.cloned(), theirs: t.cloned(), policy });
        }
    }
    MergePlan { from: from.clone(), into: into.clone(), auto, conflicts, new_intents: rs.difference(&rt).count() }
}

/// Commit a merge. Every 'ask' conflict needs a resolution {key, value} (value null = remove).
/// Auto changes are written as resolutions too, so the merge reads the same on every node.
pub fn merge(store: &mut Store, k: &KeyPair, from: &Id, into: &Id, resolutions: &[Value], ts: i64) -> Result<Event, Reject> {
    let plan = merge_preview(store, from, into);
    let unresolved: Vec<&str> = plan
        .conflicts
        .iter()
        .filter(|c| !resolutions.iter().any(|r| r.get("key").and_then(Value::as_str) == Some(&c.key)))
        .map(|c| c.key.as_str())
        .collect();
    if !unresolved.is_empty() {
        return Err(Reject::Invalid(format!("unresolved conflicts: {}", unresolved.join(", "))));
    }
    let mut all: Vec<Value> = plan.auto.iter().map(|a| json!({"key": a["key"], "value": a["value"]})).collect();
    all.extend(resolutions.iter().cloned());
    let heads = store.heads(from);
    store.intent(k, into, "branch.merge", json!({"from": from, "resolutions": all}), ts, &heads)
}

/// Data for drawing the version tree.
pub fn tree(store: &Store) -> Value {
    let branches: Vec<Value> = store.order.iter().filter_map(|id| store.branches.get(id)).map(|b| {
        let v = view(store, &b.id);
        json!({"id": b.id, "name": b.name, "parent": b.parent, "fork": b.fork, "horizon": b.horizon,
               "heads": store.heads(&b.id), "lanes": v.lanes, "facts": v.facts, "by": short(&b.created_by), "ts": b.ts})
    }).collect();
    let intents: Vec<Value> = store.order.iter().map(|id| &store.events[id]).filter(|e| e.u.layer == crate::event::Layer::Intent).map(|e| {
        let b = &e.u.body;
        let summary = match e.u.kind.as_str() {
            "set" => format!("{} = {}", b["key"].as_str().unwrap_or(""), b["value"]),
            "unset" => format!("unset {}", b["key"].as_str().unwrap_or("")),
            "add" => format!("+ {}: {}", b["key"].as_str().unwrap_or(""), b["value"]),
            "branch.create" => format!("branch '{}'", b["name"].as_str().unwrap_or("")),
            "branch.merge" => format!("merge ← {}", short(b["from"].as_str().unwrap_or(""))),
            "lane.open" => format!("lane opened: {}", b["label"].as_str().unwrap_or("")),
            "lane.close" => "lane closed".to_string(),
            k => k.to_string(),
        };
        let own_branch = if e.u.kind == "branch.create" { Some(e.id.clone()) } else { e.u.branch.clone() };
        json!({"id": e.id, "branch": own_branch, "parents": e.u.parents, "lamport": e.u.lamport,
               "kind": e.u.kind, "summary": summary, "by": short(&e.u.author), "ts": e.u.ts})
    }).collect();
    json!({"branches": branches, "intents": intents,
           "facts": store.order.iter().filter(|id| store.events[*id].u.layer == crate::event::Layer::Fact).count()})
}
