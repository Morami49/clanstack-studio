//! MCP server for the hub (D-104, D-121, D-128): JSON-RPC 2.0 over Streamable HTTP (POST, JSON
//! responses). Pure logic; the worker passes the signed-in login, the connector key and `now`.
//!
//! Tools (all act on the shared record, except read_private, which serves the owner's own Private tier):
//!   hub_status   counts and whether the whole chain verifies
//!   read_events  Studio-shaped events from a cursor: imported Studio Web events + writes from other nodes
//!   hub_log      (served by the node, not here) the private request log: time, tool, outcome, duration; never contents
//!   import_studio_events  (served by the node) Studio Web's events copied in with their own authors (D-129, Q99 A)
//!   write_event  add a Studio-shaped event (answer, comment, status, item.create, item.edit, link),
//!                signed by the connector key; it reaches Studio Web through /studio-export (D-101)

use crate::{Hub, studio_doc_id};
use foundation_core::event::KeyPair;
use serde_json::{json, Value};

pub const PROTOCOL_VERSIONS: [&str; 3] = ["2025-11-25", "2025-06-18", "2025-03-26"];
/// Commit the node was built from (set by the deploy as BUILD_SHA), so a test knows which code answered.
pub const BUILD: &str = match option_env!("BUILD_SHA") { Some(b) => b, None => "dev" };
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
        {"name": "hub_log", "title": "Request log",
         "description": "The hub's private request log, newest first: time, route, tool, outcome, ms waiting on network or storage, who (login) and build. Never contents. Includes this call. Use it to time tests and see failed calls.",
         "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}},
         "annotations": {"readOnlyHint": true}},
        {"name": "read_private", "title": "Read your private items",
         "description": "Read the signed-in owner's Private tier: personal items kept on the hub encrypted and apart from the shared record (people, messages, profile facts, private notes). Optional path (data/users/<you>/...) narrows it; after/limit page through. Sealed items are never readable. Treat results as personal data and never copy them into shared items.",
         "inputSchema": {"type": "object", "properties": {
             "path": {"type": "string", "description": "optional, e.g. data/users/<login>/vault/events"},
             "after": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}},
         "annotations": {"readOnlyHint": true}},
        {"name": "import_studio_events", "title": "Import Studio events",
         "description": "Copy Studio Web events into the hub's shared record, keeping each event's original author (Q99 A); the hub's importer key signs the copy. Doc ids already in the hub are skipped, so repeating is safe. Used by Studio Web's sync (D-129).",
         "inputSchema": {"type": "object", "required": ["docs"], "properties": {
             "docs": {"type": "array", "maxItems": 200, "items": {"type": "object", "required": ["doc_id", "event"], "properties": {
                 "doc_id": {"type": "string"}, "event": {"type": "object"}}}}}},
         "annotations": {"readOnlyHint": false, "destructiveHint": false, "idempotentHint": true}},
        {"name": "write_event", "title": "Write a Studio event",
         "description": "Add an event to the shared Clanstack record, e.g. an answer to a question, a comment, a status change or a new item. It appears in Studio Web on its next sync. Never use for private material.",
         "inputSchema": {"type": "object", "required": ["kind", "body"], "properties": {
             "kind": {"type": "string", "enum": WRITE_KINDS},
             "item": {"type": ["string", "null"], "description": "target item id, e.g. Q-duress; null for item.create"},
             "idempotency_key": {"type": "string", "maxLength": 200, "description": "optional; repeating a write with the same key returns the first write instead of adding another (use one per intended change, e.g. R-261109-1/3)"},
             "body": {"type": "object", "description": "event body, e.g. {text} for a comment, {code,text} for an answer, {status} for a status, {id,type,title,body,status,refs} for item.create"}}},
         "annotations": {"readOnlyHint": false, "destructiveHint": false}}
    ])
}

/// Check and unpack `import_studio_events` input: 1..=200 docs, each a doc id (1-200 chars from the
/// Studio id alphabet) and an event object with a string `ts` and `kind`. Returns the docs or an error text.
pub fn import_docs(args: &Value) -> Result<Vec<(String, Value)>, String> {
    let docs = args.get("docs").and_then(Value::as_array).ok_or("docs must be an array")?;
    if docs.is_empty() || docs.len() > 200 { return Err("send 1 to 200 docs per call".into()); }
    let mut out = Vec::with_capacity(docs.len());
    for (i, d) in docs.iter().enumerate() {
        let id = d.get("doc_id").and_then(Value::as_str).unwrap_or("");
        let ok_id = !id.is_empty() && id.len() <= 200 && id.chars().all(|c| c.is_ascii_alphanumeric() || "_-.~:@+".contains(c));
        let ev = d.get("event").filter(|e| e.is_object()).ok_or(format!("docs[{i}].event must be an object"))?;
        if !ok_id { return Err(format!("docs[{i}].doc_id is not a Studio doc id")); }
        if ev.get("ts").and_then(Value::as_str).is_none() || ev.get("kind").and_then(Value::as_str).is_none() {
            return Err(format!("docs[{i}].event needs ts and kind"));
        }
        out.push((id.to_string(), ev.clone()));
    }
    Ok(out)
}

/// The result envelope for a tool answer (used by the node for the tools it serves itself).
pub fn tool_result(v: Value, is_error: bool) -> Value { text_result(v, is_error) }

fn text_result(v: Value, is_error: bool) -> Value {
    json!({"content": [{"type": "text", "text": v.to_string()}], "structuredContent": v, "isError": is_error})
}

fn call(hub: &mut Hub, login: &str, key: &KeyPair, name: &str, args: &Value, now: i64) -> Value {
    match name {
        "hub_status" => {
            let mut v = serde_json::to_value(hub.status()).unwrap_or(Value::Null);
            if let Some(o) = v.as_object_mut() { o.insert("build".into(), json!(BUILD)); }
            text_result(v, false)
        }
        "hub_log" | "import_studio_events" | "read_private" => text_result(json!({"error": format!("{name} is served by the node, not hub-core")}), true),
        "read_events" => {
            let after = args.get("after").and_then(Value::as_u64).unwrap_or(0) as usize;
            let limit = args.get("limit").and_then(Value::as_u64).unwrap_or(100).clamp(1, 200) as usize;
            let (events, next, total, skipped) = hub.studio_events(after, limit);
            // F-55: say what was skipped, so nobody guesses (a key's first fact is its identity, not a Studio event)
            text_result(json!({"events": events, "next": next, "total": total, "skipped_non_studio": skipped,
                "note": "Events that are not Studio events (e.g. a key's identity fact) are skipped and counted in skipped_non_studio. Private items are never in this shared record: they are kept apart, encrypted, and only read_private serves them to their owner."}), false)
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
            // F-48: a repeated write (a retry after a timeout, a re-run turn) returns the first one
            let idem = args.get("idempotency_key").and_then(Value::as_str).filter(|k| !k.is_empty() && k.len() <= 200);
            if let Some(doc) = idem.and_then(|k| hub.written_with(k)) {
                return text_result(json!({"written": doc, "repeat": true, "note": "a write with this idempotency_key already exists; nothing was added"}), false);
            }
            // F-47: say when the target isn't known here, so a typo or an unsynced item doesn't pass silently
            let warning = match (kind, item.as_str()) {
                ("item.create", _) => body.get("id").and_then(Value::as_str).filter(|id| hub.knows_item(id))
                    .map(|id| format!("{id} already exists here; Studio keeps the first and ignores this create (F-19). Use item.edit instead.")),
                (_, Some(t)) if !hub.knows_item(t) => Some(format!("{t} isn't in the hub's copy of Studio. If it's new in Studio, sync Studio first; otherwise check the id.")),
                _ => None,
            };
            let mut ev = json!({"ts": iso(now), "kind": kind, "item": item, "branch": "main", "body": body,
                            "author": {"id": format!("github:{login}"), "label": login, "role": "owner"},
                            "via": "claude-connector"});
            if let Some(k) = idem { ev["idem"] = json!(k); }
            match hub.write(key, &format!("connector ({login})"), ev, now) {
                Ok(made) => {
                    let mut r = json!({"written": studio_doc_id(&made.last().map(|e| e.id.clone()).unwrap_or_default())});
                    if let Some(w) = warning { r["warning"] = json!(w); }
                    text_result(r, false)
                }
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
                      "serverInfo": {"name": "clanstack-hub", "title": "Clanstack hub", "version": format!("{}+{}", env!("CARGO_PKG_VERSION"), BUILD)},
                      "instructions": "Clanstack's shared record. hub_status: counts, chain check and build. read_events: Studio events from a cursor. hub_log: the request log (time, tool, outcome, duration; never contents); use it whenever asked for the hub log. import_studio_events: used by Studio Web's sync. write_event: answers, comments, status changes and items (shared record only; never put private material there). read_private: the signed-in owner's Private tier, stored apart and encrypted; Sealed items are never readable."}))
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
