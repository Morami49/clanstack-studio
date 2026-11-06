//! Hub scenarios: S41 (a provider vanishes), S42 (offline, catch up later), D-095 stage A import.
use foundation_core::event::{KeyPair, Realm};
use foundation_core::store::Store;
use hub_core::*;
use serde_json::json;

fn key(n: u8) -> KeyPair { KeyPair::from_seed([n; 32]) }

/// A device with its own identity writing a few facts.
fn device_events(k: &KeyPair, n: usize) -> Vec<foundation_core::event::Event> {
    let mut s = Store::new();
    let mut v = vec![s.fact(k, "identity.genesis", json!({"label": "phone"}), Realm::Real, None, 1, &[]).unwrap()];
    for i in 0..n { v.push(s.fact(k, "capture", json!({"note": i}), Realm::Real, None, 2 + i as i64, &[]).unwrap()); }
    v
}

#[test]
fn push_in_any_order_and_resend_safely() {
    let mut h = Hub::new();
    let mut evs = device_events(&key(1), 5);
    evs.reverse(); // arrives backwards
    let r = h.push(evs.clone());
    assert_eq!((r.added.len(), r.refused.len()), (6, 0));
    let again = h.push(evs);
    assert_eq!((again.added.len(), again.duplicates), (0, 6));
    assert!(h.status().verified);
}

#[test]
fn tampered_event_is_refused() {
    let mut h = Hub::new();
    let mut evs = device_events(&key(1), 1);
    evs[1].u.body = json!({"note": "changed after signing"});
    let r = h.push(evs);
    assert_eq!(r.added.len(), 1);
    assert!(r.refused[0].1.contains("invalid"));
}

#[test]
fn s41_provider_vanishes_and_another_node_carries_on() {
    // Cloudflare hub holds the record; a PC node pulls it. The Cloudflare node disappears.
    let mut cloud = Hub::new();
    cloud.push(device_events(&key(1), 10));
    let mut pc = Hub::new();
    let mut after = 0;
    loop { let p = cloud.pull(after, 4); pc.push(p.events); after = p.next; if after == p.total { break; } }
    drop(cloud);
    // A new rung starts empty and catches up from the PC: nothing is lost.
    let mut oracle = Hub::new();
    oracle.push(pc.pull(0, 1000).events);
    assert_eq!(oracle.status().events, 11);
    assert!(oracle.status().verified);
}

#[test]
fn s42_offline_writes_merge_when_back() {
    let (phone, pc_key) = (key(1), key(2));
    let mut hub = Hub::new();
    hub.push(device_events(&pc_key, 2));
    // phone captures while the PC is off and the hub is unreachable
    let offline = device_events(&phone, 3);
    let r = hub.push(offline);
    assert_eq!(r.added.len(), 4);
    let mut pc = Hub::new();
    pc.push(hub.pull(0, 100).events);
    assert_eq!(pc.status().events, 7);
}

#[test]
fn restore_from_persisted_order() {
    let mut h = Hub::new();
    h.push(device_events(&key(1), 3));
    let persisted = h.pull(0, 100).events;
    let (back, r) = Hub::restore(persisted);
    assert!(r.refused.is_empty());
    assert_eq!(back.status().events, 4);
}

#[test]
fn import_studio_events_once_in_a_stable_order() {
    let imp = key(9);
    let mut h = Hub::new();
    let docs = vec![
        ("claude-b".to_string(), json!({"ts": "2026-11-05T02:00:00.000Z", "kind": "answer", "item": "Q-x", "body": {"text": "A"}})),
        ("claude-a".to_string(), json!({"ts": "2026-11-05T01:00:00.000Z", "kind": "item.create", "body": {"id": "Q-x"}})),
    ];
    let made = h.import(&imp, docs.clone(), 100).unwrap();
    assert_eq!(made.len(), 3); // importer identity + 2 events
    assert_eq!(made[1].u.body["doc_id"], "claude-a"); // earlier Studio ts first
    assert!(h.import(&imp, docs, 200).unwrap().is_empty()); // second export run adds nothing
    assert!(h.has_imported("claude-b"));
    // another node receiving these facts knows what was imported too
    let (other, _) = Hub::restore(h.pull(0, 100).events);
    assert!(other.has_imported("claude-a"));
    assert_eq!(other.status().imported_studio_events, 2);
}

#[test]
fn outsider_cannot_import_into_someone_elses_chain() {
    let mut h = Hub::new();
    let imp = key(9);
    let made = h.import(&imp, vec![("d1".into(), json!({"ts": "1"}))], 1).unwrap();
    // a stranger re-signs a copy of the import with their own key but claims the importer's chain
    let mut forged = made[1].clone();
    forged.u.body["doc_id"] = json!("d-forged");
    let r = Hub::new().push(vec![made[0].clone(), forged]);
    assert_eq!(r.added.len(), 1);
    assert_eq!(r.refused.len(), 1);
}

#[test]
fn c_now_two_writers_merge_without_loops() {
    // Q44 "C now": Studio Web and a PC node both write; each side ends with both writes, once.
    let (imp, pc) = (key(9), key(2));
    let mut hub = Hub::new();
    // 1. Studio Web writes an answer; the export brings it in.
    hub.import(&imp, vec![("claude-1".into(), json!({"ts": "2026-11-06T10:00:00.000Z", "kind": "answer", "item": "Q-x", "body": {"text": "A"}}))], 1).unwrap();
    // 2. Nowed answers the same question on his PC node, offline, slightly later.
    let mut s = Store::new();
    let pc_evs = vec![
        s.fact(&pc, "identity.genesis", json!({"label": "pc"}), Realm::Real, None, 1, &[]).unwrap(),
        s.fact(&pc, WRITE_KIND, json!({"ts": "2026-11-06T10:05:00.000Z", "kind": "answer", "item": "Q-x", "body": {"text": "C now"}}), Realm::Real, None, 2, &[]).unwrap(),
    ];
    hub.push(pc_evs.clone());
    // 3. Hub → Studio Web: only the PC write goes back, with a stable id and its origin.
    let (docs, next) = hub.to_studio(0, 100);
    assert_eq!(docs.len(), 1);
    assert_eq!(docs[0].0, studio_doc_id(&pc_evs[1].id));
    assert_eq!(docs[0].1["body"]["text"], "C now");
    assert_eq!(docs[0].1["origin"], json!(pc.public));
    assert_eq!(hub.to_studio(next, 100).0.len(), 0); // cursor: nothing new
    // 4. Studio Web now holds that doc; the next export includes it. It must not be imported again.
    let before = hub.status().events;
    let back = hub.import(&imp, vec![docs[0].clone(), ("claude-1".into(), json!({"ts": "x"}))], 3).unwrap();
    assert!(back.is_empty());
    assert_eq!(hub.status().events, before);
    // 5. Any other node rebuilt from the record knows the same, so no node loops either.
    let (mut other, _) = Hub::restore(hub.pull(0, 100).events);
    assert!(other.import(&imp, vec![docs[0].clone()], 4).is_ok());
    assert_eq!(other.to_studio(0, 100).0, docs);
}
