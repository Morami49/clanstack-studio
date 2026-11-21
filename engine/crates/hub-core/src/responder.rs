//! Live instant responder (51a, 20 Nov): which live lines get a quick AI answer, and what the model is sent.
//!
//! A session item (source "live") whose `live.responder` is true (item.create body.live, then item.edit body.live
//! in order, the latest wins) gets one short answer per eligible line, written by the hub as a comment. This module
//! is the pure part: gating, the per-session rate limit and the prompt. The worker calls the model and writes.
//!
//! Rules: at most one call per line (lines already considered are passed in `tried`, and a line that already has a
//! responder comment pointing at it is never considered again); at most MAX_PER_HOUR responder comments per session
//! per hour; a line under MIN_WORDS words is skipped unless it ends with '?'; only lines newer than FRESH_MS are
//! considered (turning the switch on never answers old lines). The prompt holds the text of the last CONTEXT lines
//! and comments of that session: never report comments, points, pointer screenshots or anything else.
use std::collections::{HashMap, HashSet};

use serde_json::Value;

pub const MAX_PER_HOUR: usize = 30;
pub const CONTEXT: usize = 12;
pub const MIN_WORDS: usize = 3;
pub const FRESH_MS: i64 = 10 * 60_000;
pub const AUTHOR_ID: &str = "agent:live-responder";
pub const LABEL: &str = "Live responder (Gemini)";
pub const VIA: &str = "live-responder";
pub const SYSTEM: &str = "You are the Nodach Live responder. Answer briefly. If the request needs code changes, repo access or decisions, say Claude will pick it up when Nowed next messages the chat, and tag it [for-claude].";

/// What to do with one fresh line of a session that has the responder on.
#[derive(Debug, Clone, PartialEq)]
pub enum Action {
    /// call the model with this prompt (the system note goes separately, as SYSTEM)
    Call { prompt: String },
    /// considered and not answered: "short" or "rate limit"
    Skip(&'static str),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Decision {
    pub session: String,
    /// the line's doc id (the responder comment carries it as body.line)
    pub line: String,
    pub action: Action,
}

/// Is this line worth an answer? Three words or more, or a question.
pub fn worth_answering(text: &str) -> bool {
    let t = text.trim();
    !t.is_empty() && (t.split_whitespace().count() >= MIN_WORDS || t.ends_with('?'))
}

/// Did the model hand this over to Claude?
pub fn for_claude(answer: &str) -> bool {
    answer.to_ascii_lowercase().contains("[for-claude]")
}

fn s<'a>(v: &'a Value, p: &str) -> &'a str {
    v.pointer(p).and_then(Value::as_str).unwrap_or("")
}

/// The record's sessions that have the responder switched on (session id → still live).
pub fn sessions_on(docs: &[Value]) -> HashMap<String, bool> {
    let mut cfg: HashMap<String, (bool, String)> = HashMap::new();   // id → (responder, status)
    for d in docs {
        let e = d.get("event").unwrap_or(&Value::Null);
        let b = e.get("body").unwrap_or(&Value::Null);
        match s(e, "/kind") {
            "item.create" if s(b, "/source") == "live" => {
                let id = s(b, "/id").to_string();
                if !id.is_empty() && !cfg.contains_key(&id) {   // the first create wins (F-19)
                    let on = b.pointer("/live/responder").and_then(Value::as_bool).unwrap_or(false);
                    cfg.insert(id, (on, s(b, "/status").to_string()));
                }
            }
            "item.edit" => if let Some(c) = cfg.get_mut(s(e, "/item")) {
                if let Some(on) = b.pointer("/live/responder").and_then(Value::as_bool) { c.0 = on; }
            },
            "status" => if let Some(c) = cfg.get_mut(s(e, "/item")) { c.1 = s(b, "/status").to_string(); },
            _ => {}
        }
    }
    cfg.into_iter().filter(|(_, (on, _))| *on).map(|(id, (_, st))| (id, st == "live")).collect()
}

/// One row of a session's stream, as the model may see it: who and the words, nothing else.
fn row(e: &Value) -> Option<String> {
    let b = e.get("body")?;
    let text = b.get("text").and_then(Value::as_str).unwrap_or("").trim();
    if text.is_empty() { return None; }
    let who = match s(e, "/kind") {
        "live.line" => { let sp = s(b, "/speaker"); if sp.is_empty() { "Speaker" } else { sp } }
        "comment" => {
            if b.get("report").and_then(Value::as_bool).unwrap_or(false) || b.get("step").is_some() { return None; }   // reports, show steps
            if b.get("responder").and_then(Value::as_bool).unwrap_or(false) { "Live responder" }
            else if s(e, "/via") == "claude-connector" || s(e, "/author/id") == "claude" { "Claude" }
            else { let l = s(e, "/author/label"); if l.is_empty() { "Someone" } else { l } }
        }
        _ => return None,
    };
    let text: String = text.chars().take(1500).collect();
    Some(format!("{who}: {text}"))
}

/// The lines to answer now. `tried`: line doc ids already considered (answered, skipped or failed); `now`: ms.
pub fn due(docs: &[Value], tried: &HashSet<String>, now: i64) -> Vec<Decision> {
    let on = sessions_on(docs);
    if on.is_empty() { return vec![]; }
    let fresh = crate::mcp::iso(now - FRESH_MS);
    let hour = crate::mcp::iso(now - 3_600_000);
    let mut gone: HashSet<&str> = HashSet::new();
    let mut answered: HashSet<&str> = HashSet::new();
    let mut recent: HashMap<&str, usize> = HashMap::new();   // responder comments in the last hour, per session
    for d in docs {
        let e = d.get("event").unwrap_or(&Value::Null);
        match s(e, "/kind") {
            "retract" => { gone.insert(s(e, "/body/of")); }
            "comment" if e.pointer("/body/responder").and_then(Value::as_bool).unwrap_or(false) => {
                answered.insert(s(e, "/body/line"));
                if s(e, "/ts") >= hour.as_str() { *recent.entry(s(e, "/item")).or_default() += 1; }
            }
            _ => {}
        }
    }
    let mut stream: HashMap<&str, Vec<(String, String)>> = HashMap::new();   // session → [(doc id, row)]
    let mut out = vec![];
    for d in docs {
        let e = d.get("event").unwrap_or(&Value::Null);
        let item = s(e, "/item");
        if !on.contains_key(item) { continue; }
        let doc = d.get("doc_id").and_then(Value::as_str).unwrap_or("");
        if gone.contains(doc) { continue; }
        let r = row(e);
        if let Some(r) = &r { stream.entry(item).or_default().push((doc.to_string(), r.clone())); }
        if s(e, "/kind") != "live.line" || !on[item] || doc.is_empty() || tried.contains(doc) || answered.contains(doc) { continue; }
        if s(e, "/ts") < fresh.as_str() { continue; }
        let text = s(e, "/body/text");
        let action = if !worth_answering(text) {
            Action::Skip("short")
        } else if recent.get(item).copied().unwrap_or(0) >= MAX_PER_HOUR {
            Action::Skip("rate limit")
        } else {
            *recent.entry(item).or_default() += 1;   // counts the answer about to be written
            let rows = stream.get(item).map(|v| v.as_slice()).unwrap_or(&[]);
            let tail: Vec<&str> = rows[rows.len().saturating_sub(CONTEXT)..].iter().map(|(_, r)| r.as_str()).collect();
            Action::Call { prompt: format!("Live session {item}. The latest lines and replies, oldest first:\n{}\n\nAnswer the last line.", tail.join("\n")) }
        };
        out.push(Decision { session: item.to_string(), line: doc.to_string(), action });
    }
    out
}

/// The comment the hub writes with the model's answer.
pub fn answer_body(text: &str, model: &str, line: &str) -> Value {
    let text: String = text.trim().chars().take(4000).collect();
    serde_json::json!({"text": text, "responder": true, "model": model, "for_claude": for_claude(&text), "line": line})
}

/// Would a write of this event need a responder pass? (A cheap check before waking the worker.)
pub fn wakes(ev: &Value) -> bool {
    s(ev, "/kind") == "live.line"
}

/// How soon a live line wakes the responder. workers-rs `set_alarm(i64)` reads the number as an OFFSET from now,
/// not an epoch time (F-responder-alarm, 21 Nov: `now + 200` scheduled the wake ~56 years ahead and pushed the
/// hourly schedule with it). Always pass an offset from these helpers, never an absolute time.
pub const WAKE_OFFSET_MS: i64 = 200;

/// Offset to a minute past the next hour: the hub's hourly wake-up.
pub fn next_hour_offset(now: i64) -> i64 {
    3_600_000 - now.rem_euclid(3_600_000) + 60_000
}

/// True when the stored alarm must be (re)set: none, or further away than any alarm the hub ever sets
/// (the hourly one is at most 61 minutes out). Repairs an alarm a bad call pushed into the far future.
pub fn alarm_needs_reset(existing: Option<i64>, now: i64) -> bool {
    match existing { None => true, Some(at) => at > now + 2 * 3_600_000 }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const NOW: i64 = 1_795_200_000_000;   // 2026-11-20
    fn at(ms_ago: i64) -> String { crate::mcp::iso(NOW - ms_ago) }
    fn doc(id: &str, ev: Value) -> Value { json!({"doc_id": id, "event": ev}) }
    fn session(id: &str, responder: Option<bool>) -> Value {
        let mut live = json!({"schema": "live.v1", "started": at(600_000)});
        if let Some(r) = responder { live["responder"] = json!(r); }
        doc(&format!("c-{id}"), json!({"ts": at(600_000), "kind": "item.create", "item": null,
            "body": {"id": id, "type": "idea", "status": "live", "source": "live", "live": live}, "author": {"id": "github:Morami49", "role": "owner"}}))
    }
    fn line(id: &str, sid: &str, text: &str, ms_ago: i64) -> Value {
        doc(id, json!({"ts": at(ms_ago), "kind": "live.line", "item": sid, "body": {"session": sid, "speaker": "Nowed", "text": text,
            "point": {"schema": "pointer.v1", "screenshot": "data:image/png;base64,SECRETPIXELS"}}, "author": {"id": "github:Morami49"}}))
    }
    fn reply(id: &str, sid: &str, line: &str, ms_ago: i64) -> Value {
        doc(id, json!({"ts": at(ms_ago), "kind": "comment", "item": sid, "body": answer_body("ok", "gemini-flash-latest", line),
            "author": {"id": AUTHOR_ID, "label": LABEL, "role": "agent"}, "via": VIA}))
    }
    fn calls(d: &[Decision]) -> Vec<&str> { d.iter().filter(|x| matches!(x.action, Action::Call { .. })).map(|x| x.line.as_str()).collect() }

    #[test]
    fn only_sessions_with_the_switch_on_and_live() {
        let mut docs = vec![session("LV-on", Some(true)), session("LV-off", Some(false)), session("LV-unset", None),
            line("l1", "LV-on", "what does this button do", 1000), line("l2", "LV-off", "what does this button do", 1000),
            line("l3", "LV-unset", "what does this button do", 1000)];
        assert_eq!(calls(&due(&docs, &HashSet::new(), NOW)), vec!["l1"]);
        // switched off later, switched on later
        docs.push(doc("e1", json!({"ts": at(500), "kind": "item.edit", "item": "LV-on", "body": {"live": {"responder": false}}})));
        docs.push(doc("e2", json!({"ts": at(500), "kind": "item.edit", "item": "LV-off", "body": {"live": {"responder": true}}})));
        assert_eq!(calls(&due(&docs, &HashSet::new(), NOW)), vec!["l2"]);
        // an ended session gets nothing
        docs.push(doc("s1", json!({"ts": at(400), "kind": "status", "item": "LV-off", "body": {"status": "open"}})));
        assert!(due(&docs, &HashSet::new(), NOW).is_empty());
    }

    #[test]
    fn one_call_per_line_short_lines_and_freshness() {
        let docs = vec![session("LV-a", Some(true)), line("old", "LV-a", "this is an old line from before", FRESH_MS + 1000),
            line("short", "LV-a", "ok thanks", 3000), line("q", "LV-a", "why?", 2500), line("long", "LV-a", "please explain the map view", 2000),
            line("done", "LV-a", "this one was answered already", 1500), reply("r1", "LV-a", "done", 1000)];
        let d = due(&docs, &HashSet::new(), NOW);
        assert_eq!(calls(&d), vec!["q", "long"]);
        assert!(d.iter().any(|x| x.line == "short" && x.action == Action::Skip("short")));
        assert!(!d.iter().any(|x| x.line == "old" || x.line == "done"));
        let tried: HashSet<String> = ["q", "long", "short"].iter().map(|s| s.to_string()).collect();
        assert!(due(&docs, &tried, NOW).is_empty());
        assert!(worth_answering("is it?") && worth_answering("one two three") && !worth_answering("one two") && !worth_answering("  "));
    }

    #[test]
    fn thirty_answers_per_hour_per_session() {
        let mut docs = vec![session("LV-a", Some(true)), session("LV-b", Some(true))];
        for i in 0..29 { docs.push(reply(&format!("r{i}"), "LV-a", &format!("x{i}"), 50 * 60_000)); }
        docs.push(reply("r-old", "LV-a", "y", 61 * 60_000));   // outside the hour
        docs.push(line("l1", "LV-a", "first new question here", 3000));
        docs.push(line("l2", "LV-a", "second new question here", 2000));
        docs.push(line("l3", "LV-b", "another session is separate", 1000));
        let d = due(&docs, &HashSet::new(), NOW);
        assert_eq!(calls(&d), vec!["l1", "l3"]);
        assert!(d.iter().any(|x| x.line == "l2" && x.action == Action::Skip("rate limit")));
    }

    #[test]
    fn the_prompt_holds_words_only_and_the_last_twelve() {
        let mut docs = vec![session("LV-a", Some(true))];
        for i in 0..14 { docs.push(line(&format!("l{i}"), "LV-a", &format!("line number {i} here"), 300_000 - i as i64 * 1000)); }
        docs.push(doc("rep", json!({"ts": at(1000), "kind": "comment", "item": "LV-a", "body": {"text": "REPORT client 0.2.2", "report": true}, "author": {"id": "github:Morami49"}})));
        docs.push(doc("cl", json!({"ts": at(900), "kind": "comment", "item": "LV-a", "body": {"text": "I'll look at it"}, "author": {"id": "github:Morami49", "label": "Morami49"}, "via": "claude-connector"})));
        docs.push(line("last", "LV-a", "so what next?", 500));
        let tried: HashSet<String> = (0..14).map(|i| format!("l{i}")).collect();
        let d = due(&docs, &tried, NOW);
        let Action::Call { prompt } = &d[0].action else { panic!("{d:?}") };
        assert_eq!(d.len(), 1);
        assert!(prompt.contains("Claude: I'll look at it") && prompt.ends_with("Nowed: so what next?\n\nAnswer the last line."), "{prompt}");
        assert!(!prompt.contains("REPORT") && !prompt.contains("SECRETPIXELS") && !prompt.contains("pointer.v1"));
        assert!(!prompt.contains("line number 3 ") && prompt.contains("line number 4 "));   // 12 rows: l4..l13, Claude, last
        assert_eq!(prompt.matches('\n').count(), 1 + 12 + 1);
    }

    #[test]
    fn retracted_lines_are_skipped_and_answers_marked() {
        let docs = vec![session("LV-a", Some(true)), line("l1", "LV-a", "please do the thing now", 1000),
            doc("x", json!({"ts": at(500), "kind": "retract", "item": "LV-a", "body": {"of": "l1"}}))];
        assert!(due(&docs, &HashSet::new(), NOW).is_empty());
        let b = answer_body("Claude will pick it up when Nowed next messages the chat [for-claude]", "gemini-flash-latest", "l1");
        assert_eq!(b["responder"], true); assert_eq!(b["for_claude"], true); assert_eq!(b["line"], "l1");
        assert_eq!(answer_body("Fine.", "m", "l").get("for_claude"), Some(&json!(false)));
        assert!(wakes(&json!({"kind": "live.line"})) && !wakes(&json!({"kind": "comment"})));
    }

    // Run 4 (21 Nov), exact staging shapes: a Watch line in a fresh session with responder on must be answered.
    #[test]
    fn watch_line_in_fresh_session_is_answered() {
        let docs = vec![
            json!({"doc_id":"lv53be2ec89e85dd747a79","event":{"author":{"id":"github:Morami49","label":"Nowed","role":"owner"},"body":{"body":"x","id":"LV-261121-143725-eb46","live":{"audience":[],"responder":true,"schema":"live.v1","started":"2026-11-21T14:37:25.683Z","via":"watch"},"refs":[],"source":"live","status":"live","title":"t","type":"idea"},"branch":"main","item":null,"kind":"item.create","ts":"2026-11-21T14:37:25.683Z"}}),
            json!({"doc_id":"lv00eb94fd33a6279794cb","event":{"author":{"id":"github:Morami49","label":"Nowed","role":"owner"},"body":{"session":"LV-261121-143725-eb46","speaker":"Nowed","text":"[looks-off] golden path run 4: versions line cramped","ts":"2026-11-21T14:37:26.378Z","via":"watch"},"branch":"main","item":"LV-261121-143725-eb46","kind":"live.line","ts":"2026-11-21T14:37:26.378Z"}}),
        ];
        let now = 1_795_271_848_378; // 14:37:28Z
        let d = due(&docs, &Default::default(), now);
        assert_eq!(d.len(), 1);
        assert!(matches!(d[0].action, Action::Call { .. }));
    }

    #[test]
    fn wake_is_an_offset_not_an_epoch() {
        assert!(WAKE_OFFSET_MS > 0 && WAKE_OFFSET_MS < 5_000);
        let off = next_hour_offset(NOW);
        assert!(off > 60_000 && off <= 3_660_000);
    }

    #[test]
    fn far_future_alarm_is_repaired() {
        assert!(alarm_needs_reset(None, NOW));
        assert!(!alarm_needs_reset(Some(NOW + next_hour_offset(NOW)), NOW));
        assert!(alarm_needs_reset(Some(NOW + NOW + 200), NOW));   // the 21 Nov bug: now + (now + 200)
    }

    // Mechanism guard: the hub must never hand set_alarm an epoch time again.
    #[test]
    fn hub_never_passes_epoch_to_set_alarm() {
        let src = include_str!("../../../../hub/src/lib.rs");
        for (i, l) in src.lines().enumerate() {
            if let Some(p) = l.find("set_alarm(") {
                let arg = &l[p + 10..];
                assert!(!arg.trim_start().starts_with("now"), "hub/src/lib.rs:{}: set_alarm takes an offset, not now + x", i + 1);
            }
        }
    }
}
