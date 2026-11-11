//! Runnable flows (D-174 C2): what the hub plans and computes from a canvas, without any network.

use hub_core::flows::*;
use serde_json::{json, Value};

fn node(id: &str, step: &str, config: Value) -> Value {
    json!({"kind": "flow.node", "branch": "main", "item": null, "body": {"board": "main", "id": id, "step": step, "title": id, "config": config}})
}
fn wire(id: &str, a: &str, b: &str) -> Value {
    json!({"kind": "flow.wire", "branch": "main", "item": null, "body": {"board": "main", "id": id, "from": a, "to": b}})
}

#[test]
fn fold_keeps_latest_config_and_drops_deleted() {
    let evs = vec![
        node("N1", "fetch", json!({"url": "https://a"})),
        node("N2", "filter", json!({})),
        node("N3", "post", json!({})),
        wire("W1", "N1", "N2"), wire("W2", "N2", "N3"),
        json!({"kind": "flow.node", "branch": "main", "body": {"board": "main", "id": "N1", "config": {"url": "https://b"}}}),
        json!({"kind": "flow.node", "branch": "main", "body": {"board": "main", "id": "N3", "deleted": true}}),
        node("NX", "shell", json!({})),                       // not a step: ignored
        json!({"kind": "flow.node", "branch": "try", "body": {"board": "main", "id": "NB", "step": "post"}}), // other branch
    ];
    let f = fold(&evs, "main");
    assert_eq!(f.nodes.len(), 2);
    assert_eq!(f.nodes["N1"].config["url"], "https://b");
    assert_eq!(f.nodes["N1"].step, "fetch", "an edit without step keeps the step");
    assert_eq!(f.wires, vec![("N1".into(), "N2".into())], "wires to deleted steps are gone");
}

#[test]
fn plan_orders_steps_after_their_inputs() {
    // N1 → N2 → N4, N1 → N3 → N4
    let evs = vec![node("N1", "fetch", json!({})), node("N2", "filter", json!({})), node("N3", "calc", json!({})), node("N4", "post", json!({})),
                   wire("a", "N1", "N2"), wire("b", "N1", "N3"), wire("c", "N2", "N4"), wire("d", "N3", "N4")];
    let f = fold(&evs, "main");
    let p = plan(&f, "N1").unwrap();
    let pos = |x: &str| p.iter().position(|y| y == x).unwrap();
    assert_eq!(p.len(), 4);
    assert!(pos("N1") < pos("N2") && pos("N1") < pos("N3") && pos("N2") < pos("N4") && pos("N3") < pos("N4"));
    assert_eq!(inputs_of(&f, "N4"), vec!["N2".to_string(), "N3".to_string()]);
    // starting in the middle runs only what follows
    assert_eq!(plan(&f, "N3").unwrap(), vec!["N3".to_string(), "N4".to_string()]);
}

#[test]
fn plan_refuses_loops_and_unknown_steps() {
    let evs = vec![node("N1", "fetch", json!({})), node("N2", "filter", json!({})), wire("a", "N1", "N2"), wire("b", "N2", "N1")];
    assert!(plan(&fold(&evs, "main"), "N1").is_err());
    assert!(plan(&fold(&evs, "main"), "NOPE").is_err());
}

#[test]
fn filter_with_all_and_none() {
    let items = vec![
        json!({"title": "Night warehouse operative", "pay": 14.5, "needs": "none"}),
        json!({"title": "Delivery driver (own car)", "pay": 16, "needs": "licence"}),
        json!({"title": "Event steward", "pay": "", "needs": "none"}),
        json!({"title": "Kitchen porter", "pay": "£12.20", "needs": "steel-toe boots"}),
    ];
    let cfg = json!({"all": [{"field": "pay", "op": "exists"}, {"field": "pay", "op": ">=", "value": 12}],
                     "none": [{"field": "needs", "op": "contains", "value": "licence"}, {"field": "needs", "op": "contains", "value": "boots"}]});
    let out = filter(items, &cfg).unwrap();
    assert_eq!(out.len(), 1);
    assert_eq!(out[0]["title"], "Night warehouse operative");
    assert!(filter(vec![json!({"a": 1})], &json!({"all": [{"field": "a", "op": "~="}]})).is_err());
}

#[test]
fn calc_sets_fields_and_never_guesses() {
    let items = vec![json!({"pay": 120, "travel": 10, "stay": 30}), json!({"pay": 100, "travel": 0, "stay": 0}), json!({"pay": 90})];
    let cfg = json!({"sets": [{"set": "cost", "a": "travel", "op": "+", "b": "stay"}, {"set": "ratio", "a": "pay", "op": "/", "b": "cost"}]});
    let out = calc(items, &cfg).unwrap();
    assert_eq!(out[0]["cost"], json!(40.0));
    assert_eq!(out[0]["ratio"], json!(3.0));
    assert_eq!(out[1]["ratio"], Value::Null, "divide by zero gives no number, not infinity");
    assert_eq!(out[2]["cost"], Value::Null, "missing fields give no number");
    let out = calc(vec![json!({"p": 10})], &json!({"sets": [{"set": "x", "a": "p", "op": "*", "b": 1.35}]})).unwrap();
    assert_eq!(out[0]["x"], json!(13.5));
}

#[test]
fn render_templates() {
    let it = json!({"jobTitle": "Steward", "pay": {"min": 12.5}, "n": 3});
    assert_eq!(render("{{jobTitle}} · £{{pay.min}} · {{n}} · {{missing}}", &it), "Steward · £12.5 · 3 · ");
    assert_eq!(render("no braces", &it), "no braces");
    assert_eq!(render("half {{open", &it), "half {{open");
}

#[test]
fn items_from_a_fetched_body() {
    let body = json!({"results": [{"a": 1}, {"a": 2}], "total": 2});
    assert_eq!(as_items(body.clone(), "results").len(), 2);
    assert_eq!(as_items(body.clone(), "").len(), 1);
    assert_eq!(as_items(body, "nope").len(), 0);
    assert_eq!(get_path(&json!({"a": [{"b": 7}]}), "a.0.b"), json!(7));
}

#[test]
fn flows_cannot_reach_hub_secrets_or_the_hub_itself() {
    assert_eq!(secret_var("reed").as_deref(), Some("NODE_SECRET_REED"));
    for bad in ["", "HUB WRITE", "../x", "a-b"] { assert!(secret_var(bad).is_none(), "{bad}"); }
    assert!(url_allowed("https://www.reed.co.uk/api/1.0/search?keywords=temp"));
    for bad in ["http://plain.example", "https://clanstack-hub.ndab-utube.workers.dev/studio/api/events", "https://localhost/x",
                "https://user@evil.example/", "ftp://x", "https://127.0.0.1/"] {
        assert!(!url_allowed(bad), "{bad}");
    }
}

#[test]
fn base64_matches_rfc_4648() {
    for (i, o) in [("", ""), ("f", "Zg=="), ("fo", "Zm8="), ("foo", "Zm9v"), ("foob", "Zm9vYg=="), ("fooba", "Zm9vYmE="), ("foobar", "Zm9vYmFy")] {
        assert_eq!(base64(i.as_bytes()), o);
    }
}

#[test]
fn runner_seed_is_separate_from_sessions() {
    assert_ne!(runner_seed("s"), hub_core::session::session_key("s"));
    assert_eq!(runner_seed("s"), runner_seed(" s "));
}
