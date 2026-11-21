//! driver-core (63c b): the Nodach Driver's rules in Rust, so a Tauri app can replace the Python Gate later.
//!
//! The Python Gate (actionmap/gate/gate_core.py) is the one running on the PC for now. This crate must give
//! identical answers: `tests/parity.rs` replays every vector `actionmap/gate/tests/export_vectors.py` wrote
//! from Python, and CI fails when Python's output differs from the committed vectors.
//!
//! - `zones`  : zones.json (gate.zones.v1) with serde; parse/load with defaults; `upgrade_zones`.
//! - `decide` : (Zone, reason) for one request: hidden tools, Gate's own windows, App launch rules,
//!              key combos, Enter after typing, password fields, shell and confirm apps.
//! - `redact` : never-zone windows and secret-named elements cut out of Snapshot text.
//! - `log`    : the gate.v1 action record, `mask_text`, `looks_secret`, `clean_args`, `iso`.
//! - `reload` : drain / restart / none from VERSION and file stamps, and the 1-2-5-10-30-60 s backoff.
//! - `words`, `py`: whole-word matching and the Python string semantics the rules depend on.
//!
//! No I/O, no clock, no network: every input is an argument.
//!
//! # Known differences from Python (none reachable with a valid zones.json and Gate's own contexts)
//! - Where Python raises, Rust still answers: `Click clicks="2.5"` (Python `int()` raises ValueError) is
//!   treated as not a hover and the remaining rules run. Such cases are left out of the vectors.
//! - A zones.json with wrong types (e.g. a number inside a word list) is refused when loaded (the caller keeps
//!   the last good rules); Python loads it and fails on first use.
//! - `"name": null` in a group gives the label "never" (Python prints "None"); `"gate_titles": null` means the
//!   default ["Nodach Gate"] (Python: no titles).
//! - Two different never-zone window titles of equal length are replaced in text order; Python's order comes
//!   from a set and changes with PYTHONHASHSEED (so Python itself is not deterministic there).
//! - `upgrade_zones` returns the same content, but keys come out sorted (serde_json map) instead of in file order.
//! - `str()` of a list or dict argument (only ever logged) follows Python's repr for plain strings only.
//! - `reload` mirrors actionmap/desktop/shell/shell_mcp.py (branch b-desktop-shell, not in this tree), so it is
//!   covered by unit tests rather than vectors; "drain" vs "restart" makes explicit what Python does implicitly
//!   (its drain is a no-op when nothing is in flight).

pub mod decide;
pub mod log;
pub mod py;
pub mod redact;
pub mod reload;
pub mod words;
pub mod zones;

pub use decide::{decide, Action, Context, Zone};
pub use log::{log_entry, looks_secret, mask_text, ActionRecord};
pub use redact::redact_snapshot;
pub use zones::{load_zones, parse_zones, upgrade_zones, Zones};

/// The Python Gate version these rules mirror.
pub const GATE_VERSION: &str = "0.1.5";
