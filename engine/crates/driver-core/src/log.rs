//! The gate.v1 process-data log: one record per action, shaped and masked as gate_core `log_entry` does
//! (typed text masked in secret fields, long text cut, never more than the reason needs).

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use std::collections::BTreeMap;

use crate::decide::Context;
use crate::py;
use crate::words::hit;

pub const SCHEMA: &str = "gate.v1";
pub const PASSWORD_WORDS: &[&str] =
    &["password", "passcode", "passphrase", "pin", "secret", "otp", "one-time code", "2fa", "security code", "cvv", "cvc"];

/// gate_core `looks_secret`.
pub fn looks_secret(element_name: &str, element_type: &str, is_password: bool) -> bool {
    is_password || hit(PASSWORD_WORDS, &[element_name]).is_some() || py::lower(element_type).contains("password")
}

/// gate_core `mask_text(text, secret, limit)` for text already turned into a string (`str(text or "")`).
pub fn mask_text(text: &str, secret: bool, limit: usize) -> String {
    let n = py::char_len(text);
    if secret {
        return format!("[masked {n} chars]");
    }
    if n <= limit {
        text.to_string()
    } else {
        format!("{}…(+{})", py::char_prefix(text, limit), n - limit)
    }
}

/// `mask_text(value, ...)` with Python's `str(value or "")`.
pub fn mask_value(v: Option<&Value>, secret: bool, limit: usize) -> String {
    mask_text(&py::str_or_empty(v), secret, limit)
}

fn ctx_secret(ctx: &Context) -> bool {
    looks_secret(
        ctx.element_name.as_deref().unwrap_or(""),
        &ctx.element_type.clone().unwrap_or_default(),
        py::truthy_opt(ctx.is_password.as_ref()),
    )
}

/// gate_core `clean_args`: typed text masked or cut to 80, notes to 200, any other string to 120.
pub fn clean_args(args: &Map<String, Value>, ctx: &Context) -> Map<String, Value> {
    let mut a = args.clone();
    let secret = ctx_secret(ctx);
    if a.contains_key("text") {
        let m = mask_value(a.get("text"), secret, 80);
        a.insert("text".into(), Value::String(m));
    }
    for k in ["texts", "items"] {
        if let Some(Value::Array(xs)) = a.get_mut(k) {
            for x in xs.iter_mut() {
                if let Value::String(s) = x {
                    *x = Value::String(mask_text(s, secret, 80));
                }
            }
        }
    }
    if a.contains_key("note") {
        let m = mask_value(a.get("note"), false, 200);
        a.insert("note".into(), Value::String(m));
    }
    for (k, v) in a.iter_mut() {
        if k != "text" && k != "note" {
            if let Value::String(s) = v {
                *v = Value::String(mask_text(s, false, 120));
            }
        }
    }
    a
}

/// gate_core `iso(t)`: UTC, milliseconds, "Z" (`datetime.fromtimestamp` rounds to microseconds half-even,
/// `isoformat(timespec="milliseconds")` then truncates).
pub fn iso(t: f64) -> String {
    let secs = t.floor();
    let frac = t - secs;
    let mut s = secs as i64;
    let us_f = frac * 1e6;
    let mut us = us_f.round() as i64;
    if us_f - us_f.trunc() == 0.5 && us % 2 == 1 {
        us -= 1; // Python's round(): half to even
    }
    if us >= 1_000_000 {
        s += 1;
        us -= 1_000_000;
    }
    let days = s.div_euclid(86_400);
    let sod = s.rem_euclid(86_400);
    let (y, m, d) = civil_from_days(days);
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:03}Z",
        y,
        m,
        d,
        sod / 3600,
        (sod % 3600) / 60,
        sod % 60,
        us / 1000
    )
}

/// Howard Hinnant's days -> (year, month, day).
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ElementRef {
    pub name: String,
    #[serde(rename = "type")]
    pub kind: String,
}

/// One gate.v1 action record, field for field as Python writes it to actions.jsonl.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ActionRecord {
    pub schema: String,
    pub kind: String,
    pub ts: String,
    pub session: String,
    pub tool: String,
    pub args: Map<String, Value>,
    pub app: String,
    pub title: String,
    pub element: ElementRef,
    pub zone: String,
    pub reason: String,
    pub decision: String,
    pub by: String,
    pub duration_ms: i64,
    pub ok: bool,
    pub zones_rev: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shot: Option<String>,
    /// `extra=` fields (Python `e.update(extra)`); must not reuse the names above.
    #[serde(flatten)]
    pub extra: BTreeMap<String, Value>,
}

/// The inputs of gate_core `log_entry`.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct LogInput {
    pub ts: f64,
    pub tool: String,
    #[serde(default)]
    pub args: Map<String, Value>,
    #[serde(default)]
    pub ctx: Context,
    pub zone: String,
    pub reason: String,
    pub decision: String,
    pub by: String,
    pub duration_ms: f64,
    pub ok: bool,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub shot: Option<String>,
    #[serde(default)]
    pub zones_rev: String,
    #[serde(default)]
    pub session: String,
    #[serde(default = "action_kind")]
    pub kind: String,
    #[serde(default)]
    pub extra: BTreeMap<String, Value>,
}

fn action_kind() -> String {
    "action".into()
}

/// gate_core `log_entry`.
pub fn log_entry(i: &LogInput) -> ActionRecord {
    let ctx = &i.ctx;
    ActionRecord {
        schema: SCHEMA.into(),
        kind: i.kind.clone(),
        ts: iso(i.ts),
        session: i.session.clone(),
        tool: i.tool.clone(),
        args: clean_args(&i.args, ctx),
        app: ctx.app.clone().unwrap_or_default(),
        title: mask_text(ctx.title.as_deref().unwrap_or(""), false, 80),
        element: ElementRef {
            name: mask_text(ctx.element_name.as_deref().unwrap_or(""), false, 80),
            kind: ctx.element_type.clone().unwrap_or_default(),
        },
        zone: i.zone.clone(),
        reason: i.reason.clone(),
        decision: i.decision.clone(),
        by: i.by.clone(),
        duration_ms: i.duration_ms.trunc() as i64,
        ok: i.ok,
        zones_rev: i.zones_rev.clone(),
        error: if i.error.is_empty() { None } else { Some(py::char_prefix(&i.error, 300).to_string()) },
        shot: i.shot.clone().filter(|s| !s.is_empty()),
        extra: i.extra.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn iso_like_python() {
        assert_eq!(iso(0.0), "1970-01-01T00:00:00.000Z");
        assert_eq!(iso(1763700000.1239), "2025-11-21T04:40:00.123Z");
        assert_eq!(iso(951782400.0), "2000-02-29T00:00:00.000Z");
    }
}
