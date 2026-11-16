//! The Private tier (D-nodach-identity, Q53 A, build piece I1).
//!
//! Private items live on the hub, encrypted at rest, so they survive a new browser or device. They are
//! never part of the signed shared record: they are stored apart, served only to their owner (and to
//! grantees such as the Claude connector), and never appear in `read_events` or `/studio/api/events`.
//!
//! Pure logic: no clock, no randomness, no network. The node supplies the hub secret and a fresh nonce.
//!
//! - Each owner gets their own key: SHA-256 over a fixed label, the hub secret and the lower-cased login.
//! - Each row is AES-256-GCM sealed. The owner, the path and the doc id are bound in as associated data,
//!   so a sealed row copied to another owner, path or id fails to open instead of leaking.
//! - The Sealed tier (passphrase only the owner knows, I4) is a layer on top: the browser encrypts first,
//!   and the hub stores the result here like any other private row, without being able to read it.
//!
//! Losing the hub secret makes every private row unreadable, so the node never rotates it on its own,
//! and the owner can export a decrypted copy at any time (`/studio/api/private/export`).

use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Nonce};
use sha2::{Digest, Sha256};

pub const NONCE_LEN: usize = 12;
/// Largest private event a browser may send (bytes of JSON). Files have their own encrypted path.
pub const MAX_EVENT_BYTES: usize = 64 * 1024;

pub fn owner_key(secret: &str, owner: &str) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"nodach-private-v1\0");
    h.update(secret.trim().as_bytes());
    h.update(b"\0");
    h.update(owner.to_ascii_lowercase().as_bytes());
    h.finalize().into()
}

fn aad(owner: &str, path: &str, doc_id: &str) -> Vec<u8> {
    format!("{}\0{}\0{}", owner.to_ascii_lowercase(), path, doc_id).into_bytes()
}

/// Seal one private row. Returns hex(nonce || ciphertext+tag).
pub fn seal(key: &[u8; 32], nonce: &[u8; NONCE_LEN], owner: &str, path: &str, doc_id: &str, plaintext: &[u8]) -> String {
    let c = Aes256Gcm::new_from_slice(key).expect("32-byte key");
    let ct = c.encrypt(Nonce::from_slice(nonce), Payload { msg: plaintext, aad: &aad(owner, path, doc_id) })
        .expect("AES-GCM encryption cannot fail for in-memory buffers");
    let mut out = nonce.to_vec();
    out.extend(ct);
    hex::encode(out)
}

/// Open a sealed row. None if it was tampered with, or belongs to another owner, path or doc id.
pub fn open(key: &[u8; 32], owner: &str, path: &str, doc_id: &str, blob_hex: &str) -> Option<Vec<u8>> {
    let raw = hex::decode(blob_hex).ok()?;
    if raw.len() < NONCE_LEN + 16 { return None; }
    let (n, ct) = raw.split_at(NONCE_LEN);
    let c = Aes256Gcm::new_from_slice(key).ok()?;
    c.decrypt(Nonce::from_slice(n), Payload { msg: ct, aad: &aad(owner, path, doc_id) }).ok()
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

#[cfg(test)]
mod tests {
    use super::*;

    const S: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
    const N: [u8; 12] = [7; 12];

    #[test]
    fn round_trip() {
        let k = owner_key(S, "Morami49");
        let b = seal(&k, &N, "Morami49", "data/users/Morami49/vault/events", "w1", br#"{"kind":"item.create"}"#);
        assert_eq!(open(&k, "morami49", "data/users/Morami49/vault/events", "w1", &b).unwrap(), br#"{"kind":"item.create"}"#);
    }

    #[test]
    fn ciphertext_hides_the_content() {
        let k = owner_key(S, "a");
        let b = seal(&k, &N, "a", "data/users/a/vault/events", "w1", b"my secret plans");
        assert!(!b.contains(&hex::encode(b"secret")));
    }

    #[test]
    fn another_owner_cannot_open_it() {
        let b = seal(&owner_key(S, "alice"), &N, "alice", "data/users/alice/v", "w1", b"x");
        assert!(open(&owner_key(S, "bob"), "bob", "data/users/alice/v", "w1", &b).is_none());
        // even with alice's key, claiming the row for bob fails, because the owner is bound in
        assert!(open(&owner_key(S, "alice"), "bob", "data/users/alice/v", "w1", &b).is_none());
    }

    #[test]
    fn moving_a_row_to_another_path_or_id_fails() {
        let k = owner_key(S, "a");
        let b = seal(&k, &N, "a", "data/users/a/vault/events", "w1", b"x");
        assert!(open(&k, "a", "data/users/a/other", "w1", &b).is_none());
        assert!(open(&k, "a", "data/users/a/vault/events", "w2", &b).is_none());
    }

    #[test]
    fn tampering_is_detected() {
        let k = owner_key(S, "a");
        let mut b = seal(&k, &N, "a", "data/users/a/v", "w1", b"hello").into_bytes();
        let last = b.len() - 1;
        b[last] = if b[last] == b'0' { b'1' } else { b'0' };
        assert!(open(&k, "a", "data/users/a/v", "w1", std::str::from_utf8(&b).unwrap()).is_none());
        assert!(open(&k, "a", "data/users/a/v", "w1", "zz").is_none());
        assert!(open(&k, "a", "data/users/a/v", "w1", "00").is_none());
    }

    #[test]
    fn a_different_hub_secret_cannot_open_it() {
        let b = seal(&owner_key(S, "a"), &N, "a", "data/users/a/v", "w1", b"x");
        assert!(open(&owner_key("other-secret", "a"), "a", "data/users/a/v", "w1", &b).is_none());
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
}
