//! The trust zone for one request, before it is forwarded: gate_core `decide()`, rule for rule and in the
//! same order, with the same reason texts (the log and the popup show them).

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::py;
use crate::words::hit;
use crate::zones::{NeverGroup, Zones};

/// Windows-MCP 0.8.9 UI tools Gate exposes (an allowlist: anything else is hidden).
pub const UI_TOOLS: &[&str] = &[
    "Snapshot", "Screenshot", "Click", "Type", "Scroll", "Move", "Shortcut", "Wait", "WaitFor", "App", "ControlStatus",
];
pub const GATE_TOOLS: &[&str] = &["capture_view", "gate_status"];
pub const INPUT_TOOLS: &[&str] = &["Click", "Type", "Scroll", "Move", "Shortcut"];
pub const READ_TOOLS: &[&str] = &["Snapshot", "Screenshot"];
pub const PASSIVE_TOOLS: &[&str] = &["Wait", "WaitFor", "ControlStatus"];

/// Arguments Gate never forwards (they make Windows-MCP write files).
pub fn stripped_args(tool: &str) -> &'static [&'static str] {
    match tool {
        "Snapshot" | "Screenshot" => &["save_path"],
        _ => &[],
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Zone {
    /// Not a UI tool: never exposed.
    Hidden,
    /// Bad arguments: refused.
    Invalid,
    Never,
    Confirm,
    Auto,
}

impl Zone {
    pub fn as_str(&self) -> &'static str {
        match self {
            Zone::Hidden => "hidden",
            Zone::Invalid => "invalid",
            Zone::Never => "never",
            Zone::Confirm => "confirm",
            Zone::Auto => "auto",
        }
    }
}

/// `{"tool": "Click", "args": {...}}`
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Action {
    #[serde(default)]
    pub tool: String,
    #[serde(default, deserialize_with = "obj_or_empty")]
    pub args: Map<String, Value>,
}

fn obj_or_empty<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Map<String, Value>, D::Error> {
    Ok(match Option::<Value>::deserialize(d)? {
        Some(Value::Object(o)) => o,
        _ => Map::new(),
    })
}

/// What Gate knows about the screen when the request arrives (gate_win fills it on Windows).
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Context {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub app: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub element_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub element_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub is_password: Option<Value>,
    /// The Settings page header (for the Settings > Accounts/Privacy rule).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub page_hint: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub paused: Option<Value>,
    /// `{"element_name": "...", "ts": float}`: what was typed into last (for Enter after typing).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub last_typed: Option<Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub now: Option<f64>,
    /// For App switch/launch: the window being asked for.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_app: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_title: Option<String>,
}

fn s(o: &Option<String>) -> &str {
    o.as_deref().unwrap_or("")
}

/// gate_core `_proc`: lowercase, stripped, without `.exe`.
pub fn proc_name(name: &str) -> String {
    let n = py::lower(py::strip(name));
    match n.strip_suffix(".exe") {
        Some(b) => b.to_string(),
        None => n,
    }
}

/// gate_core `_in_procs`.
pub fn in_procs(app: &str, procs: &[String]) -> bool {
    let a = proc_name(app);
    !a.is_empty() && procs.iter().any(|p| proc_name(p) == a)
}

/// gate_core `_app_on_list`.
pub fn app_on_list(name: &str, apps: &[String]) -> bool {
    in_procs(name, apps)
}

/// gate_core `norm_keys`: "Ctrl + Del" -> ["ctrl", "delete"].
pub fn norm_keys(shortcut: &str) -> Vec<String> {
    shortcut
        .split('+')
        .map(py::strip)
        .filter(|p| !p.is_empty())
        .map(|p| {
            let p = py::lower(p);
            match p.as_str() {
                "del" => "delete".to_string(),
                "return" => "enter".to_string(),
                "control" => "ctrl".to_string(),
                "windows" => "win".to_string(),
                "escape" => "esc".to_string(),
                _ => p,
            }
        })
        .collect()
}

/// gate_core `_never`: the reason if the window/element is in a never group.
pub fn never_reason(groups: &[NeverGroup], app: &str, title: &str, element: &str, hints: &[&str], input_action: bool) -> Option<String> {
    for g in groups {
        if g.input_only() && !input_action {
            continue;
        }
        let label = g.label();
        if in_procs(app, &g.processes) {
            return Some(format!("{label}: app {app}"));
        }
        if let Some(w) = hit(&g.title_words, &[title]) {
            return Some(format!("{label}: window title has '{w}'"));
        }
        if let Some(w) = hit(&g.element_words, &[element]) {
            return Some(format!("{label}: element named '{w}'"));
        }
        if !g.only_in_processes.is_empty() && in_procs(app, &g.only_in_processes) {
            let mut texts = vec![title, element];
            texts.extend_from_slice(hints);
            if let Some(w) = hit(&g.scoped_words, &texts) {
                return Some(format!("{label}: '{w}'"));
            }
        }
    }
    None
}

fn has(list: &[&str], x: &str) -> bool {
    list.contains(&x)
}

const GATE_WINDOW: &str = "a Nodach Gate window (Claude can't answer Gate's own prompts)";

/// gate_core `decide(action, context, zones)` -> (zone, reason).
pub fn decide(action: &Action, ctx: &Context, zones: &Zones) -> (Zone, String) {
    let tool = action.tool.as_str();
    let args = &action.args;
    let r = |z: Zone, why: String| (z, why);
    if !has(UI_TOOLS, tool) && !has(GATE_TOOLS, tool) {
        return r(Zone::Hidden, format!("{tool} is not a UI tool; Gate never exposes it"));
    }
    if has(GATE_TOOLS, tool) {
        return r(Zone::Auto, "Gate's own tool".into());
    }
    if py::truthy_opt(ctx.paused.as_ref()) {
        return r(Zone::Never, "Gate is paused (Pause all is on in the Gate window)".into());
    }
    if has(PASSIVE_TOOLS, tool) {
        return r(Zone::Auto, "passive".into());
    }
    if args.get("label").map(|v| !v.is_null()).unwrap_or(false) && has(INPUT_TOOLS, tool) {
        return r(
            Zone::Invalid,
            "Gate needs loc=[x, y] (the centre shown in Snapshot), not a label, so it can check the element there".into(),
        );
    }
    for k in stripped_args(tool) {
        if py::truthy_opt(args.get(*k)) {
            return r(Zone::Invalid, format!("{tool} {k} writes a file; Gate doesn't forward file writes (leave {k} out)"));
        }
    }

    let app = s(&ctx.app);
    let title = s(&ctx.title);
    let el = s(&ctx.element_name);
    let hints = [s(&ctx.page_hint)];

    // Gate's own windows: never clicked or typed into; reading and opening other apps stay allowed.
    let gate_titles = zones.gate_titles();
    if tool == "App" {
        let target = py::str_or_empty(args.get("name"));
        if hit(&gate_titles, &[&target, s(&ctx.target_title)]).is_some() {
            return r(Zone::Never, GATE_WINDOW.into());
        }
    } else if !has(READ_TOOLS, tool) && hit(&gate_titles, &[title]).is_some() {
        return r(Zone::Never, GATE_WINDOW.into());
    }

    if tool == "App" {
        let mode = match args.get("mode") {
            Some(v) if py::truthy(v) => py::lower(&py::to_str(v)),
            _ => "launch".to_string(),
        };
        if mode == "launch_executable" {
            return r(
                Zone::Never,
                "App launch_executable runs any program with arguments (a shell route); use launch by name".into(),
            );
        }
        let target = py::str_or_empty(args.get("name"));
        let t_app = ctx.target_app.as_deref().filter(|x| !x.is_empty()).unwrap_or(&target);
        let t_title = ctx.target_title.as_deref().filter(|x| !x.is_empty()).unwrap_or(&target);
        if let Some(why) = never_reason(&zones.never, t_app, t_title, &target, &hints, true) {
            return r(Zone::Never, why);
        }
        if mode == "launch" {
            if hit(&zones.shell_apps.names, &[&target]).is_some() || in_procs(&target, &zones.shell_apps.processes) {
                return r(Zone::Never, format!("launching a shell or system editor ('{target}') is a shell route"));
            }
            if !app_on_list(&target, &zones.auto_apps) {
                return r(Zone::Confirm, format!("launch '{target}': not on your auto list"));
            }
        }
        return r(Zone::Auto, format!("App {mode}"));
    }

    if let Some(why) = never_reason(&zones.never, app, title, el, &hints, has(INPUT_TOOLS, tool)) {
        return r(Zone::Never, why);
    }
    if has(READ_TOOLS, tool) {
        return r(Zone::Auto, "read".into());
    }

    let cw = &zones.confirm;
    let keys = if tool == "Shortcut" { norm_keys(&py::str_or_empty(args.get("shortcut"))) } else { vec![] };

    if tool == "Shortcut" {
        for combo in &cw.key_combos {
            let mut want = norm_keys(combo);
            want.sort();
            want.dedup();
            let subset = want.iter().all(|k| keys.contains(k));
            if !want.is_empty() && subset && (want.len() > 1 || keys.len() == 1 || want.iter().any(|k| k == "delete")) {
                return r(Zone::Confirm, format!("key combo {}", keys.join("+")));
            }
        }
    }
    if tool == "Click" {
        // int(args.get("clicks", 1) or 0) == 0; a value Python's int() refuses is not a hover.
        let clicks = match args.get("clicks") {
            None => Some(1),
            v => py::int_or_zero(v),
        };
        if clicks == Some(0) {
            return r(Zone::Auto, "hover".into());
        }
    }
    let last_enter_or_space = keys.last().map(|k| k == "enter" || k == "space").unwrap_or(false);
    if (matches!(tool, "Click" | "Shortcut" | "Type")
        || (tool == "Move" && py::flag(args.get("drag")))
        || py::truthy_opt(args.get("from_loc")))
        && (tool != "Shortcut" || last_enter_or_space) {
            if let Some(w) = hit(&cw.element_words, &[el]) {
                if !(tool == "Type" && !py::flag(args.get("press_enter"))) {
                    return r(Zone::Confirm, format!("{} on an element named like '{w}'", py::lower(tool)));
                }
            }
        }
    // Enter after typing into a message/comment/reply box
    let enter = (tool == "Type" && py::flag(args.get("press_enter")))
        || (tool == "Shortcut" && keys.last().map(|k| k == "enter").unwrap_or(false));
    if enter {
        let lt = ctx.last_typed.as_ref().filter(|v| py::truthy(v));
        let fresh = match lt {
            None => false,
            Some(lt) => {
                let ts = lt.get("ts").filter(|v| !v.is_null());
                match (ctx.now, ts) {
                    (None, _) | (_, None) => true,
                    (Some(now), Some(ts)) => ts.as_f64().map(|t| now - t <= 300.0).unwrap_or(false),
                }
            }
        };
        let typed_into = if tool == "Type" {
            el.to_string()
        } else {
            let from_lt = if fresh { py::str_or_empty(lt.and_then(|l| l.get("element_name"))) } else { String::new() };
            if from_lt.is_empty() { el.to_string() } else { from_lt }
        };
        if let Some(w) = hit(&cw.enter_after_typing_words, &[&typed_into]) {
            return r(Zone::Confirm, format!("Enter after typing into '{w}' (sends it)"));
        }
    }
    if tool == "Type" && py::truthy_opt(ctx.is_password.as_ref()) {
        return r(Zone::Confirm, "typing into a password field".into());
    }
    if has(INPUT_TOOLS, tool) && in_procs(app, &zones.shell_apps.processes) {
        return r(Zone::Confirm, format!("input into a shell window ({app})"));
    }
    for g in &zones.confirm_apps {
        if has(INPUT_TOOLS, tool) && tool != "Scroll" && in_procs(app, &g.processes) {
            return r(Zone::Confirm, format!("{}: {app}", g.name.as_deref().unwrap_or("confirm app")));
        }
    }
    r(Zone::Auto, "no rule matched".into())
}
