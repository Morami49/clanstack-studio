//! Parity with the Python Gate: every vector actionmap/gate/tests/export_vectors.py wrote from gate_core.py
//! must come out identical here. Regenerate with `python actionmap/gate/tests/export_vectors.py`.

use driver_core::decide::{norm_keys, proc_name, Action, Context};
use driver_core::log::{clean_args, iso, log_entry, looks_secret, mask_value, LogInput};
use driver_core::words::hit;
use driver_core::zones::{load_zones_value, parse_zones_value, upgrade_zones, Zones};
use driver_core::{decide, redact_snapshot, GATE_VERSION};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::PathBuf;

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn vectors(name: &str) -> Value {
    let p = root().join("tests/vectors").join(name);
    let v: Value = serde_json::from_str(&std::fs::read_to_string(&p).expect("vectors missing: run export_vectors.py")).unwrap();
    assert_eq!(v["version"], GATE_VERSION, "{name} was exported from another Gate version");
    v
}

fn zone_sets(v: &Value) -> BTreeMap<String, Zones> {
    v["zones"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, z)| (k.clone(), Zones::from_value(z.clone()).unwrap_or_else(|e| panic!("zone set {k}: {e}"))))
        .collect()
}

fn s(v: &Value) -> String {
    v.as_str().unwrap_or_else(|| panic!("not a string: {v}")).to_string()
}

#[test]
fn words_match_like_python_regex() {
    let v = vectors("words.json");
    let mut n = 0;
    for c in v["cases"].as_array().unwrap() {
        let words: Vec<String> = c["words"].as_array().unwrap().iter().map(s).collect();
        let texts: Vec<String> = c["texts"].as_array().unwrap().iter().map(s).collect();
        let texts: Vec<&str> = texts.iter().map(|t| t.as_str()).collect();
        let want = c["hit"].as_str().map(String::from);
        assert_eq!(hit(&words, &texts), want, "words {:?} texts {:?}", words, texts);
        n += 1;
    }
    assert!(n > 1000);
}

#[test]
fn decide_matches_python_for_every_vector() {
    let v = vectors("decide.json");
    let zs = zone_sets(&v);
    let acts: Vec<Action> = v["actions"].as_array().unwrap().iter().map(|a| serde_json::from_value(a.clone()).unwrap()).collect();
    let ctxs: Vec<Context> =
        v["contexts"].as_array().unwrap().iter().map(|c| serde_json::from_value(c.clone()).unwrap()).collect();
    let reasons: Vec<String> = v["reasons"].as_array().unwrap().iter().map(s).collect();
    let mut bad = vec![];
    let cases = v["cases"].as_array().unwrap();
    for c in cases {
        let (zn, ai, ci) = (s(&c[0]), c[1].as_u64().unwrap() as usize, c[2].as_u64().unwrap() as usize);
        let want = (s(&c[3]), reasons[c[4].as_u64().unwrap() as usize].clone());
        let (zone, why) = decide(&acts[ai], &ctxs[ci], &zs[&zn]);
        if (zone.as_str().to_string(), why.clone()) != want {
            bad.push(format!(
                "zones {zn} action {} context {}: rust ({}, {why}) python ({}, {})",
                v["actions"][ai], v["contexts"][ci], zone.as_str(), want.0, want.1
            ));
        }
    }
    assert!(bad.is_empty(), "{} of {} differ:\n{}", bad.len(), cases.len(), bad[..bad.len().min(20)].join("\n"));
    assert!(cases.len() > 10_000);
}

#[test]
fn default_zones_load_like_python() {
    let v = vectors("decide.json");
    let text = std::fs::read_to_string(root().join("../../../actionmap/gate/zones.json")).unwrap();
    let text = text.strip_prefix('\u{feff}').unwrap_or(&text);
    assert_eq!(load_zones_value(None, Some(text)).unwrap(), v["zones"]["default"], "the shipped zones.json changed: re-export");
}

#[test]
fn redact_matches_python() {
    let v = vectors("redact.json");
    let dz = zone_sets(&vectors("decide.json"));
    for c in v["cases"].as_array().unwrap() {
        let (out, n) = redact_snapshot(c["text"].as_str().unwrap(), &dz[&s(&c["zones"])]);
        assert_eq!(out, s(&c["out"]), "zones {} text {:?}", c["zones"], c["text"]);
        assert_eq!(n as u64, c["hidden"].as_u64().unwrap(), "hidden count for {:?}", c["text"]);
    }
}

#[test]
fn log_matches_python() {
    let v = vectors("log.json");
    for c in v["mask_text"].as_array().unwrap() {
        let got = mask_value(Some(&c["text"]), c["secret"].as_bool().unwrap(), c["limit"].as_u64().unwrap() as usize);
        assert_eq!(got, s(&c["out"]), "mask_text {c}");
    }
    for c in v["looks_secret"].as_array().unwrap() {
        let got = looks_secret(c["element_name"].as_str().unwrap(), c["element_type"].as_str().unwrap(), c["is_password"].as_bool().unwrap());
        assert_eq!(Value::Bool(got), c["out"], "looks_secret {c}");
    }
    for c in v["clean_args"].as_array().unwrap() {
        let ctx: Context = serde_json::from_value(c["ctx"].clone()).unwrap();
        let got = clean_args(c["args"].as_object().unwrap(), &ctx);
        assert_eq!(Value::Object(got), c["out"], "clean_args {c}");
    }
    for c in v["log_entry"].as_array().unwrap() {
        let i: LogInput = serde_json::from_value(c["in"].clone()).unwrap();
        let got = serde_json::to_value(log_entry(&i)).unwrap();
        assert_eq!(got, c["out"], "log_entry {}", c["in"]);
    }
    for c in v["iso"].as_array().unwrap() {
        assert_eq!(iso(c["ts"].as_f64().unwrap()), s(&c["out"]), "iso {}", c["ts"]);
    }
    for c in v["norm_keys"].as_array().unwrap() {
        let want: Vec<String> = c["out"].as_array().unwrap().iter().map(s).collect();
        assert_eq!(norm_keys(c["shortcut"].as_str().unwrap()), want, "norm_keys {}", c["shortcut"]);
    }
    for c in v["proc"].as_array().unwrap() {
        assert_eq!(proc_name(c["name"].as_str().unwrap()), s(&c["out"]), "_proc {}", c["name"]);
    }
}

#[test]
fn zones_parse_load_and_upgrade_match_python() {
    let v = vectors("zones.json");
    for c in v["parse"].as_array().unwrap() {
        let d = if c["defaults"].is_null() { None } else { Some(&c["defaults"]) };
        let got = parse_zones_value(c["text"].as_str().unwrap(), d).unwrap();
        assert_eq!(got, c["out"], "parse_zones {:?}", c["text"]);
        Zones::from_value(got).expect("typed zones");
    }
    for c in v["load"].as_array().unwrap() {
        let got = load_zones_value(c["user"].as_str(), c["defaults"].as_str()).unwrap();
        assert_eq!(got, c["out"]);
    }
    for c in v["upgrade"].as_array().unwrap() {
        let (out, added) = upgrade_zones(&c["user"], &c["default"]);
        assert_eq!(out, c["out"], "upgrade_zones user {}", c["user"]);
        assert_eq!(serde_json::to_value(added).unwrap(), c["added"]);
    }
}
