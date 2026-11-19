//! The resume digest (19 Nov, "memory flexibility across chats"): what every new chat or tool needs before it
//! answers, so context survives compressed or parallel chats. Folded from the Studio events the caller may see.
//! Returned by begin_answer and by the `resume` tool. Titles and ids only: bodies stay in the record.
use serde_json::{json, Value};
use std::collections::BTreeMap;

#[derive(Default, Clone)]
struct It { title: String, kind: String, status: String, ts: String, answer: Option<String>, seq: usize }

const DONE: [&str; 5] = ["done", "closed", "answered", "superseded", "mitigated"];

/// `events` in record order (each a Studio event: kind, item, body, ts).
pub fn fold<'a>(events: impl Iterator<Item = &'a Value>) -> Value {
    let mut items: BTreeMap<String, It> = BTreeMap::new();
    for (seq, e) in events.enumerate() {
        let kind = e.get("kind").and_then(Value::as_str).unwrap_or("");
        let body = e.get("body").cloned().unwrap_or(Value::Null);
        let ts = e.get("ts").and_then(Value::as_str).unwrap_or("").to_string();
        let id = match kind {
            "item.create" => body.get("id").and_then(Value::as_str).map(String::from),
            _ => e.get("item").and_then(Value::as_str).map(String::from),
        };
        let Some(id) = id else { continue };
        let it = items.entry(id).or_default();
        it.seq = seq;
        it.ts = ts;
        match kind {
            "item.create" | "item.edit" => {
                if let Some(t) = body.get("title").and_then(Value::as_str) { it.title = t.chars().take(120).collect(); }
                if let Some(t) = body.get("type").and_then(Value::as_str) { it.kind = t.to_string(); }
                if let Some(s) = body.get("status").and_then(Value::as_str) { it.status = s.to_string(); }
            }
            "status" => { if let Some(s) = body.get("status").and_then(Value::as_str) { it.status = s.to_string(); } }
            "answer" => { it.answer = body.get("code").and_then(Value::as_str).map(|c| c.chars().take(60).collect()); }
            _ => {}
        }
    }
    let row = |id: &String, it: &It| json!({"id": id, "title": it.title, "status": it.status, "last_answer": it.answer, "ts": it.ts});
    let mut by_recent: Vec<(&String, &It)> = items.iter().filter(|(_, it)| !it.title.is_empty()).collect();
    by_recent.sort_by(|a, b| b.1.seq.cmp(&a.1.seq));
    let rules: Vec<Value> = by_recent.iter()
        .filter(|(id, it)| (id.starts_with("G-") || id.starts_with("RULE-")) && !DONE.contains(&it.status.as_str()))
        .take(30).map(|(id, it)| json!({"id": id, "title": it.title, "status": it.status})).collect();
    let open_questions: Vec<Value> = by_recent.iter()
        .filter(|(id, it)| id.starts_with("Q-") && !DONE.contains(&it.status.as_str()))
        .take(25).map(|(id, it)| row(id, it)).collect();
    let recent_replies: Vec<Value> = by_recent.iter().filter(|(id, _)| id.starts_with("R-")).take(10).map(|(id, it)| row(id, it)).collect();
    let open_findings: Vec<Value> = by_recent.iter()
        .filter(|(id, it)| (id.starts_with("F-") || id.starts_with("INC-") || id.starts_with("AUD-")) && !DONE.contains(&it.status.as_str()))
        .take(10).map(|(id, it)| row(id, it)).collect();
    json!({
        "read_first": "Context for any chat or tool before answering Nowed. Follow every rule listed (read_events for its body when unsure). Reply in G-reply-order form; split personal and developer per G-compartments; record his codes as answer events on Q- items (G-chat-graph); check here before re-asking anything.",
        "rules": rules, "open_questions": open_questions, "recent_replies": recent_replies, "open_findings": open_findings,
    })
}
