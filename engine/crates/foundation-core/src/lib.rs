//! foundation-core (working name — rename pending, see GLOSSARY.md)
//!
//! The substrate under ActionMap and whatever it builds next:
//! - a signed FACT ledger (what happened; never branched, per-author hash chains),
//! - a branching INTENT tree (what was decided/planned/configured; branch, resume, merge),
//! - key-based identities with sub-identities and devices (no blockchain needed),
//! - views of any branch at any point, and merges with per-type policies.
//! Pure Rust with no I/O, clock or randomness, so it compiles to native and to WASM.

pub mod event;
pub mod identity;
pub mod store;
pub mod view;

pub use event::{Event, Id, KeyPair, Layer, PubKey, Realm};
pub use store::{Reject, Store};
pub use view::{merge, merge_preview, tree, view, view_at, MergePlan, View};
