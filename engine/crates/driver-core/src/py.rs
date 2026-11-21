//! The few bits of Python behaviour Gate's rules depend on, reproduced exactly: truthiness, `str()`,
//! `str.strip()` / `str.isspace()`, `str.lower()`, `str.splitlines()`, and `re`'s case-insensitive
//! character matching (simple lowercase plus the `re._casefix` extra cases).
//!
//! gate_core.py is the reference: when Rust and Python disagree, the parity vectors fail.

use serde_json::Value;

/// Python `str.isspace()` for one character (Unicode White_Space plus U+001C..U+001F, which Python counts
/// because their bidi class is B/S).
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// Python `str.strip()` with no argument.
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// Python `str.lower()` (full lowercase mapping, final sigma included).
pub fn lower(s: &str) -> String {
    s.to_lowercase()
}

/// The simple (one character) lowercase `re` uses (`_PyUnicode_ToLowercase`). Only U+0130 has a multi-char
/// full mapping (`i` + U+0307); its simple mapping is `i`, the first char of the full one.
pub fn simple_lower(c: char) -> char {
    c.to_lowercase().next().unwrap_or(c)
}

/// `re._casefix._EXTRA_CASES` (CPython 3.13): characters that also match under IGNORECASE although their
/// lowercase differs (e.g. `s` and U+017F, `i` and U+0131).
const EXTRA_CASES: &[(u32, &[u32])] = &[
    (105, &[305]), (115, &[383]), (181, &[956]), (305, &[105]), (383, &[115]), (837, &[953, 8126]),
    (912, &[8147]), (944, &[8163]), (946, &[976]), (949, &[1013]), (952, &[977]), (953, &[837, 8126]),
    (954, &[1008]), (956, &[181]), (960, &[982]), (961, &[1009]), (962, &[963]), (963, &[962]),
    (966, &[981]), (976, &[946]), (977, &[952]), (981, &[966]), (982, &[960]), (1008, &[954]),
    (1009, &[961]), (1013, &[949]), (1074, &[7296]), (1076, &[7297]), (1086, &[7298]), (1089, &[7299]),
    (1090, &[7300, 7301]), (1098, &[7302]), (1123, &[7303]), (7296, &[1074]), (7297, &[1076]),
    (7298, &[1086]), (7299, &[1089]), (7300, &[1090, 7301]), (7301, &[1090, 7300]), (7302, &[1098]),
    (7303, &[1123]), (7304, &[42571]), (7777, &[7835]), (7835, &[7777]), (8126, &[837, 953]),
    (8147, &[912]), (8163, &[944]), (42571, &[7304]), (64261, &[64262]), (64262, &[64261]),
];

pub(crate) fn extra_cases(c: char) -> &'static [u32] {
    let k = c as u32;
    EXTRA_CASES.binary_search_by_key(&k, |(a, _)| *a).map(|i| EXTRA_CASES[i].1).unwrap_or(&[])
}

/// Does text character `t` match pattern character `p` under `re.IGNORECASE` (str pattern)?
/// `p` is already lowered, as `re`'s compiler stores it.
pub fn ci_eq(t: char, p: char) -> bool {
    let p = simple_lower(p);
    let l = simple_lower(t);
    if l == p {
        return true;
    }
    let lp = p as u32;
    extra_cases(p).contains(&(l as u32)) || (t as u32 == lp)
}

/// `[a-z0-9]` under `re.IGNORECASE`: `re` tests the lowercased char against {a-z, 0-9} plus the extra cases
/// of its members (U+0131 for i, U+017F for s). So A-Z, U+0130 (lowers to i) and U+212A Kelvin (lowers to k)
/// count as word characters too.
pub fn is_word_class(c: char) -> bool {
    let l = simple_lower(c);
    l.is_ascii_lowercase() || l.is_ascii_digit() || l == '\u{131}' || l == '\u{17f}'
}

/// Python `str.splitlines()` (no keepends): splits on \n, \r, \r\n, \v, \f, \x1c, \x1d, \x1e, \x85,
/// U+2028, U+2029; a final line break adds no empty line.
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = s.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        let brk = matches!(c, '\n' | '\r' | '\u{b}' | '\u{c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}');
        if brk {
            out.push(&s[start..i]);
            let mut end = i + c.len_utf8();
            if c == '\r' {
                if let Some(&(j, '\n')) = it.peek() {
                    it.next();
                    end = j + 1;
                }
            }
            start = end;
        }
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

/// Python truthiness of a JSON value.
pub fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

pub fn truthy_opt(v: Option<&Value>) -> bool {
    v.map(truthy).unwrap_or(false)
}

/// Python `repr(float)` for the values JSON can carry (shortest round-trip digits; `1.0`, `1e+16`, `1e-05`).
pub fn float_repr(f: f64) -> String {
    if f.is_nan() {
        return "nan".into();
    }
    if f.is_infinite() {
        return if f > 0.0 { "inf".into() } else { "-inf".into() };
    }
    // Rust's `{:e}` gives the shortest round-trip digits as d.ddde±x
    let e = format!("{:e}", f);
    let (mant, exp) = e.split_once('e').unwrap();
    let exp: i32 = exp.parse().unwrap();
    let neg = mant.starts_with('-');
    let digits: String = mant.chars().filter(|c| c.is_ascii_digit()).collect();
    let sign = if neg { "-" } else { "" };
    if (-4..16).contains(&exp) {
        // positional
        let n = digits.len() as i32;
        let s = if exp >= 0 {
            if n <= exp + 1 {
                format!("{}{}.0", digits, "0".repeat((exp + 1 - n) as usize))
            } else {
                format!("{}.{}", &digits[..(exp + 1) as usize], &digits[(exp + 1) as usize..])
            }
        } else {
            format!("0.{}{}", "0".repeat((-exp - 1) as usize), digits)
        };
        format!("{sign}{s}")
    } else {
        let m = if digits.len() > 1 { format!("{}.{}", &digits[..1], &digits[1..]) } else { digits.clone() };
        format!("{sign}{m}e{}{:02}", if exp < 0 { '-' } else { '+' }, exp.abs())
    }
}

/// Python `str(v)` for a JSON value. Strings, None, bools and numbers are exact; lists and dicts use Python's
/// repr layout for strings with no quotes or escapes inside (enough for the log; Gate never decides on them).
pub fn to_str(v: &Value) -> String {
    match v {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                i.to_string()
            } else if let Some(u) = n.as_u64() {
                u.to_string()
            } else {
                float_repr(n.as_f64().unwrap_or(0.0))
            }
        }
        Value::String(s) => s.clone(),
        Value::Array(a) => format!("[{}]", a.iter().map(repr).collect::<Vec<_>>().join(", ")),
        Value::Object(o) => format!(
            "{{{}}}",
            o.iter().map(|(k, v)| format!("'{}': {}", k, repr(v))).collect::<Vec<_>>().join(", ")
        ),
    }
}

fn repr(v: &Value) -> String {
    match v {
        Value::String(s) => format!("'{}'", s),
        other => to_str(other),
    }
}

/// Python `str(v or "")`.
pub fn str_or_empty(v: Option<&Value>) -> String {
    match v {
        Some(v) if truthy(v) => to_str(v),
        _ => String::new(),
    }
}

/// Python `int(v)` for JSON values: bools, ints, floats (truncated) and strings of an integer (surrounding
/// whitespace, sign and `_` between digits allowed). `None` where Python would raise.
pub fn to_int(v: &Value) -> Option<i64> {
    match v {
        Value::Bool(b) => Some(*b as i64),
        Value::Number(n) => n.as_i64().or_else(|| n.as_f64().filter(|f| f.is_finite()).map(|f| f.trunc() as i64)),
        Value::String(s) => {
            let t = strip(s);
            let (neg, body) = match t.as_bytes().first() {
                Some(b'-') => (true, &t[1..]),
                Some(b'+') => (false, &t[1..]),
                _ => (false, t),
            };
            if body.is_empty() || body.starts_with('_') || body.ends_with('_') || body.contains("__") {
                return None;
            }
            let digits: String = body.chars().filter(|c| *c != '_').collect();
            if !digits.chars().all(|c| c.is_ascii_digit()) {
                return None;
            }
            digits.parse::<i64>().ok().map(|n| if neg { -n } else { n })
        }
        _ => None,
    }
}

/// Python `int(v or 0)`.
pub fn int_or_zero(v: Option<&Value>) -> Option<i64> {
    match v {
        Some(v) if truthy(v) => to_int(v),
        _ => Some(0),
    }
}

/// gate_core `_truthy`: `v is True or str(v).strip().lower() in ("true", "1", "yes")`. A missing key is None.
pub fn flag(v: Option<&Value>) -> bool {
    match v {
        Some(Value::Bool(true)) => true,
        Some(v) => matches!(lower(strip(&to_str(v))).as_str(), "true" | "1" | "yes"),
        None => false,
    }
}

/// Python `s[:n]` / `len(s)` work on code points.
pub fn char_len(s: &str) -> usize {
    s.chars().count()
}

pub fn char_prefix(s: &str, n: usize) -> &str {
    match s.char_indices().nth(n) {
        Some((i, _)) => &s[..i],
        None => s,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn floats_print_like_python() {
        for (f, s) in [(1.0, "1.0"), (0.5, "0.5"), (1e16, "1e+16"), (1e-5, "1e-05"), (123.456, "123.456"), (0.0001, "0.0001"), (-2.5, "-2.5")] {
            assert_eq!(float_repr(f), s);
        }
    }

    #[test]
    fn splitlines_like_python() {
        assert_eq!(splitlines("a\r\nb\rc\n"), ["a", "b", "c"]);
        assert_eq!(splitlines(""), Vec::<&str>::new());
        assert_eq!(splitlines("a\n\nb\u{2028}"), ["a", "", "b"]);
    }

    #[test]
    fn ints_like_python() {
        assert_eq!(to_int(&json!(" 1_0 ")), Some(10));
        assert_eq!(to_int(&json!("2.5")), None);
        assert_eq!(to_int(&json!(2.9)), Some(2));
        assert_eq!(int_or_zero(Some(&json!(null))), Some(0));
    }
}
