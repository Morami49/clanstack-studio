use hub_core::digest::fold;
use serde_json::json;

#[test]
fn digest_lists_live_rules_open_questions_and_latest_replies() {
    let evs = vec![
        json!({"kind": "item.create", "ts": "1", "body": {"id": "G-reply-order", "type": "protocol", "title": "Replies in reading order", "status": "active"}}),
        json!({"kind": "item.create", "ts": "2", "body": {"id": "G-old", "title": "Old rule", "status": "superseded"}}),
        json!({"kind": "item.create", "ts": "3", "body": {"id": "Q-RB1", "title": "Recover?", "status": "open"}}),
        json!({"kind": "answer", "ts": "4", "item": "Q-RB1", "body": {"code": "b"}}),
        json!({"kind": "item.create", "ts": "5", "body": {"id": "Q-done", "title": "Done one", "status": "open"}}),
        json!({"kind": "status", "ts": "6", "item": "Q-done", "body": {"status": "done"}}),
        json!({"kind": "item.create", "ts": "7", "body": {"id": "R-1", "title": "First reply", "status": "open"}}),
        json!({"kind": "item.create", "ts": "8", "body": {"id": "R-2", "title": "Second reply", "status": "open"}}),
        json!({"kind": "item.edit", "ts": "9", "item": "G-reply-order", "body": {"title": "Replies in reading order, coded asks"}}),
        json!({"kind": "comment", "ts": "10", "item": "R-1", "body": {"text": "no title change"}}),
    ];
    let d = fold(evs.iter());
    let ids = |k: &str| d[k].as_array().unwrap().iter().map(|r| r["id"].as_str().unwrap().to_string()).collect::<Vec<_>>();
    assert_eq!(ids("rules"), ["G-reply-order"], "superseded rules drop out");
    assert_eq!(d["rules"][0]["title"], "Replies in reading order, coded asks", "edits update titles");
    assert_eq!(ids("open_questions"), ["Q-RB1"], "done questions drop out");
    assert_eq!(d["open_questions"][0]["last_answer"], "b");
    assert_eq!(ids("recent_replies"), ["R-1", "R-2"], "most recently touched first");
    assert!(d["read_first"].as_str().unwrap().contains("G-reply-order"));
}
