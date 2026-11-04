//! The stories in STORIES.md, as executable tests.

use foundation_core::{merge, merge_preview, view, view_at, KeyPair, Realm, Reject, Store};
use serde_json::json;

fn kp(n: u8) -> KeyPair {
    KeyPair::from_seed([n; 32])
}

/// Nowed's identity, a laptop and a VM device, and an outside-AI sub-identity.
fn setup() -> (Store, KeyPair, KeyPair, KeyPair, KeyPair, String) {
    let mut s = Store::new();
    let (me, laptop, vm, chatgpt) = (kp(1), kp(2), kp(3), kp(4));
    s.fact(&me, "identity.genesis", json!({"label": "nowed"}), Realm::Real, None, 1, &[]).unwrap();
    s.fact(&me, "grant", json!({"subject": laptop.public, "role": "device", "label": "laptop", "caps": ["fact.write", "intent.write", "branch", "merge"]}), Realm::Real, None, 2, &[]).unwrap();
    s.fact(&me, "grant", json!({"subject": vm.public, "role": "device", "label": "oracle-vm", "caps": ["fact.write", "intent.write"]}), Realm::Real, None, 3, &[]).unwrap();
    s.fact(&me, "grant", json!({"subject": chatgpt.public, "role": "sub_identity", "label": "ext:chatgpt", "caps": ["intent.write", "branch"]}), Realm::Real, None, 4, &[]).unwrap();
    let main = s.branch(&me, None, None, "main", None, 5).unwrap();
    (s, me, laptop, vm, chatgpt, main)
}

#[test]
fn s0_identities_devices_and_limits() {
    let (mut s, me, laptop, vm, chatgpt, main) = setup();
    s.intent(&laptop, &main, "set", json!({"key": "mode/agent:next-step", "value": "suggest"}), 10, &[]).unwrap();
    // the VM may write but not merge; ChatGPT may not record facts
    let b = s.branch(&laptop, Some(&main), None, "try", None, 11).unwrap();
    assert!(matches!(merge(&mut s, &vm, &b, &main, &[], 12), Err(Reject::Unauthorised(_))));
    assert!(s.fact(&chatgpt, "click", json!({}), Realm::Real, None, 13, &[]).is_err());
    // a sub-identity can't hand out more than it holds
    let x = kp(9);
    assert!(s.fact(&chatgpt, "grant", json!({"subject": x.public, "role": "device", "caps": ["merge"]}), Realm::Real, None, 14, &[]).is_err());
    // revoke the VM: it can no longer write
    let g = s.auth.grants.iter().find(|g| g.label == "oracle-vm").unwrap().id.clone();
    s.fact(&me, "revoke", json!({"grant": g}), Realm::Real, None, 20, &[]).unwrap();
    assert!(s.intent(&vm, &main, "set", json!({"key": "note/x", "value": 1}), 21, &[]).is_err());
    assert!(s.verify().is_ok());
}

#[test]
fn s1_resume_tuesday_in_a_parallel_lane() {
    let (mut s, _me, laptop, _vm, _c, main) = setup();
    s.fact(&laptop, "click", json!({"step": "click|EXCEL|Status"}), Realm::Real, None, 100, &[]).unwrap();
    let tue = s.intent(&laptop, &main, "set", json!({"key": "handoff/save", "value": "agent:next-step@suggest"}), 101, &[]).unwrap();
    s.fact(&laptop, "click", json!({"step": "click|ClickUp|Done"}), Realm::Real, None, 200, &[]).unwrap();
    s.intent(&laptop, &main, "set", json!({"key": "handoff/save", "value": "agent:next-step@act"}), 201, &[]).unwrap();

    // Resume from Tuesday's point, in a new lane, while main carries on
    let resumed = s.branch(&laptop, Some(&main), Some(&tue.id), "resume-tuesday", Some(150), 300).unwrap();
    s.intent(&laptop, &resumed, "lane.open", json!({"label": "rethink saving", "device": "laptop"}), 301, &[]).unwrap();
    s.intent(&laptop, &main, "lane.open", json!({"label": "today", "device": "laptop"}), 302, &[]).unwrap();

    let vr = view(&s, &resumed);
    assert_eq!(vr.get("handoff/save"), Some(&json!("agent:next-step@suggest")));
    assert_eq!(vr.facts, 5); // real facts up to ts 150: genesis + 3 grants + Tuesday's click
    assert_eq!(vr.lanes.len(), 1);
    let vm_ = view(&s, &main);
    assert_eq!(vm_.get("handoff/save"), Some(&json!("agent:next-step@act")));
    assert_eq!(view_at(&s, &tue.id).get("handoff/save"), Some(&json!("agent:next-step@suggest")));
}

#[test]
fn s2_outside_ai_edits_on_its_own_branch_then_merge() {
    let (mut s, _me, laptop, _vm, chatgpt, main) = setup();
    s.intent(&laptop, &main, "set", json!({"key": "mode/agent:next-step", "value": "observe"}), 10, &[]).unwrap();
    let ai = s.branch(&chatgpt, Some(&main), None, "chatgpt: tighten saving", None, 11).unwrap();
    s.intent(&chatgpt, &ai, "set", json!({"key": "mode/agent:next-step", "value": "act"}), 12, &[]).unwrap();
    s.intent(&chatgpt, &ai, "add", json!({"key": "note/save", "value": "always saved after status edit"}), 13, &[]).unwrap();
    s.intent(&laptop, &main, "set", json!({"key": "mode/agent:next-step", "value": "suggest"}), 14, &[]).unwrap();
    s.intent(&laptop, &main, "add", json!({"key": "note/save", "value": "check PO first"}), 15, &[]).unwrap();

    let plan = merge_preview(&s, &ai, &main);
    assert_eq!(plan.conflicts.len(), 1, "mode is an 'ask' type");
    assert_eq!(plan.conflicts[0].key, "mode/agent:next-step");
    // chatgpt may not merge into main by itself
    assert!(merge(&mut s, &chatgpt, &ai, &main, &[], 16).is_err());
    // unresolved conflict blocks the merge
    assert!(merge(&mut s, &laptop, &ai, &main, &[], 17).is_err());
    merge(&mut s, &laptop, &ai, &main, &[json!({"key": "mode/agent:next-step", "value": "suggest"})], 18).unwrap();
    let v = view(&s, &main);
    assert_eq!(v.get("mode/agent:next-step"), Some(&json!("suggest")));
    assert_eq!(v.sets["note/save"].len(), 2, "notes merge by themselves");
    assert_eq!(v.merges.len(), 1);
}

#[test]
fn s2b_merge_policy_is_itself_controllable_and_versioned() {
    let (mut s, _me, laptop, _vm, chatgpt, main) = setup();
    s.intent(&laptop, &main, "set", json!({"key": "policy/merge/mode", "value": "auto"}), 9, &[]).unwrap();
    let ai = s.branch(&chatgpt, Some(&main), None, "ai", None, 10).unwrap();
    s.intent(&chatgpt, &ai, "set", json!({"key": "mode/a", "value": "act"}), 11, &[]).unwrap();
    s.intent(&laptop, &main, "set", json!({"key": "mode/a", "value": "observe"}), 12, &[]).unwrap();
    let plan = merge_preview(&s, &ai, &main);
    assert!(plan.conflicts.is_empty());
    assert_eq!(plan.auto.len(), 1);
}

#[test]
fn s3_two_devices_offline_then_sync_any_order() {
    let (s0, _me, laptop, vm, _c, main) = setup();
    let base = s0.export();
    let mut a = Store::new();
    a.add_all(base.clone());
    let mut b = Store::new();
    let mut shuffled = base.clone();
    shuffled.reverse(); // arrival order doesn't matter
    let (n, errs) = b.add_all(shuffled);
    assert_eq!((n, errs.len()), (base.len(), 0));

    a.fact(&laptop, "click", json!({"on": "train"}), Realm::Real, None, 50, &[]).unwrap();
    a.intent(&laptop, &main, "add", json!({"key": "note/x", "value": "from laptop"}), 51, &[]).unwrap();
    b.fact(&vm, "observation", json!({"cron": "nightly"}), Realm::Real, None, 52, &[]).unwrap();
    b.intent(&vm, &main, "add", json!({"key": "note/x", "value": "from vm"}), 53, &[]).unwrap();

    let (ea, eb) = (a.export(), b.export());
    let (mut ra, mut rb) = (ea.clone(), eb.clone());
    ra.reverse();
    rb.reverse();
    a.add_all(rb);
    b.add_all(ra);
    let (va, vb) = (view(&a, &main), view(&b, &main));
    assert_eq!(va.sets, vb.sets);
    assert_eq!(va.sets["note/x"].len(), 2);
    assert_eq!(s0.verify().is_ok() && a.verify().is_ok() && b.verify().is_ok(), true);
    assert_eq!(a.heads(&main), b.heads(&main), "two concurrent heads, same on both");
}

#[test]
fn s4_rehearsal_facts_stay_on_their_branch() {
    let (mut s, _me, laptop, _vm, _c, main) = setup();
    let reh = s.branch(&laptop, Some(&main), None, "rehearse invoice run", None, 10).unwrap();
    s.fact(&laptop, "click", json!({"sim": true}), Realm::Rehearsal(reh.clone()), Some(reh.clone()), 11, &[]).unwrap();
    assert_eq!(view(&s, &reh).facts, view(&s, &main).facts + 1);
}

#[test]
fn tampering_and_gaps_are_refused() {
    let (s, _me, laptop, ..) = setup();
    let mut s2 = Store::new();
    s2.add_all(s.export());
    let mut good = Store::new();
    good.add_all(s.export());
    let ev = good.fact(&laptop, "click", json!({"x": 1}), Realm::Real, None, 9, &[]).unwrap();
    let mut forged = ev.clone();
    forged.u.body = json!({"x": 666});
    assert!(matches!(s2.add(forged), Err(Reject::Invalid(_))));
    let next = good.fact(&laptop, "click", json!({"x": 2}), Realm::Real, None, 10, &[]).unwrap();
    assert!(matches!(s2.add(next.clone()), Err(Reject::MissingParents(_))));
    s2.add(ev).unwrap();
    s2.add(next).unwrap();
    assert!(s2.verify().is_ok());
}
