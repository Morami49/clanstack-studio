//! Signed, content-addressed events. One envelope for both layers:
//! - Fact   = something that happened. Never branched. Per-author hash chain.
//! - Intent = a decision / setting / plan / note. Lives on a branch of the tree (a DAG).

use ed25519_dalek::{Signature, Signer as _, SigningKey, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub type Id = String; // hex blake3 of the unsigned event
pub type PubKey = String; // hex ed25519 public key

#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case")]
pub enum Layer {
    Fact,
    Intent,
}

/// Real facts happened once. Rehearsal facts were simulated on one branch only (story S4).
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq, Hash)]
#[serde(rename_all = "snake_case", tag = "t", content = "branch")]
pub enum Realm {
    Real,
    Rehearsal(Id),
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct Unsigned {
    pub v: u8,
    pub layer: Layer,
    pub realm: Realm,
    /// Key that signed this event (an identity, sub-identity or device).
    pub author: PubKey,
    /// Milliseconds since epoch, supplied by the caller (WASM has no clock of its own).
    pub ts: i64,
    /// Greater than every parent's lamport: a causal clock that orders the DAG.
    pub lamport: u64,
    /// Facts: position in the author's own chain (1..n). Intents: 0.
    pub seq: u64,
    /// Facts: [author's previous fact] + any causes. Intents: the branch heads it builds on.
    pub parents: Vec<Id>,
    /// Intents: the branch they belong to. Facts: the lane's branch they were recorded in (context only).
    pub branch: Option<Id>,
    pub kind: String,
    pub body: Value,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct Event {
    #[serde(flatten)]
    pub u: Unsigned,
    pub id: Id,
    pub sig: String,
}

pub fn content_id(u: &Unsigned) -> Id {
    // serde_json::Value objects are BTreeMaps, so keys come out sorted: a canonical form.
    let canon = serde_json::to_vec(&serde_json::to_value(u).expect("serialisable")).expect("json");
    blake3::hash(&canon).to_hex().to_string()
}

pub struct KeyPair {
    key: SigningKey,
    pub public: PubKey,
}

impl KeyPair {
    /// Keys are made from 32 caller-supplied random bytes (crypto.getRandomValues in the browser,
    /// the OS RNG natively), so the core needs no randomness of its own.
    pub fn from_seed(seed: [u8; 32]) -> Self {
        let key = SigningKey::from_bytes(&seed);
        let public = hex::encode(key.verifying_key().to_bytes());
        KeyPair { key, public }
    }
    /// Secret seed (for a device's own encrypted keystore only; never put it in an event).
    pub fn seed(&self) -> [u8; 32] {
        self.key.to_bytes()
    }
    pub fn seal(&self, u: Unsigned) -> Event {
        let id = content_id(&u);
        let sig = hex::encode(self.key.sign(id.as_bytes()).to_bytes());
        Event { u, id, sig }
    }
}

pub fn check_signature(ev: &Event) -> Result<(), String> {
    if content_id(&ev.u) != ev.id {
        return Err("id does not match content".into());
    }
    let pk: [u8; 32] = hex::decode(&ev.u.author)
        .map_err(|_| "bad author hex")?
        .try_into()
        .map_err(|_| "bad author length")?;
    let vk = VerifyingKey::from_bytes(&pk).map_err(|_| "bad author key")?;
    let sig: [u8; 64] = hex::decode(&ev.sig)
        .map_err(|_| "bad sig hex")?
        .try_into()
        .map_err(|_| "bad sig length")?;
    vk.verify(ev.id.as_bytes(), &Signature::from_bytes(&sig))
        .map_err(|_| "signature invalid".to_string())
}

pub fn short(id: &str) -> &str {
    &id[..id.len().min(8)]
}
