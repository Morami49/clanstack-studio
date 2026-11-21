//! zones.json (gate.zones.v1): the same file Python Gate reads, with serde.
//!
//! - `parse_zones` = gate_core `parse_zones`: `_`-keys (comments) dropped at every level, missing keys taken
//!   from the shipped defaults (deep merge), `_sha` = first 12 hex of the file's SHA-256.
//! - `load_zones` = gate_core `load_zones` without the file reads (the caller passes the texts).
//! - `upgrade_zones` = gate_core `upgrade_zones`, on the raw files (comments and `_changes` kept).
//!
//! Keys this crate doesn't use (capture, auto_reports, gui, notes, ...) are kept in `extra`, so nothing is
//! lost when a file is read and written back.

use serde::{Deserialize, Deserializer, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

use crate::py;

/// A list of strings where `null` items are skipped (Python drops them: `_proc(None)` is "" and `_rx`
/// filters falsy words). A non-string item is a load error (Python would raise on first use).
fn str_list<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<String>, D::Error> {
    let v: Option<Vec<Option<String>>> = Option::deserialize(d)?;
    Ok(v.unwrap_or_default().into_iter().flatten().collect())
}

fn opt_str_list<'de, D: Deserializer<'de>>(d: D) -> Result<Option<Vec<String>>, D::Error> {
    let v: Option<Vec<Option<String>>> = Option::deserialize(d)?;
    Ok(v.map(|v| v.into_iter().flatten().collect()))
}

fn null_default<'de, D: Deserializer<'de>, T: Deserialize<'de> + Default>(d: D) -> Result<T, D::Error> {
    Ok(Option::<T>::deserialize(d)?.unwrap_or_default())
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct NeverGroup {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    /// "all" (default: reads hidden too) or "input" (only clicks/keys/typing refused).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub applies_to: Option<String>,
    #[serde(default, deserialize_with = "str_list")]
    pub processes: Vec<String>,
    #[serde(default, deserialize_with = "str_list")]
    pub title_words: Vec<String>,
    #[serde(default, deserialize_with = "str_list")]
    pub element_words: Vec<String>,
    #[serde(default, deserialize_with = "str_list", skip_serializing_if = "Vec::is_empty")]
    pub only_in_processes: Vec<String>,
    #[serde(default, deserialize_with = "str_list", skip_serializing_if = "Vec::is_empty")]
    pub scoped_words: Vec<String>,
    /// Truthy: every Snapshot line naming one of this group's title_words has its quoted values hidden.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub redact_elements: Option<Value>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

impl NeverGroup {
    pub fn input_only(&self) -> bool {
        self.applies_to.as_deref() == Some("input")
    }
    pub fn label(&self) -> &str {
        self.name.as_deref().unwrap_or("never")
    }
    pub fn redacts_elements(&self) -> bool {
        py::truthy_opt(self.redact_elements.as_ref())
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ShellApps {
    #[serde(default, deserialize_with = "str_list")]
    pub processes: Vec<String>,
    #[serde(default, deserialize_with = "str_list")]
    pub names: Vec<String>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ConfirmRules {
    #[serde(default, deserialize_with = "str_list")]
    pub element_words: Vec<String>,
    #[serde(default, deserialize_with = "str_list")]
    pub enter_after_typing_words: Vec<String>,
    #[serde(default, deserialize_with = "str_list")]
    pub key_combos: Vec<String>,
    /// popup_timeout_s, grant_minutes, ...
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ConfirmApp {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(default, deserialize_with = "str_list")]
    pub processes: Vec<String>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Zones {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub revision: Option<Value>,
    #[serde(default, deserialize_with = "null_default")]
    pub never: Vec<NeverGroup>,
    /// Missing: ["Nodach Gate"].
    #[serde(default, deserialize_with = "opt_str_list", skip_serializing_if = "Option::is_none")]
    pub gate_titles: Option<Vec<String>>,
    #[serde(default, deserialize_with = "null_default")]
    pub shell_apps: ShellApps,
    #[serde(default, deserialize_with = "null_default")]
    pub confirm: ConfirmRules,
    #[serde(default, deserialize_with = "null_default")]
    pub confirm_apps: Vec<ConfirmApp>,
    #[serde(default, deserialize_with = "str_list")]
    pub auto_apps: Vec<String>,
    #[serde(rename = "_sha", default, skip_serializing_if = "Option::is_none")]
    pub sha: Option<String>,
    /// capture, auto_reports, gui, ... (and `_` keys when built from a raw file).
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

pub const DEFAULT_GATE_TITLES: &[&str] = &["Nodach Gate"];

impl Zones {
    pub fn from_value(v: Value) -> Result<Zones, serde_json::Error> {
        serde_json::from_value(v)
    }

    pub fn gate_titles(&self) -> Vec<String> {
        match &self.gate_titles {
            Some(t) => t.clone(),
            None => DEFAULT_GATE_TITLES.iter().map(|s| s.to_string()).collect(),
        }
    }

    /// `int(zones.get("revision") or 0)`.
    pub fn revision_number(&self) -> i64 {
        py::int_or_zero(self.revision.as_ref()).unwrap_or(0)
    }

    /// The `zones_rev` the log carries: `"{revision}-{_sha}"`.
    pub fn zones_rev(&self) -> String {
        let r = self.revision.as_ref().map(py::to_str).unwrap_or_else(|| "0".into());
        format!("{}-{}", r, self.sha.as_deref().unwrap_or(""))
    }
}

/// gate_core `_strip_comments`.
pub fn strip_comments(v: &Value) -> Value {
    match v {
        Value::Object(o) => Value::Object(
            o.iter().filter(|(k, _)| !k.starts_with('_')).map(|(k, v)| (k.clone(), strip_comments(v))).collect(),
        ),
        Value::Array(a) => Value::Array(a.iter().map(strip_comments).collect()),
        other => other.clone(),
    }
}

/// gate_core `deep_merge(base, over)`: dicts merge recursively, everything else in `over` replaces.
pub fn deep_merge(base: &Value, over: &Value) -> Value {
    let mut out = match base {
        Value::Object(o) => o.clone(),
        _ => Map::new(),
    };
    if let Value::Object(over) = over {
        for (k, v) in over {
            let merged = match (v, out.get(k)) {
                (Value::Object(_), Some(b @ Value::Object(_))) => deep_merge(b, v),
                _ => v.clone(),
            };
            out.insert(k.clone(), merged);
        }
    }
    Value::Object(out)
}

#[derive(Debug)]
pub enum ZonesError {
    Json(serde_json::Error),
}

impl core::fmt::Display for ZonesError {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        match self {
            ZonesError::Json(e) => write!(f, "zones.json: {e}"),
        }
    }
}

impl From<serde_json::Error> for ZonesError {
    fn from(e: serde_json::Error) -> Self {
        ZonesError::Json(e)
    }
}

/// `sha256(text)[:12]`.
pub fn text_sha(text: &str) -> String {
    hex::encode(Sha256::digest(text.as_bytes()))[..12].to_string()
}

/// gate_core `parse_zones` as a JSON value (comments dropped, defaults merged, `_sha` added).
/// A leading BOM is the caller's to remove (Python reads with utf-8-sig).
pub fn parse_zones_value(text: &str, defaults: Option<&Value>) -> Result<Value, ZonesError> {
    let raw: Value = serde_json::from_str(text)?;
    let mut z = strip_comments(&raw);
    if let Some(d) = defaults.filter(|d| py::truthy(d)) {
        z = deep_merge(d, &z);
    }
    match &mut z {
        Value::Object(o) => {
            o.insert("_sha".into(), Value::String(text_sha(text)));
        }
        _ => return Err(ZonesError::Json(serde::de::Error::custom("zones.json is not an object"))),
    }
    Ok(z)
}

pub fn parse_zones(text: &str, defaults: Option<&Value>) -> Result<Zones, ZonesError> {
    Ok(Zones::from_value(parse_zones_value(text, defaults)?)?)
}

/// gate_core `load_zones(path, defaults_path)` with the file contents passed in (None = file missing).
pub fn load_zones_value(user_text: Option<&str>, defaults_text: Option<&str>) -> Result<Value, ZonesError> {
    let mut d = match defaults_text {
        Some(t) => parse_zones_value(t, None)?,
        None => Value::Object(Map::new()),
    };
    if let Value::Object(o) = &mut d {
        o.remove("_sha");
    }
    if let Some(u) = user_text {
        return parse_zones_value(u, Some(&d));
    }
    if let Value::Object(o) = &mut d {
        o.insert("_sha".into(), Value::String("default".into()));
    }
    Ok(d)
}

pub fn load_zones(user_text: Option<&str>, defaults_text: Option<&str>) -> Result<Zones, ZonesError> {
    Ok(Zones::from_value(load_zones_value(user_text, defaults_text)?)?)
}

fn rev(v: Option<&Value>) -> i64 {
    py::int_or_zero(v).unwrap_or(0)
}

fn list(v: Option<&Value>) -> &[Value] {
    match v {
        Some(Value::Array(a)) => a,
        _ => &[],
    }
}

/// gate_core `upgrade_zones(user, default)` on the raw files: new never groups (by name) are appended, his own
/// groups and settings are kept, bundled change notes newer than his revision are appended, revision is
/// bumped. Returns (zones, added names); names empty (and zones unchanged) when the default is not newer.
pub fn upgrade_zones(user: &Value, default: &Value) -> (Value, Vec<Option<String>>) {
    let ur = rev(user.get("revision"));
    let dr = rev(default.get("revision"));
    if dr <= ur {
        return (user.clone(), vec![]);
    }
    let mut out = user.as_object().cloned().unwrap_or_default();
    let name = |g: &Value| g.get("name").cloned().unwrap_or(Value::Null);
    let have: Vec<Value> = list(user.get("never")).iter().map(name).collect();
    let added: Vec<Value> = list(default.get("never")).iter().filter(|g| !have.contains(&name(g))).cloned().collect();
    let mut never: Vec<Value> = list(user.get("never")).to_vec();
    never.extend(added.iter().cloned());
    out.insert("never".into(), Value::Array(never));
    let mut changes: Vec<Value> = match user.get("_changes") {
        Some(v) if py::truthy(v) => list(Some(v)).to_vec(),
        _ => vec![],
    };
    for c in list(default.get("_changes")) {
        if c.is_object() && rev(c.get("revision")) > ur && !changes.contains(c) {
            changes.push(c.clone());
        }
    }
    out.insert("_changes".into(), Value::Array(changes));
    out.insert("revision".into(), Value::from(dr));
    let names = added.iter().map(|g| g.get("name").and_then(|n| n.as_str()).map(String::from)).collect();
    (Value::Object(out), names)
}
