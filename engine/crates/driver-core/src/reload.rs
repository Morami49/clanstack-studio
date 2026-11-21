//! Reload decisions as pure functions (the Desktop shell's watcher, actionmap/desktop/shell/shell_mcp.py on
//! branch b-desktop-shell: `app_signature`, `watch`, `reload`, `_restart_loop`, `backoff_steps`).
//!
//! The caller reads the disk (VERSION text and every file's size and mtime) and keeps the clock; these
//! functions only say what to do:
//! - a change is acted on once two polls in a row see the same new signature (the files stopped changing);
//! - while `_next/.swapping` (the swap lock) exists nothing is decided;
//! - a reload request from the Desktop window reloads at once;
//! - a reload drains first when calls are in flight (they finish, up to drain_s), else restarts at once;
//! - a crashed worker restarts after 1, 2, 5, 10, 30, 60, 60, ... seconds; the step resets after a successful
//!   reload or when the worker had run for more than 60 s.

use serde::{Deserialize, Serialize};

pub const DEFAULT_BACKOFF: &[f64] = &[1.0, 2.0, 5.0, 10.0, 30.0, 60.0];
/// Folders under app/ a reload never looks at.
pub const SKIP_DIRS: &[&str] = &["_next", "_prev", "_rollback", "_old", "__pycache__", ".git"];
pub const SWAP_LOCK: &str = ".swapping";
/// A worker that ran longer than this before it stopped starts the backoff again from the first step.
pub const BACKOFF_RESET_AFTER_S: f64 = 60.0;
pub const DRAIN_S: f64 = 150.0;

#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct FileStamp {
    /// Relative to app/, '/' separated.
    pub path: String,
    pub size: u64,
    pub mtime_ns: i128,
}

/// What a reload depends on: VERSION's text and every file's (path, size, mtime) under app/.
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct Signature {
    pub version: String,
    pub files: Vec<FileStamp>,
}

impl Signature {
    /// Builds a signature from what the caller found on disk, skipping what `app_signature` skips.
    pub fn new(version: &str, files: impl IntoIterator<Item = FileStamp>) -> Signature {
        let mut files: Vec<FileStamp> = files.into_iter().filter(|f| counts(&f.path)).collect();
        files.sort();
        Signature { version: version.to_string(), files }
    }
}

/// Is this file (relative path) part of the signature? Not under a skipped folder, not .pyc/.tmp, not the lock.
pub fn counts(rel_path: &str) -> bool {
    let parts: Vec<&str> = rel_path.split('/').collect();
    let (dirs, name) = parts.split_at(parts.len() - 1);
    let name = name[0];
    !dirs.iter().any(|d| SKIP_DIRS.contains(d)) && !name.ends_with(".pyc") && !name.ends_with(".tmp") && name != SWAP_LOCK
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum WorkerState {
    Stopped,
    Starting,
    Ready,
    Draining,
    Down,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "do", rename_all = "lowercase")]
pub enum ReloadAction {
    None,
    /// Hold new calls, let the ones in flight finish (up to DRAIN_S), then restart the worker.
    Drain { reason: String },
    /// Nothing in flight: restart the worker now.
    Restart { reason: String },
}

/// The watcher's memory between polls.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct WatchState {
    /// The signature last loaded into the worker.
    pub loaded: Signature,
    /// A new signature seen once, waiting to be seen again unchanged.
    pub pending: Option<Signature>,
    pub stable: u32,
}

/// One poll of the disk.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Poll {
    pub current: Signature,
    pub swap_lock: bool,
    /// The Desktop window's reload-request file changed since the last poll.
    pub reload_requested: bool,
    pub worker: WorkerState,
    pub in_flight: usize,
}

fn reload(reason: String, in_flight: usize) -> ReloadAction {
    if in_flight > 0 {
        ReloadAction::Drain { reason }
    } else {
        ReloadAction::Restart { reason }
    }
}

/// shell_mcp `watch()` loop body: (new state, what to do).
pub fn watch_step(st: &WatchState, p: &Poll) -> (WatchState, ReloadAction) {
    let mut s = st.clone();
    if p.swap_lock {
        s.stable = 0;
        return (s, ReloadAction::None);
    }
    if p.reload_requested {
        s.loaded = p.current.clone();
        return (s, reload("asked from the Desktop window".into(), p.in_flight));
    }
    if p.current == s.loaded {
        s.pending = None;
        s.stable = 0;
        return (s, ReloadAction::None);
    }
    if s.pending.as_ref() != Some(&p.current) {
        s.pending = Some(p.current.clone());
        s.stable = 0;
        return (s, ReloadAction::None);
    }
    s.stable += 1;
    let old_v = s.loaded.version.clone();
    let new_v = p.current.version.clone();
    let changed = sym_diff(&s.loaded.files, &p.current.files);
    s.loaded = p.current.clone();
    s.pending = None;
    s.stable = 0;
    let why = if old_v != new_v { format!("VERSION {old_v} -> {new_v}") } else { format!("{changed} file change(s) under app") };
    if p.worker == WorkerState::Stopped {
        return (s, ReloadAction::None);
    }
    (s, reload(why, p.in_flight))
}

fn sym_diff(a: &[FileStamp], b: &[FileStamp]) -> usize {
    use std::collections::BTreeSet;
    let a: BTreeSet<&FileStamp> = a.iter().collect();
    let b: BTreeSet<&FileStamp> = b.iter().collect();
    a.symmetric_difference(&b).count()
}

/// `backoff_steps()`: NODACH_DESKTOP_BACKOFF ("1,2,5") or the default; anything unparsable -> default.
pub fn backoff_steps(raw: Option<&str>) -> Vec<f64> {
    match raw {
        Some(r) if !r.is_empty() => {
            let parsed: Result<Vec<f64>, _> = r.split(',').map(|x| crate::py::strip(x).parse::<f64>()).collect();
            match parsed {
                Ok(v) => v,
                Err(_) => DEFAULT_BACKOFF.to_vec(),
            }
        }
        _ => DEFAULT_BACKOFF.to_vec(),
    }
}

/// `_restart_loop`: the wait before the next try at step `i`, and the next step.
pub fn next_backoff(i: usize, steps: &[f64]) -> (f64, usize) {
    let steps = if steps.is_empty() { DEFAULT_BACKOFF } else { steps };
    (steps[i.min(steps.len() - 1)], i + 1)
}

/// The worker stopped after running `ran_s` seconds: the backoff step to continue from.
pub fn after_worker_exit(ran_s: f64, i: usize) -> usize {
    if ran_s > BACKOFF_RESET_AFTER_S {
        0
    } else {
        i
    }
}

/// After a reload: success starts the backoff over; failure leaves the worker down and schedules a restart.
pub fn after_reload(ok: bool, i: usize) -> (usize, WorkerState) {
    if ok {
        (0, WorkerState::Ready)
    } else {
        (i, WorkerState::Down)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sig(v: &str, files: &[(&str, u64, i128)]) -> Signature {
        Signature::new(v, files.iter().map(|(p, s, m)| FileStamp { path: p.to_string(), size: *s, mtime_ns: *m }))
    }

    fn poll(current: Signature, in_flight: usize) -> Poll {
        Poll { current, swap_lock: false, reload_requested: false, worker: WorkerState::Ready, in_flight }
    }

    #[test]
    fn a_change_waits_until_the_files_stop_changing() {
        let a = sig("0.1.0", &[("gate/gate_core.py", 10, 1)]);
        let b = sig("0.1.1", &[("gate/gate_core.py", 12, 2)]);
        let st = WatchState { loaded: a.clone(), ..Default::default() };
        let (st, act) = watch_step(&st, &poll(a.clone(), 0));
        assert_eq!(act, ReloadAction::None);
        let (st, act) = watch_step(&st, &poll(b.clone(), 0));
        assert_eq!(act, ReloadAction::None, "first sight: still being written");
        let (st, act) = watch_step(&st, &poll(b.clone(), 2));
        assert_eq!(act, ReloadAction::Drain { reason: "VERSION 0.1.0 -> 0.1.1".into() });
        assert_eq!(st.loaded, b);
        let (_, act) = watch_step(&st, &poll(b, 0));
        assert_eq!(act, ReloadAction::None);
    }

    #[test]
    fn file_changes_without_version_restart_when_idle() {
        let a = sig("1", &[("x.py", 1, 1), ("y.py", 1, 1)]);
        let b = sig("1", &[("x.py", 2, 2), ("y.py", 1, 1), ("z.py", 1, 1)]);
        let st = WatchState { loaded: a, ..Default::default() };
        let (st, _) = watch_step(&st, &poll(b.clone(), 0));
        let (_, act) = watch_step(&st, &poll(b, 0));
        assert_eq!(act, ReloadAction::Restart { reason: "3 file change(s) under app".into() });
    }

    #[test]
    fn swap_lock_request_and_stopped_worker() {
        let a = sig("1", &[]);
        let b = sig("2", &[]);
        let st = WatchState { loaded: a.clone(), pending: Some(b.clone()), stable: 0 };
        let mut p = poll(b.clone(), 0);
        p.swap_lock = true;
        assert_eq!(watch_step(&st, &p).1, ReloadAction::None);
        p.swap_lock = false;
        p.worker = WorkerState::Stopped;
        let (st2, act) = watch_step(&st, &p);
        assert_eq!(act, ReloadAction::None);
        assert_eq!(st2.loaded, b, "signature taken even while stopped");
        let mut p = poll(a, 1);
        p.reload_requested = true;
        assert_eq!(watch_step(&st, &p).1, ReloadAction::Drain { reason: "asked from the Desktop window".into() });
    }

    #[test]
    fn skipped_files() {
        let s = sig("1", &[("_next/a.py", 1, 1), ("a.pyc", 1, 1), ("b/__pycache__/c.py", 1, 1), (".swapping", 0, 0), ("ok.py", 1, 1)]);
        assert_eq!(s.files.len(), 1);
    }

    #[test]
    fn backoff_schedule() {
        let steps = backoff_steps(None);
        let mut i = 0;
        let mut waits = vec![];
        for _ in 0..8 {
            let (w, n) = next_backoff(i, &steps);
            waits.push(w);
            i = n;
        }
        assert_eq!(waits, [1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 60.0, 60.0]);
        assert_eq!(after_worker_exit(61.0, 7), 0);
        assert_eq!(after_worker_exit(5.0, 7), 7);
        assert_eq!(after_reload(true, 4), (0, WorkerState::Ready));
        assert_eq!(backoff_steps(Some("0.1, 0.2")), [0.1, 0.2]);
        assert_eq!(backoff_steps(Some("x")), DEFAULT_BACKOFF);
    }
}
