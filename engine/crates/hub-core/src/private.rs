//! The Private tier (D-nodach-identity, Q53 A, build piece I1).
//!
//! Private items live on the hub, encrypted at rest, so they survive a new browser or device. They are
//! never part of the signed shared record: they are stored apart, served only to their owner (and to
//! grantees such as the Claude connector), and never appear in `read_events` or `/studio/api/events`.
//!
//! Pure logic: no clock, no randomness, no network. The node supplies the hub secret and a fresh nonce.
//!
//! - Envelope keys (A-spec-identity): a key-encryption key (KEK) comes from the hub secret; each owner has a random
//!   data key (DEK), stored only wrapped by the KEK, with a version. Rotating the hub secret re-wraps the small DEK
//!   table (the node tries the previous secret, then re-wraps with the new one); the data itself never changes.
//! - Each row is AES-256-GCM sealed under the owner's DEK. The owner, key version, path and doc id are bound in as
//!   associated data, so a sealed row copied to another owner, path or id fails to open instead of leaking.
//! - The Sealed tier (passphrase only the owner knows, I4) is a layer on top: the browser encrypts first,
//!   and the hub stores the result here like any other private row, without being able to read it.
//!
//! Losing the hub secret (with no previous copy kept) makes every private row unreadable, so the owner can export a
//! decrypted copy at any time (`/studio/api/private/export`).

use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Nonce};
use sha2::{Digest, Sha256};

pub const NONCE_LEN: usize = 12;
/// Largest private event a browser may send (bytes of JSON). Files have their own encrypted path.
pub const MAX_EVENT_BYTES: usize = 64 * 1024;

/// The key-encryption key: SHA-256 over a fixed label and the hub secret. It only ever wraps data keys.
pub fn kek(secret: &str) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"nodach-private-kek-v1\0");
    h.update(secret.trim().as_bytes());
    h.finalize().into()
}

fn gcm_seal(key: &[u8; 32], nonce: &[u8; NONCE_LEN], aad: &[u8], plaintext: &[u8]) -> String {
    let c = Aes256Gcm::new_from_slice(key).expect("32-byte key");
    let ct = c.encrypt(Nonce::from_slice(nonce), Payload { msg: plaintext, aad })
        .expect("AES-GCM encryption cannot fail for in-memory buffers");
    let mut out = nonce.to_vec();
    out.extend(ct);
    hex::encode(out)
}

fn gcm_open(key: &[u8; 32], aad: &[u8], blob_hex: &str) -> Option<Vec<u8>> {
    let raw = hex::decode(blob_hex).ok()?;
    if raw.len() < NONCE_LEN + 16 { return None; }
    let (n, ct) = raw.split_at(NONCE_LEN);
    let c = Aes256Gcm::new_from_slice(key).ok()?;
    c.decrypt(Nonce::from_slice(n), Payload { msg: ct, aad }).ok()
}

fn dek_aad(owner: &str, version: u32) -> Vec<u8> {
    format!("dek\0{}\0{}", owner.to_ascii_lowercase(), version).into_bytes()
}

fn row_aad(owner: &str, version: u32, path: &str, doc_id: &str) -> Vec<u8> {
    format!("row\0{}\0{}\0{}\0{}", owner.to_ascii_lowercase(), version, path, doc_id).into_bytes()
}

/// Wrap an owner's data key under the KEK (stored as hex in the node's key table).
pub fn wrap_dek(kek: &[u8; 32], nonce: &[u8; NONCE_LEN], owner: &str, version: u32, dek: &[u8; 32]) -> String {
    gcm_seal(kek, nonce, &dek_aad(owner, version), dek)
}

/// Unwrap a data key. None if the KEK is wrong (e.g. the secret changed) or the row belongs to someone else.
pub fn unwrap_dek(kek: &[u8; 32], owner: &str, version: u32, wrapped_hex: &str) -> Option<[u8; 32]> {
    gcm_open(kek, &dek_aad(owner, version), wrapped_hex)?.try_into().ok()
}

/// Seal one private row under the owner's data key. Returns hex(nonce || ciphertext+tag).
pub fn seal(dek: &[u8; 32], nonce: &[u8; NONCE_LEN], owner: &str, version: u32, path: &str, doc_id: &str, plaintext: &[u8]) -> String {
    gcm_seal(dek, nonce, &row_aad(owner, version, path, doc_id), plaintext)
}

/// Open a sealed row. None if it was tampered with, or belongs to another owner, key version, path or doc id.
pub fn open(dek: &[u8; 32], owner: &str, version: u32, path: &str, doc_id: &str, blob_hex: &str) -> Option<Vec<u8>> {
    gcm_open(dek, &row_aad(owner, version, path, doc_id), blob_hex)
}

/// A private path belongs to `owner` only if it is `data/users/<owner>/<rest>` or `data/users/github:<owner>/<rest>`
/// (Studio's user id form), case-insensitive on the login, with a short rest of plain path characters.
pub fn path_owned_by(path: &str, owner: &str) -> bool {
    let Some(rest) = path.strip_prefix("data/users/") else { return false };
    let Some((login, tail)) = rest.split_once('/') else { return false };
    let login = login.strip_prefix("github:").unwrap_or(login);
    login.eq_ignore_ascii_case(owner)
        && !tail.is_empty() && tail.len() <= 120
        && tail.split('/').all(|s| !s.is_empty() && s != "." && s != "..")
        && tail.bytes().all(|b| b.is_ascii_alphanumeric() || b"/-_.".contains(&b))
}

/// Most events one `write_private_batch` call may carry.
pub const MAX_BATCH: usize = 200;

/// The doc id a keyed private write gets: deterministic, so a re-run of the same import is a no-op.
pub fn doc_id_for(login: &str, path: &str, key: &str) -> String {
    format!("cp-{}", &hex::encode(Sha256::digest(format!("{}\0{}\0{}", login.to_ascii_lowercase(), path, key).as_bytes()))[..32])
}

/// SHA-256 of an event's JSON (object keys sorted), so the sender can check what was stored row by row.
pub fn checksum(event: &serde_json::Value) -> String {
    hex::encode(Sha256::digest(serde_json::to_vec(event).unwrap_or_default()))
}

/// One checked item of a batch, ready for the node to seal and store.
#[derive(Debug, Clone, PartialEq)]
pub struct BatchItem {
    pub key: String,
    pub path: String,
    pub doc_id: String,
    pub checksum: String,
    pub event: serde_json::Value,
}

/// Check a whole `write_private_batch` call before anything is stored. Every item needs a path the signed-in
/// owner owns, an event with `kind` and `ts` (at most 64 KB) and an idempotency key unique in the batch.
/// Any bad item rejects the whole batch with every reason listed, so an import never half-lands silently.
pub fn plan_batch(login: &str, args: &serde_json::Value) -> Result<(Vec<BatchItem>, String), Vec<String>> {
    plan_batch_via(login, args, "claude-connector")
}

/// Same checks as `plan_batch`, stamping `via` with the route the batch came in on (the connector, or Studio's
/// spreadsheet import page, M1 d), so a row's history says how it arrived.
pub fn plan_batch_via(login: &str, args: &serde_json::Value, via: &str) -> Result<(Vec<BatchItem>, String), Vec<String>> {
    let items = match args.get("items").and_then(serde_json::Value::as_array) {
        Some(a) if !a.is_empty() && a.len() <= MAX_BATCH => a,
        _ => return Err(vec![format!("items: 1 to {MAX_BATCH} entries of {{path, event, key}}")]),
    };
    let (mut out, mut errs, mut seen) = (vec![], vec![], std::collections::HashSet::new());
    for (i, it) in items.iter().enumerate() {
        let path = it.get("path").and_then(serde_json::Value::as_str).unwrap_or("");
        let key = it.get("key").and_then(serde_json::Value::as_str).unwrap_or("");
        let ev = it.get("event").cloned().unwrap_or(serde_json::Value::Null);
        let size = serde_json::to_vec(&ev).map(|v| v.len()).unwrap_or(usize::MAX);
        if !path_owned_by(path, login) { errs.push(format!("items[{i}]: path isn't yours")); continue; }
        if key.is_empty() || key.len() > 200 { errs.push(format!("items[{i}]: key is required (1-200 characters)")); continue; }
        if !seen.insert((path.to_string(), key.to_string())) { errs.push(format!("items[{i}]: key {key} repeats in this batch")); continue; }
        if ev.get("kind").and_then(serde_json::Value::as_str).is_none() || ev.get("ts").and_then(serde_json::Value::as_str).is_none() {
            errs.push(format!("items[{i}]: event needs kind and ts")); continue;
        }
        if size > MAX_EVENT_BYTES { errs.push(format!("items[{i}]: event too large (64 KB max)")); continue; }
        let mut ev = ev;
        if let Some(o) = ev.as_object_mut() { o.insert("via".into(), via.into()); }
        out.push(BatchItem { key: key.into(), path: path.into(), doc_id: doc_id_for(login, path, key), checksum: checksum(&ev), event: ev });
    }
    if !errs.is_empty() { return Err(errs); }
    let whole = hex::encode(Sha256::digest(out.iter().map(|b| b.checksum.as_str()).collect::<Vec<_>>().join("\n").as_bytes()));
    Ok((out, whole))
}

#[cfg(test)]
mod tests {
    use super::*;

    const S: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    const N: [u8; 12] = [7; 12];
    const D: [u8; 32] = [3; 32];
    const P: &str = "data/users/Morami49/vault/events";

    #[test]
    fn round_trip() {
        let b = seal(&D, &N, "Morami49", 1, P, "w1", br#"{"kind":"item.create"}"#);
        assert_eq!(open(&D, "morami49", 1, P, "w1", &b).unwrap(), br#"{"kind":"item.create"}"#);
    }

    #[test]
    fn ciphertext_hides_the_content() {
        let b = seal(&D, &N, "a", 1, "data/users/a/v", "w1", b"my secret plans");
        assert!(!b.contains(&hex::encode(b"secret")));
    }

    #[test]
    fn another_owner_or_version_cannot_open_it() {
        let b = seal(&D, &N, "alice", 1, "data/users/alice/v", "w1", b"x");
        assert!(open(&D, "bob", 1, "data/users/alice/v", "w1", &b).is_none(), "owner is bound in");
        assert!(open(&D, "alice", 2, "data/users/alice/v", "w1", &b).is_none(), "key version is bound in");
        assert!(open(&[4; 32], "alice", 1, "data/users/alice/v", "w1", &b).is_none(), "another data key");
    }

    #[test]
    fn moving_a_row_to_another_path_or_id_fails() {
        let b = seal(&D, &N, "a", 1, "data/users/a/vault/events", "w1", b"x");
        assert!(open(&D, "a", 1, "data/users/a/other", "w1", &b).is_none());
        assert!(open(&D, "a", 1, "data/users/a/vault/events", "w2", &b).is_none());
    }

    #[test]
    fn tampering_is_detected() {
        let mut b = seal(&D, &N, "a", 1, "data/users/a/v", "w1", b"hello").into_bytes();
        let last = b.len() - 1;
        b[last] = if b[last] == b'0' { b'1' } else { b'0' };
        assert!(open(&D, "a", 1, "data/users/a/v", "w1", std::str::from_utf8(&b).unwrap()).is_none());
        assert!(open(&D, "a", 1, "data/users/a/v", "w1", "zz").is_none());
        assert!(open(&D, "a", 1, "data/users/a/v", "w1", "00").is_none());
    }

    #[test]
    fn data_keys_unwrap_only_with_the_right_secret_and_owner() {
        let w = wrap_dek(&kek(S), &N, "Morami49", 1, &D);
        assert_eq!(unwrap_dek(&kek(S), "morami49", 1, &w), Some(D));
        assert_eq!(unwrap_dek(&kek("other-secret"), "morami49", 1, &w), None);
        assert_eq!(unwrap_dek(&kek(S), "bob", 1, &w), None);
        assert_eq!(unwrap_dek(&kek(S), "morami49", 2, &w), None);
        assert!(!w.contains(&hex::encode(D)), "the data key is never stored in the clear");
    }

    #[test]
    fn rotating_the_hub_secret_rewraps_keys_and_keeps_every_row_readable() {
        let (old, new) = (kek(S), kek("a-new-secret"));
        let wrapped_old = wrap_dek(&old, &N, "a", 1, &D);
        let row = seal(&D, &[9; 12], "a", 1, "data/users/a/v", "w1", b"kept");
        // the node: current secret fails, previous works, so re-wrap with the current one
        assert!(unwrap_dek(&new, "a", 1, &wrapped_old).is_none());
        let dek = unwrap_dek(&old, "a", 1, &wrapped_old).unwrap();
        let wrapped_new = wrap_dek(&new, &[5; 12], "a", 1, &dek);
        let dek2 = unwrap_dek(&new, "a", 1, &wrapped_new).unwrap();
        assert_eq!(open(&dek2, "a", 1, "data/users/a/v", "w1", &row).unwrap(), b"kept");
    }

    #[test]
    fn paths_must_belong_to_the_owner() {
        assert!(path_owned_by("data/users/Morami49/vault/events", "morami49"));
        assert!(path_owned_by("data/users/a/x", "a"));
        assert!(path_owned_by("data/users/github:Morami49/vault/events", "Morami49"));
        assert!(!path_owned_by("data/users/github:b/x", "a"));
        assert!(!path_owned_by("data/users/gitlab:a/x", "a"));
        assert!(!path_owned_by("data/users/b/x", "a"));
        assert!(!path_owned_by("data/users/a", "a"));
        assert!(!path_owned_by("data/users/a/", "a"));
        assert!(!path_owned_by("data/users/a/../b/x", "a"));
        assert!(!path_owned_by("data/users/a//x", "a"));
        assert!(!path_owned_by("events", "a"));
        assert!(!path_owned_by("data/users/a/x y", "a"));
        assert!(!path_owned_by(&format!("data/users/a/{}", "x".repeat(121)), "a"));
    }

    #[test]
    fn a_batch_is_checked_whole_before_anything_is_stored() {
        use serde_json::json;
        let p = "data/users/github:Morami49/career/roles";
        let ev = |n: u32| json!({"kind": "rrs.row", "ts": "2026-11-17T20:00:00.000Z", "body": {"row": n}});
        let ok = json!({"items": [{"path": p, "key": "Roles/2", "event": ev(2)}, {"path": p, "key": "Roles/3", "event": ev(3)}]});
        let (items, whole) = plan_batch("Morami49", &ok).unwrap();
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].doc_id, doc_id_for("morami49", p, "Roles/2"), "same id as a single keyed write, case-insensitive login");
        assert_eq!(items[0].event["via"], "claude-connector");
        assert_eq!(whole.len(), 64);
        let (again, whole2) = plan_batch("Morami49", &ok).unwrap();
        assert_eq!((again, whole2), (items, whole), "re-running an import plans the same ids and checksums");
        let bad = json!({"items": [{"path": p, "key": "a", "event": ev(1)}, {"path": "data/users/someone/x", "key": "b", "event": ev(2)},
                                   {"path": p, "key": "a", "event": ev(3)}, {"path": p, "key": "", "event": ev(4)}, {"path": p, "key": "c", "event": json!({"kind": "x"})}]});
        let errs = plan_batch("Morami49", &bad).unwrap_err();
        assert_eq!(errs.len(), 4, "{errs:?}");
        assert!(plan_batch("Morami49", &json!({"items": []})).is_err());
        let (studio, _) = plan_batch_via("Morami49", &ok, "studio-import").unwrap();
        assert_eq!(studio[0].event["via"], "studio-import");
        assert_eq!(studio[0].doc_id, doc_id_for("morami49", p, "Roles/2"), "the route does not change which item a row is");
        let many: Vec<_> = (0..=MAX_BATCH).map(|i| json!({"path": p, "key": format!("k{i}"), "event": ev(i as u32)})).collect();
        assert!(plan_batch("Morami49", &json!({"items": many})).is_err());
    }
}
