//! gate_core `redact_snapshot`: cut every never-zone window out of Windows-MCP Snapshot text.
//!
//! 1. In the UI tree, a `window "<title>"` line whose title is never-zone keeps one line (title replaced,
//!    "(contents hidden: <group>)" added) and its deeper lines are dropped (an empty line ends the skip).
//! 2. Those titles are replaced everywhere else (longest first).
//! 3. Before "UI Tree:", any line naming a never-zone window becomes the hidden marker.
//! 4. Groups with `redact_elements`: any line naming one of their title words has every quoted value hidden,
//!    in every window.
//!
//! Python quirks kept on purpose (Rust must give identical text): lines are split with `str.splitlines()` and
//! joined with "\n" (so \r\n becomes \n and a final newline is dropped), and step 3 drops the line break just
//! before "UI Tree:".

use crate::decide::never_reason;
use crate::py;
use crate::words::WordSet;
use crate::zones::Zones;

pub const HIDDEN: &str = "[hidden by Nodach Gate]";

/// `_TREE_RE`: (depth = number of leading '│'/' ' chars, rest stripped).
fn tree_line(line: &str) -> (usize, &str) {
    let mut depth = 0;
    let mut idx = 0;
    for (i, c) in line.char_indices() {
        if c == '│' || c == ' ' {
            depth += 1;
            idx = i + c.len_utf8();
        } else {
            idx = i;
            break;
        }
    }
    if depth == line.chars().count() {
        idx = line.len();
    }
    let mut rest = &line[idx..];
    // optional "├── " / "└── " (any one whitespace char after the dashes)
    let mut it = rest.chars();
    if let (Some(a), Some('─'), Some('─'), Some(w)) = (it.next(), it.next(), it.next(), it.next()) {
        if (a == '├' || a == '└') && py::is_space(w) {
            let skip = a.len_utf8() + 2 * '─'.len_utf8() + w.len_utf8();
            rest = &rest[skip..];
        }
    }
    (depth, py::strip(rest))
}

/// `_WIN_RE`: `window "<title>"` (title is everything up to the last quote).
fn window_title(rest: &str) -> Option<&str> {
    let body = rest.strip_prefix("window \"")?;
    body.strip_suffix('"')
}

/// `re.sub(r'"[^"]*"', '"' + HIDDEN + '"', line)`.
fn hide_quoted(line: &str) -> String {
    let mut out = String::with_capacity(line.len());
    let mut rest = line;
    while let Some(a) = rest.find('"') {
        match rest[a + 1..].find('"') {
            Some(b) => {
                out.push_str(&rest[..a]);
                out.push('"');
                out.push_str(HIDDEN);
                out.push('"');
                rest = &rest[a + 1 + b + 1..];
            }
            None => break,
        }
    }
    out.push_str(rest);
    out
}

/// Returns (text, number of distinct never-zone windows hidden).
pub fn redact_snapshot(text: &str, zones: &Zones) -> (String, usize) {
    let never = |s: &str| never_reason(&zones.never, "", s, "", &[], false);
    let mut out: Vec<String> = Vec::new();
    let mut skip_depth: Option<usize> = None;
    let mut titles: Vec<String> = Vec::new();
    for line in py::splitlines(text) {
        let (depth, rest) = tree_line(line);
        if let Some(sd) = skip_depth {
            if depth > sd && !rest.is_empty() {
                continue;
            }
            skip_depth = None;
        }
        if let Some(title) = window_title(rest) {
            if let Some(r) = never(title) {
                if !titles.iter().any(|t| t == title) {
                    titles.push(title.to_string());
                }
                let group = r.split(':').next().unwrap_or("");
                out.push(format!("{}  (contents hidden: {group})", line.replace(title, HIDDEN)));
                skip_depth = Some(depth);
                continue;
            }
        }
        out.push(line.to_string());
    }
    let mut t = out.join("\n");
    // Python: sorted(set, key=len, reverse=True); equal lengths are put in text order here.
    let mut sorted = titles.clone();
    sorted.sort_by(|a, b| py::char_len(b).cmp(&py::char_len(a)));
    for title in &sorted {
        if !title.is_empty() {
            t = t.replace(title.as_str(), HIDDEN);
        }
    }
    let (head, sep, tail) = match t.find("UI Tree:") {
        Some(i) => (&t[..i], "UI Tree:", &t[i + "UI Tree:".len()..]),
        None => (t.as_str(), "", ""),
    };
    let head: Vec<&str> = py::splitlines(head).into_iter().map(|ln| if never(ln).is_some() { HIDDEN } else { ln }).collect();
    let mut t = format!("{}{}{}", head.join("\n"), sep, tail);
    let words: Vec<&String> =
        zones.never.iter().filter(|g| g.redacts_elements()).flat_map(|g| g.title_words.iter()).collect();
    if let Some(rx) = WordSet::new(&words) {
        t = py::splitlines(&t)
            .into_iter()
            .map(|ln| if rx.search(ln).is_some() { hide_quoted(ln) } else { ln.to_string() })
            .collect::<Vec<_>>()
            .join("\n");
    }
    (t, titles.len())
}
