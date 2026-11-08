//! MCP server for the hub (D-104, D-121, D-128): JSON-RPC 2.0 over Streamable HTTP (POST, JSON
//! responses). Pure logic; the worker passes the signed-in login, the connector key and `now`.
//!
//! Tools (all act on the shared record, never on private compartments):
//!   hub_status   counts and whether the whole chain verifies
//!   read_events  Studio-shaped events from a cursor: imported Studio Web events + writes from other nodes
//!   write_event  add a Studio-shaped event (answer, comment, status, item.create, item.edit, link),
//!                signed by the connector key; it reaches Studio Web through /studio-export (D-101)

use crate::{Hub, IMPORT_KIND, WRITE_KIND, studio_doc_id};
use foundation_core::event::KeyPair;
use serde_json::{json, Value};

pub const PROTOCOL_VERSIONS: [&str; 3] = ["2025-11-25", "2025-06-18", "2025-03-26"];
pub const WRITE_KINDS: [&str; 6] = ["answer", "comment", "status", "item.create", "item.edit", "link"];

/// Milliseconds since 1970 → `YYYY-MM-DDTHH:MM:SS.mmmZ` (Studio's timestamp shape).
pub fn iso(ms: i64) -> String {
    let (secs, milli) = (ms.div_euclid(1000), ms.rem_euclid(1000));
    let (days, rem) = (secs.div_euclid(86_400), secs.rem_euclid(86_400));
    // civil-from-days (Howard Hinnant)
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + if m <= 2 { 1 } else { 0 };
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}.{milli:03}Z", rem / 3600, rem % 3600 / 60, rem % 60)
}

fn tools() -> Value {
    json!([
        {"name": "hub_status", "title": "Hub status",
         "description": "How many events the Clanstack hub holds and whether its whole signed chain verifies.",
         "inputSchema": {"type": "object", "properties": {}},
         "annotations": {"readOnlyHint": true}},
        {"name": "read_events", "title": "Read Studio events",
         "description": "Read Clanstack Studio events from the hub's shared record, oldest first, from a cursor. Returns {events:[{doc_id, event}], next}; pass next back as after to continue.",
         "inputSchema": {"type": "object", "properties": {
             "after": {"type": "integer", "minimum": 0, "description": "cursor from a previous call (0 to start)"},
             "limit": {"type": "integer", "minimum": 1, "maximum": 200}}},
         "annotations": {"readOnlyHint": true}},
        {"name": "write_event", "title": "Write a Studio event",
         "description": "Add an event to the shared Clanstack record, e.g. an answer to a question, a comment, a status change or a new item. It appears in Studio Web on its next sync. Never use for private material.",
         "inputSchema": {"type": "object", "required": ["kind", "body"], "properties": {
             "kind": {"type": "string", "enum": WRITE_KINDS},
             "item": {"type": ["string", "null"], "description": "target item id, e.g. Q-duress; null for item.create"},
             "body": {"type": "object", "description": "event body, e.g. {text} for a comment, {code,text} for an answer, {status} for a status, {id,type,title,body,status,refs} for item.create"}}},
         "annotations": {"readOnlyHint": false, "destructiveHint": false}}
    ])
}

fn text_result(v: Value, is_error: bool) -> Value {
    json!({"content": [{"type": "text", "text": v.to_string()}], "structuredContent": v, "isError": is_error})
}

fn call(hub: &mut Hub, login: &str, key: &KeyPair, name: &str, args: &Value, now: i64) -> Value {
    match name {
        "hub_status" => text_result(serde_json::to_value(hub.status()).unwrap_or(Value::Null), false),
        "read_events" => {
            let after = args.get("after").and_then(Value::as_u64).unwrap_or(0) as usize;
            let limit = args.get("limit").and_then(Value::as_u64).unwrap_or(100).clamp(1, 200) as usize;
            let page = hub.pull(after, limit);
            let events: Vec<Value> = page.events.iter().filter_map(|e| match e.u.kind.as_str() {
                k if k == IMPORT_KIND => Some(json!({"doc_id": e.u.body.get("doc_id"), "event": e.u.body.get("event")})),
                k if k == WRITE_KIND => Some(json!({"doc_id": studio_doc_id(&e.id), "event": e.u.body})),
                _ => None,
            }).collect();
            text_result(json!({"events": events, "next": page.next, "total": page.total}), false)
        }
        "write_event" => {
            let kind = args.get("kind").and_then(Value::as_str).unwrap_or("");
            if !WRITE_KINDS.contains(&kind) {
                return text_result(json!({"error": format!("kind must be one of {WRITE_KINDS:?}")}), true);
            }
            let body = match args.get("body") { Some(b) if b.is_object() => b.clone(), _ => return text_result(json!({"error": "body must be an object"}), true) };
            let item = args.get("item").cloned().unwrap_or(Value::Null);
            if kind != "item.create" && !item.is_string() {
                return text_result(json!({"error": "item is required for this kind"}), true);
            }
            if kind == "item.create" && body.get("id").and_then(Value::as_str).is_none() {
                return text_result(json!({"error": "item.create needs body.id"}), true);
            }
            let ev = json!({"ts": iso(now), "kind": kind, "item": item, "branch": "main", "body": body,
                            "author": {"id": format!("github:{login}"), "label": login, "role": "owner"},
                            "via": "claude-connector"});
            match hub.write(key, &format!("connector ({login})"), ev, now) {
                Ok(made) => text_result(json!({"written": studio_doc_id(&made.last().map(|e| e.id.clone()).unwrap_or_default())}), false),
                Err(e) => text_result(json!({"error": format!("{e:?}")}), true),
            }
        }
        _ => text_result(json!({"error": format!("unknown tool {name}")}), true),
    }
}

/// Handle one JSON-RPC message. Returns None for notifications. `made` collects new events to persist.
pub fn handle(hub: &mut Hub, login: &str, key: &KeyPair, msg: &Value, now: i64) -> Option<Value> {
    let id = msg.get("id").cloned();
    let method = msg.get("method").and_then(Value::as_str).unwrap_or("");
    let id = id?; // notifications (no id) get no response
    let ok = |r: Value| Some(json!({"jsonrpc": "2.0", "id": id.clone(), "result": r}));
    let err = |code: i64, m: &str| Some(json!({"jsonrpc": "2.0", "id": id.clone(), "error": {"code": code, "message": m}}));
    match method {
        "initialize" => {
            let asked = msg.pointer("/params/protocolVersion").and_then(Value::as_str).unwrap_or("");
            let v = if PROTOCOL_VERSIONS.contains(&asked) { asked } else { PROTOCOL_VERSIONS[0] };
            ok(json!({"protocolVersion": v, "capabilities": {"tools": {"listChanged": false}},
                      "serverInfo": {"name": "clanstack-hub", "title": "Clanstack hub", "version": env!("CARGO_PKG_VERSION")},
                      "instructions": "Clanstack's shared record. Read with read_events; write answers, comments and items with write_event. Private compartments are never exposed here."}))
        }
        "ping" => ok(json!({})),
        "tools/list" => ok(json!({"tools": tools()})),
        "tools/call" => {
            let name = msg.pointer("/params/name").and_then(Value::as_str).unwrap_or("");
            let args = msg.pointer("/params/arguments").cloned().unwrap_or(json!({}));
            ok(call(hub, login, key, name, &args, now))
        }
        "" => err(-32600, "invalid request"),
        _ => err(-32601, "method not found"),
    }
}
