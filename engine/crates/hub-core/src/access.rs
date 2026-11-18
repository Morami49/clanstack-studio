//! Who may see and change what on the shared record (A1 d step one, 18 Nov 2026).
//!
//! Until now every signed-in login saw the whole shared record, which was fine while the only login was the owner.
//! Before a tenant (the first is Insydr) signs in, a member sees only:
//!   - events about items the owner granted them, by id or by id prefix (a space, e.g. "INSYDR-");
//!   - events they wrote themselves.
//! Owners see everything. Grants are events on the record (`access.grant`, `access.revoke`), written only by an owner,
//! so who could see what at any time can be replayed, like everything else.
//!
//! With no owners configured, everyone signed in counts as an owner (the behaviour before this module), so existing
//! single-owner hubs and tests are unchanged.

use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};

pub const KINDS: [&str; 2] = ["access.grant", "access.revoke"];

#[derive(Default, Clone, Debug)]
struct Grant {
    items: BTreeSet<String>,
    prefixes: BTreeSet<String>,
}

#[derive(Default, Clone, Debug)]
pub struct State {
    owners: Vec<String>,
    grants: BTreeMap<String, Grant>,
}

fn lc(s: &str) -> String { s.trim().to_ascii_lowercase() }

/// The item an event is about: its target, or the id it creates.
pub fn subject(ev: &Value) -> Option<String> {
    if let Some(i) = ev.get("item").and_then(Value::as_str) { return Some(i.to_string()); }
    if ev.get("kind").and_then(Value::as_str) == Some("item.create") {
        return ev.pointer("/body/id").and_then(Value::as_str).map(str::to_string);
    }
    None
}

fn author_login(ev: &Value) -> Option<String> {
    ev.pointer("/author/id").and_then(Value::as_str).and_then(|a| a.strip_prefix("github:")).map(lc)
}

fn strings(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array).map(|a| a.iter().filter_map(Value::as_str).map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).take(500).collect()).unwrap_or_default()
}

impl State {
    pub fn fold(owners: &[String], events: &[Value]) -> State {
        let mut st = State { owners: owners.iter().map(|o| lc(o)).filter(|o| !o.is_empty()).collect(), grants: BTreeMap::new() };
        for ev in events { st.observe(ev); }
        st
    }

    pub fn observe(&mut self, ev: &Value) {
        let kind = ev.get("kind").and_then(Value::as_str).unwrap_or("");
        if !KINDS.contains(&kind) { return; }
        // only an owner's grant counts, whatever got onto the record
        if !author_login(ev).map(|a| self.is_owner(&a)).unwrap_or(false) { return; }
        let body = ev.get("body").cloned().unwrap_or(Value::Null);
        let Some(who) = body.get("login").and_then(Value::as_str).map(lc).filter(|s| !s.is_empty()) else { return };
        let g = self.grants.entry(who).or_default();
        let items = strings(body.get("items"));
        let prefixes = strings(body.get("prefixes"));
        if kind == "access.grant" {
            g.items.extend(items);
            g.prefixes.extend(prefixes);
        } else {
            for i in &items { g.items.remove(i); }
            for p in &prefixes { g.prefixes.remove(p); }
        }
    }

    pub fn is_owner(&self, login: &str) -> bool {
        self.owners.is_empty() || self.owners.contains(&lc(login))
    }

    /// May `login` see items with this id?
    pub fn granted(&self, login: &str, item: &str) -> bool {
        if self.is_owner(login) { return true; }
        let Some(g) = self.grants.get(&lc(login)) else { return false };
        g.items.contains(item) || g.prefixes.iter().any(|p| item.starts_with(p.as_str()))
    }

    /// May `login` see this event? Owners see all; members see granted items and their own writes.
    pub fn visible(&self, login: &str, ev: &Value) -> bool {
        if self.is_owner(login) { return true; }
        if author_login(ev).as_deref() == Some(lc(login).as_str()) { return true; }
        subject(ev).map(|s| self.granted(login, &s)).unwrap_or(false)
    }

    /// May `login` write an event of `kind` about `item`? Grants are owner-only; members write only inside grants.
    pub fn check_write(&self, login: &str, kind: &str, item: Option<&str>) -> Result<(), String> {
        if self.is_owner(login) { return Ok(()); }
        if KINDS.contains(&kind) { return Err("only an owner can grant or revoke access".into()); }
        match item {
            Some(i) if self.granted(login, i) => Ok(()),
            Some(i) => Err(format!("{i} isn't in a space you've been given")),
            None => Err("this needs an item inside a space you've been given".into()),
        }
    }

    /// What a member was given, for /studio/api/me.
    pub fn grants_of(&self, login: &str) -> Value {
        let g = self.grants.get(&lc(login)).cloned().unwrap_or_default();
        serde_json::json!({"items": g.items, "prefixes": g.prefixes})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn ev(author: &str, kind: &str, item: Option<&str>, body: Value) -> Value {
        json!({"author": {"id": format!("github:{author}")}, "kind": kind, "item": item, "body": body})
    }

    #[test]
    fn a_member_sees_only_granted_spaces_and_their_own_writes() {
        let owners = vec!["Morami49".to_string()];
        let grant = ev("Morami49", "access.grant", None, json!({"login": "nassar", "prefixes": ["INSYDR-"]}));
        let st = State::fold(&owners, &[grant]);
        let governance = ev("Morami49", "comment", Some("D-nodach-org-model"), json!({"text": "v1.0"}));
        let space = ev("Morami49", "item.create", None, json!({"id": "INSYDR-pilot"}));
        let mine = ev("Nassar", "comment", Some("D-other"), json!({}));
        assert!(st.visible("morami49", &governance), "owners see everything");
        assert!(!st.visible("nassar", &governance), "a member never sees governance");
        assert!(st.visible("Nassar", &space));
        assert!(st.visible("nassar", &mine));
        assert!(st.check_write("nassar", "comment", Some("INSYDR-pilot")).is_ok());
        assert!(st.check_write("nassar", "comment", Some("D-nodach-org-model")).is_err());
        assert!(st.check_write("nassar", "access.grant", None).is_err());
    }

    #[test]
    fn grants_from_non_owners_are_ignored_and_revokes_take_effect() {
        let owners = vec!["morami49".to_string()];
        let forged = ev("nassar", "access.grant", None, json!({"login": "nassar", "prefixes": ["D-"]}));
        let grant = ev("morami49", "access.grant", None, json!({"login": "nassar", "items": ["X-1", "X-2"]}));
        let revoke = ev("morami49", "access.revoke", None, json!({"login": "nassar", "items": ["X-1"]}));
        let st = State::fold(&owners, &[forged, grant, revoke]);
        assert!(!st.granted("nassar", "D-nodach-org-model"));
        assert!(!st.granted("nassar", "X-1"));
        assert!(st.granted("nassar", "X-2"));
    }

    #[test]
    fn with_no_owners_configured_everyone_is_an_owner_as_before() {
        let st = State::fold(&[], &[]);
        assert!(st.visible("anyone", &json!({"item": "D-1"})));
        assert!(st.check_write("anyone", "access.grant", None).is_ok());
    }
}
