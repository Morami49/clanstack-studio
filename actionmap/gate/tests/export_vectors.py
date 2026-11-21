"""Parity vectors for the Rust Driver core (engine/crates/driver-core): runs gate_core over a broad set of cases
and writes engine/crates/driver-core/tests/vectors/*.json. The Rust test tests/parity.rs must give identical
outputs for every vector.

    python actionmap/gate/tests/export_vectors.py           # rewrite the vectors
    python actionmap/gate/tests/export_vectors.py --check   # exit 1 if they differ from the committed ones (CI)

Cases: everything the pytest suite checks, plus edge cases (word boundaries with _ - . and digits, Unicode
titles and case folding, empty and null fields, odd argument types). A case where Python raises is left out
(Rust has to answer something; see "Known differences" in engine/crates/driver-core/src/lib.rs) and counted in the summary line.
Output is deterministic (sorted keys, one case per line), so CI can compare bytes.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[1]
ROOT = GATE.parents[1]
OUT = ROOT / "engine" / "crates" / "driver-core" / "tests" / "vectors"
sys.path.insert(0, str(GATE))
import gate_core as core  # noqa: E402

SKIPPED = {"python_raises": 0}


def call(fn, *a, **k):
    try:
        return True, fn(*a, **k)
    except Exception:  # noqa: BLE001  (a case Python can't answer is not a vector)
        SKIPPED["python_raises"] += 1
        return False, None


# ------------------------------------------------------------------ zone sets
RAW = json.loads((GATE / "zones.json").read_text(encoding="utf-8"))
DEFAULT = core.load_zones(None)
CUSTOM = {
    "revision": "4",
    "never": [
        {"name": "input only", "applies_to": "input", "processes": ["Vault.EXE", " keeper "], "title_words": ["vault"], "element_words": []},
        {"name": "scoped", "processes": [], "title_words": [], "only_in_processes": ["SystemSettings", "control.exe"],
         "scoped_words": ["Accounts", "Privacy & security"]},
        {"title_words": ["my_secret", "a-b", "v1.2", "x.y_z", "ΣΟΦΙΑ", "straße", "İstanbul", "kek", "s", "Ωmega"],
         "element_words": ["Ünïcode"], "redact_elements": True},
        {"name": "elem", "element_words": ["card number", "pin"], "title_words": ["token"], "redact_elements": "yes"},
        {"name": "nullish", "processes": None, "title_words": [None, "", "zz top"], "applies_to": None},
        {"name": "Odd: name", "processes": ["odd"], "title_words": ["odd title"]},
    ],
    "gate_titles": ["Gate Window", "Nodach Gate"],
    "shell_apps": {"processes": ["bash.exe", "pwsh"], "names": ["Terminal", "Power Shell"]},
    "confirm": {"element_words": ["send", "pay now", "pay", "ok"], "enter_after_typing_words": ["message", "chat", "Σχόλιο"],
                "key_combos": ["ctrl+shift+delete", "delete", "alt+f4", "", "win + l"]},
    "confirm_apps": [{"name": "Settings", "processes": ["SystemSettings"]}, {"processes": ["regedit"]}],
    "auto_apps": ["Notepad", "code.exe", " Paint "],
}
MINIMAL = {"gate_titles": [], "never": []}
EMPTY = {}
ZONES = {"default": DEFAULT, "raw": RAW, "custom": CUSTOM, "minimal": MINIMAL, "empty": EMPTY}


# ------------------------------------------------------------------ words
def words_vectors():
    word_lists = [
        ["send"], ["pay", "pay now"], ["pay now", "pay"], ["password", "passwords"], [".env"], ["a-b"], ["2fa"], ["kek"],
        ["straße"], ["ΣΟΦΙΑ"], ["İstanbul"], ["istanbul"], ["s"], ["i"], ["_x"], ["v1.2"], ["recovery codes"], [""], [],
        ["µ"], ["ﬅ"], ["Ωmega"], ["x", "xy"], ["σ"], ["k"],
    ]
    texts = [
        "", "Send", "SEND now", "Sender", "resend", "send_it", "send-it", "send.it", "send2", "2send", "x send x",
        "pay now please", "paynow", "pay  now", "Pay Now", "my passwords.txt", "password1", "1password", "PASSWORD",
        "prod .env", "x.env", ".env", ".envrc", "a-b", "aa-b", "a-bb", "a-b-c", "2fa", "12fa", "2FA!", "2fa_code",
        "KEK", "\u212aek", "kek\u212a", "STRASSE", "Straße", "straẞe", "σοφια", "ΣΟΦΙΑ", "σοφιας", "ﬆοφια",
        "İSTANBUL", "istanbul", "ıstanbul", "Istanbul", "\u017f", "S", "ſ", "is", "ı", "İ", "I", "_x", "a_x", "-_x",
        "v1.2", "v1.2.3", "v1.20", "av1.2", "recovery codes", "Recovery  Codes", "recovery-codes", "µ", "μ", "Μ",
        "ﬅ", "ﬆ", "ωmega", "ΩMEGA", "Ωmega2", "xy", "x y", "ς", "Σ", "k", "K", "\u212a", "日本語 send 日本語",
        "send\u00a0x", "émail send", "éSend", "send\u0301",
    ]
    out = []
    for ws in word_lists:
        for t in texts:
            out.append({"words": ws, "texts": [t], "hit": core._hit(ws, t)})
        out.append({"words": ws, "texts": ["", "nothing", "Send pay a-b"], "hit": core._hit(ws, "", "nothing", "Send pay a-b")})
    return out


# ------------------------------------------------------------------ decide
def contexts():
    base = [
        {},
        {"app": None, "title": None, "element_name": None},
        {"app": "", "title": "", "element_name": ""},
        {"app": "notepad.exe", "title": "Untitled - Notepad", "element_name": "Text editor"},
        {"app": "Bitwarden.exe", "title": "Vault - Bitwarden", "element_name": "Copy"},
        {"app": "KeePassXC.exe", "title": "db.kdbx"},
        {"app": "chrome.exe", "title": "Barclays Online Banking - Google Chrome"},
        {"app": "msedge.exe", "title": "Checkout - Shop"},
        {"app": "chrome.exe", "title": "Shop", "element_name": "Card number"},
        {"app": "chrome.exe", "title": "Bankside Gallery tickets", "element_name": "x"},
        {"app": "consent.exe", "title": "User Account Control"},
        {"app": "SecHealthUI.exe", "title": "Windows Security"},
        {"app": "SystemSettings.exe", "title": "Settings", "element_name": "Accounts"},
        {"app": "SystemSettings.exe", "title": "Settings", "element_name": "Toggle", "page_hint": "Privacy & security / Location"},
        {"app": "SystemSettings.exe", "title": "Settings", "element_name": "Bluetooth"},
        {"app": "SystemSettings", "title": "Settings", "element_name": "Display", "page_hint": None},
        {"app": "OUTLOOK.EXE", "title": "Inbox", "element_name": "Send", "element_type": "Button"},
        {"app": "x.exe", "element_name": "Buy now"},
        {"app": "x.exe", "element_name": "Sign out"},
        {"app": "x.exe", "element_name": "Pay"},
        {"app": "chrome.exe", "title": "Form", "element_name": "Postcode"},
        {"app": "chrome.exe", "title": "Form", "element_name": "Sender name"},
        {"app": "ms-teams.exe", "element_name": "Type a message"},
        {"app": "chrome.exe", "title": "YouTube", "last_typed": {"element_name": "Write a comment", "ts": 0}},
        {"app": "chrome.exe", "title": "YouTube", "last_typed": {"element_name": "Write a comment", "ts": 0}, "now": 1000},
        {"app": "chrome.exe", "title": "YouTube", "last_typed": {"element_name": "Write a comment", "ts": 700}, "now": 1000},
        {"app": "chrome.exe", "title": "YouTube", "last_typed": {"element_name": "Write a comment", "ts": 699.5}, "now": 1000},
        {"app": "chrome.exe", "title": "Mail", "last_typed": {"element_name": "Message body"}},
        {"app": "chrome.exe", "title": "Mail", "last_typed": {}, "element_name": "chat box"},
        {"app": "chrome.exe", "title": "Mail", "last_typed": None, "element_name": "Reply"},
        {"app": "chrome.exe", "title": "Mail", "last_typed": {"element_name": None, "ts": None}, "element_name": "Compose", "now": 5},
        {"app": "chrome.exe", "title": "Mail", "last_typed": {"element_name": "", "ts": 1}, "element_name": "Search", "now": 2},
        {"app": "explorer.exe", "title": "Downloads"},
        {"app": "claude.exe", "title": "Claude", "element_name": "Allow"},
        {"app": "Claude", "title": "Claude"},
        {"app": "pythonw.exe", "title": "Nodach Gate — confirm", "element_name": "Allow once"},
        {"app": "pythonw.exe", "title": "Nodach Gate"},
        {"app": "pythonw.exe", "title": "nodach gate"},
        {"app": "pythonw.exe", "title": "Nodach Gateway"},
        {"app": "WindowsTerminal.exe", "title": "PowerShell"},
        {"app": "bash.exe", "title": "MINGW64"},
        {"app": "pwsh", "title": "x"},
        {"app": "regedit.exe", "title": "Registry Editor", "element_name": "OK"},
        {"app": "chrome.exe", "title": "Login", "element_name": "Password", "is_password": True},
        {"app": "chrome.exe", "title": "Login", "element_name": "Field", "is_password": 1},
        {"app": "chrome.exe", "title": "Login", "element_name": "Field", "is_password": ""},
        {"app": "chrome.exe", "title": "Login", "element_name": "Field", "is_password": "false"},
        {"app": "Notepad.exe", "title": "github-recovery-codes.txt - Notepad"},
        {"app": "Notepad.exe", "title": "notes_recovery_codes.txt - Notepad"},
        {"app": "Notepad.exe", "title": "prod .env - Notepad"},
        {"app": "Notepad.exe", "title": "x.env - Notepad"},
        {"app": "Code.exe", "title": "seed_phrase.md - Visual Studio Code"},
        {"app": "Code.exe", "title": "seedling.md - Visual Studio Code"},
        {"app": "explorer.exe", "title": "C:\\Users\\x\\Desktop\\Nodach\\nodach_sec - File Explorer"},
        {"app": "explorer.exe", "title": "client_secret_123.json", "element_name": "Open"},
        {"app": "notepad.exe", "title": "my_secret.txt", "element_name": "Ünïcode field"},
        {"app": "notepad.exe", "title": "ΣΟΦΙΑ.txt — σοφια", "element_name": "ÜNÏCODE"},
        {"app": "notepad.exe", "title": "STRASSE und straße", "element_name": "x"},
        {"app": "notepad.exe", "title": "\u212aEK.txt"},
        {"app": "notepad.exe", "title": "İSTANBUL", "element_name": "s"},
        {"app": "notepad.exe", "title": "v1.2.txt a-b x.y_z"},
        {"app": "notepad.exe", "title": "日本語のメモ", "element_name": "送信"},
        {"app": "Vault.exe", "title": "Vault", "element_name": "OK"},
        {"app": "keeper.exe", "title": "x"},
        {"app": "odd.exe", "title": "odd title", "element_name": "token"},
        {"app": "control.exe", "title": "Control Panel", "element_name": "x", "page_hint": "User Accounts"},
        {"app": "control.exe", "title": "Control Panel", "page_hint": "Accounts"},
        {"app": " NOTEPAD.EXE ", "title": "zz top", "element_name": "PIN"},
        {"app": "notepad.exe.exe", "title": "x"},
        {"app": "x.exe", "paused": True},
        {"app": "x.exe", "paused": "no"},
        {"app": "x.exe", "paused": 0},
        {"app": "x.exe", "paused": ""},
    ]
    return base


APP_CONTEXTS = [
    {}, {"app": "Claude.exe"}, {"app": "pythonw.exe", "title": "Nodach Gate"},
    {"target_app": "Bitwarden.exe", "target_title": "Bitwarden"},
    {"target_app": "notepad", "target_title": "Notepad"},
    {"target_app": "", "target_title": ""},
    {"target_app": None, "target_title": "Barclays - Edge"},
    {"target_title": "Nodach Gate"},
    {"target_app": "SystemSettings.exe", "target_title": "Settings", "page_hint": "Accounts"},
    {"target_app": "SystemSettings.exe", "target_title": "Settings", "page_hint": "Bluetooth"},
    {"app": "Claude.exe", "paused": True},
    {"target_app": "Vault.exe", "target_title": "Vault"},
]

SHORTCUTS = ["enter", "Enter", "ctrl+enter", "shift + delete", "shift+delete", "Del", "delete", "ctrl+c", "ctrl+shift+delete",
             "shift+ctrl+delete", "alt+f4", "alt + F4", "space", "ctrl+space", "Return", "delete+delete", "+", "", None, 5,
             "ctrl++enter", "\u00a0enter\u00a0", "\x1center", "win+l", "Windows + L", "ctrl+del", "escape", "CONTROL+Return"]

APP_NAMES = ["Notepad", "notepad.exe", " NOTEPAD.EXE ", "Paint", "Steam", "PowerShell", "Windows PowerShell", "Windows Terminal",
             "wt", "cmd.exe", "bash", "Power Shell", "Terminal", "Bitwarden", "Nodach Gate", "Gate Window", "", None, 5,
             "Settings", "Barclays", "Code", "Vault", "my_secret notes"]
APP_MODES = ["launch", "switch", "resize", "LAUNCH", "launch_executable", "Launch_Executable", None, "", "MISSING"]


def actions():
    acts = []
    for a in [{}, {"loc": [1, 1]}, {"loc": [1, 1], "clicks": 0}, {"clicks": None}, {"clicks": "0"}, {"clicks": " 2 "},
              {"clicks": 2}, {"clicks": 0.5}, {"clicks": False}, {"clicks": True}, {"clicks": "2.5"}, {"label": 3},
              {"label": None}, {"label": 0}, {"from_loc": [1, 1]}, {"from_loc": []}, {"loc": [1, 1], "button": "right"}]:
        acts.append({"tool": "Click", "args": a})
    for a in [{"text": "hi"}, {"text": "hi", "press_enter": True}, {"press_enter": "yes"}, {"press_enter": "1"},
              {"press_enter": 1}, {"press_enter": "no"}, {"press_enter": 1.0}, {"press_enter": " TRUE "}, {"label": "x"},
              {"press_enter": None}]:
        acts.append({"tool": "Type", "args": a})
    for sc in SHORTCUTS:
        acts.append({"tool": "Shortcut", "args": {"shortcut": sc}})
    acts.append({"tool": "Shortcut", "args": {}})
    acts.append({"tool": "Shortcut", "args": {"shortcut": "enter", "label": 1}})
    for a in [{}, {"from_loc": [1, 2]}, {"label": 1}, {"loc": [1, 1], "direction": "down"}]:
        acts.append({"tool": "Scroll", "args": a})
    for a in [{"drag": True}, {"drag": "true"}, {"drag": "Yes"}, {"drag": False}, {"from_loc": [0, 0]}, {}, {"drag": 1}]:
        acts.append({"tool": "Move", "args": a})
    for t in ("Snapshot", "Screenshot"):
        for a in [{}, {"save_path": "C:/x.png"}, {"save_path": ""}, {"use_vision": True}, {"label": 1}]:
            acts.append({"tool": t, "args": a})
    for t in ("Wait", "WaitFor", "ControlStatus", "capture_view", "gate_status", "PowerShell", "FileSystem", "Registry",
              "Process", "Clipboard", "Scrape", "MultiEdit", "BrandNewTool", "", "click", "snapshot"):
        acts.append({"tool": t, "args": {}})
    acts.append({"tool": "Wait", "args": {"duration": 1}})
    acts.append({"tool": "PowerShell", "args": {"command": "rm -r C:/"}})
    acts.append({"tool": "Click", "args": None})
    return acts


def app_actions():
    acts = []
    for mode, name in itertools.product(APP_MODES, APP_NAMES):
        a = {} if mode == "MISSING" else {"mode": mode}
        a["name"] = name
        acts.append({"tool": "App", "args": a})
    acts.append({"tool": "App", "args": {"mode": "launch_executable", "executable": "C:/x.exe"}})
    acts.append({"tool": "App", "args": {}})
    acts.append({"tool": "App", "args": {"mode": "launch", "label": 1}})
    return acts


def decide_vectors():
    ctxs, acts, reasons, cases = [], [], [], []
    ctx_ix, act_ix, why_ix = {}, {}, {}

    def ix(table, index, obj):
        k = json.dumps(obj, sort_keys=True)
        if k not in index:
            index[k] = len(table)
            table.append(obj)
        return index[k]

    plan = [(acts_, ctxs_) for acts_, ctxs_ in ((actions(), contexts()), (app_actions(), APP_CONTEXTS))]
    for zname, z in ZONES.items():
        for acts_, ctxs_ in plan:
            for i, (a, c) in enumerate(itertools.product(acts_, ctxs_)):
                if zname in ("raw", "minimal", "empty") and i % 5:
                    continue    # these sets differ little from default: a fifth of the product is enough
                ok, res = call(core.decide, a, c, z)
                if not ok:
                    continue
                cases.append([zname, ix(acts, act_ix, a), ix(ctxs, ctx_ix, c), res[0], ix(reasons, why_ix, res[1])])
    # a case is [zone set, action index, context index, zone, reason index]
    return {"zones": ZONES, "actions": acts, "contexts": ctxs, "reasons": reasons, "cases": cases}


# ------------------------------------------------------------------ redact
SNAP = (GATE / "tests" / "fake_wmcp.py").read_text(encoding="utf-8").split("SNAP = '''")[1].split("'''")[0]
SNAPS = [
    SNAP,
    SNAP + "\n",
    SNAP.replace("\n", "\r\n"),
    'UI Tree:\ndesktop\n├── window "C:\\\\Users\\\\x\\\\Desktop\\\\Nodach - File Explorer"\n'
    '│   ├── (813,257) list item "client_secret_123.apps.googleusercontent.com.json"  [action: click]\n'
    '│   └── (10,10) list item "notes.txt"  [action: click]',
    'UI Tree:\ndesktop\n├── window "C:\\\\Users\\\\x\\\\Desktop\\\\Nodach\\\\nodach_sec - File Explorer"\n│   └── (1,1) list item "anything.json"',
    "",
    "no tree at all",
    "Focused Window:\nVault - Bitwarden\nOpened Windows:\nVault - Bitwarden\nNotepad\nUI Tree:\n"
    'desktop\n├── window "Vault - Bitwarden"\n│   ├── (1,1) button "Copy"  [action: click]\n│   │   └── (2,2) text "deep"\n'
    '│\n│   └── (3,3) text "after a blank line"\n└── window "Notepad"\n    └── (4,4) edit "Bitwarden notes"  [action: type]',
    'Focused Window:\nBarclays\nwindow "Barclays" at top\nwindow "Barclays"\n├── (1,1) edit "x"',
    'UI Tree:\nwindow "Barclays"\n (1,1) edit "card"\n  (2,2) edit "deeper"\nwindow "Notepad"\n (3,3) edit "free"',
    'UI Tree:\n├── window "PayPal"\n├── window "PayPal Checkout"\n│   └── (1,1) button "Pay"  [action: click]\n'
    '├── window "PayPal"\n│   └── x\n└── window "Notes: PayPal receipt"',
    'UI Tree:\n├── window ""\n├── window\n├── window "unterminated\n├── window "a "quoted" title"\n'
    '│   └── (1,1) text "my_secret" and "two" and "three\n└──window "Bitwarden"\n└──\twindow "Bitwarden"',
    'UI Tree:\n├── window "ΣΟΦΙΑ notes"\n│   └── (1,1) text "σοφια"\n├── window "Ünïcode"\n│   └── (1,1) edit "Ünïcode"  [action: type]\n'
    '└── window "日本語 straße"\n    └── (2,2) text "STRASSE token: 123"',
    "UI Tree:\r\n└── window \"Monzo\"\r\n    └── (1,1) text \"balance\"\u2028after\x0bvt\x1cfs\x85nel",
    'Opened Windows:\nsecrets.txt - Notepad\nrecovery codes\nUI Tree:\ndesktop\n├── window "recovery codes"\n│   └── (1,1) text "123-456"\n'
    '├── window "Downloads"\n│   ├── (2,2) list item "id_rsa"  [action: click]\n│   ├── (3,3) list item "id_rsa.pub"  [action: click]\n'
    '│   ├── (4,4) list item "my.kek.file"  [action: click]\n│   └── (5,5) list item "readme"  [action: click]',
    "   \n│ \n├── \n└── window \"Bitwarden\"   \n    └── child\n\n    └── after empty",
]


def redact_vectors():
    out = []
    for zname in ("default", "raw", "custom", "minimal", "empty"):
        for t in SNAPS:
            ok, res = call(core.redact_snapshot, t, ZONES[zname])
            if ok:
                out.append({"zones": zname, "text": t, "out": res[0], "hidden": res[1]})
    return out


# ------------------------------------------------------------------ log
def log_vectors():
    texts = ["", "hi", "a" * 80, "a" * 81, "a" * 200, "é" * 90, "日本語" * 30, "line\nbreak", None, 0, 5, 1.5, True, False]
    mask = []
    for t, secret, limit in itertools.product(texts, (False, True), (80, 120, 200, 0, 3)):
        mask.append({"text": t, "secret": secret, "limit": limit, "out": core.mask_text(t, secret, limit)})
    secret = []
    for name, typ, pw in itertools.product(
            ["", "Password", "Enter PIN", "Pinboard", "pin_code", "OTP", "one-time code", "2FA code", "CVV", "Name", "Passcode:",
             "SECURITY CODE", "spin", "passwords"],
            ["", "edit", "PasswordBox", "password", "Edit (password)"], [False, True]):
        secret.append({"element_name": name, "element_type": typ, "is_password": pw, "out": core.looks_secret(name, typ, pw)})
    ctxs = [{}, {"element_name": "Password", "is_password": True}, {"element_name": "Enter PIN"}, {"element_name": "Text editor"},
            {"element_type": "PasswordBox"}, {"element_name": None, "element_type": None}, {"is_password": "yes"}]
    argsets = [{}, {"text": "hunter2", "loc": [1, 2]}, {"text": "a" * 200}, {"text": None}, {"text": 0}, {"text": 1234},
               {"texts": ["a", "b" * 100, 3, None], "items": ["x" * 90]}, {"note": "n" * 250}, {"note": None},
               {"command": "c" * 130, "mode": "launch", "name": "Notepad"}, {"shortcut": "ctrl+c", "nested": {"text": "x" * 300}},
               {"text": "é" * 81, "press_enter": True}]
    clean = []
    for c, a in itertools.product(ctxs, argsets):
        clean.append({"tool": "Type", "args": a, "ctx": c, "out": core.clean_args("Type", a, c)})
    entries = []
    for i, (c, a) in enumerate(itertools.product(ctxs[:4] + [{"app": "chrome.exe", "title": "t" * 300, "element_name": "e" * 90,
                                                              "element_type": "Edit"}], argsets[:6])):
        inp = {"ts": [0, 1763700000.1239, 1763700000.9999, 1763700000.0005, 1e9 + 0.5][i % 5], "tool": "Type", "args": a, "ctx": c,
               "zone": "auto", "reason": "no rule matched", "decision": "allowed", "by": "auto", "duration_ms": [5, 7.9, 0][i % 3],
               "ok": i % 2 == 0, "error": ["", "boom " * 100][i % 2], "shot": [None, "shots/x.png"][i % 2],
               "zones_rev": "3-abc", "session": "GS-1", "kind": "action", "extra": [{}, {"granted": True}][i % 2]}
        kw = dict(inp)
        entries.append({"in": inp, "out": core.log_entry(**kw)})
    isos = [{"ts": t, "out": core.iso(t)} for t in
            [0, 0.0005, 0.0015, 0.9995, 1.0, 59.9999, 951782400, 1763700000.1239, 1763700000.9999995, 4102444800.5, 1e9 + 0.123456]]
    keys = [{"shortcut": s, "out": core.norm_keys(s)} for s in SHORTCUTS if isinstance(s, str)]
    procs = [{"name": n, "out": core._proc(n)} for n in ["", " Notepad.EXE ", "x.exe.exe", "EXE", ".exe", "\x1cA.exe\x1f", "İ.exe"]]
    return {"mask_text": mask, "looks_secret": secret, "clean_args": clean, "log_entry": entries, "iso": isos,
            "norm_keys": keys, "proc": procs}


# ------------------------------------------------------------------ zones
def zones_vectors():
    raw_text = (GATE / "zones.json").read_text(encoding="utf-8")
    d = core.parse_zones(raw_text)
    d.pop("_sha", None)
    texts = [raw_text, '{"revision": 9, "_x": 1, "never": [{"name": "n", "_why": "c", "processes": ["a"]}], "capture": {"clips": false}}',
             '{"confirm": {"element_words": ["only"]}, "auto_apps": []}', "{}", '{"revision": 2.0, "gate_titles": ["X"]}']
    parse = []
    for t in texts:
        parse.append({"text": t, "defaults": None, "out": core.parse_zones(t)})
        parse.append({"text": t, "defaults": d, "out": core.parse_zones(t, d)})
    user1 = {"revision": 1, "never": [{"name": "password manager", "processes": ["MyVault"]}], "auto_apps": ["X"], "_changes": ["1: first"]}
    def1 = {"revision": 2, "never": [{"name": "password manager", "processes": ["Bitwarden"]}, {"name": "secrets in files"}],
            "_changes": ["1: first", {"revision": 2, "what": "secrets"}]}
    up_cases = [
        (user1, def1),
        (core.upgrade_zones(user1, def1)[0], def1),
        (user1, RAW),
        ({"revision": "1", "never": []}, {"revision": "3", "never": [{"name": "a"}, {"x": 1}], "_changes": [
            {"revision": 1, "w": "old"}, {"revision": "2", "w": "s"}, {"revision": 3}, {"revision": 3}, "text note"]}),
        ({"never": [{"x": 1}], "_changes": None}, {"revision": 1, "never": [{"y": 2}, {"name": "b"}]}),
        ({"revision": 5}, {"revision": 4, "never": [{"name": "z"}]}),
        ({"revision": 2, "_changes": [{"revision": 3, "what": "already"}]}, {"revision": 3, "_changes": [{"revision": 3, "what": "already"}]}),
        (RAW, RAW),
    ]
    upgrade = []
    for u, df in up_cases:
        ok, res = call(core.upgrade_zones, u, df)
        if ok:
            upgrade.append({"user": u, "default": df, "out": res[0], "added": res[1]})
    load = [{"user": None, "defaults": raw_text, "out": core.load_zones(None)}]
    return {"parse": parse, "upgrade": upgrade, "load": load}


def dump(obj) -> str:
    """Deterministic: sorted keys; list items of the big tables one per line."""
    if isinstance(obj, dict):
        parts = []
        for k in sorted(obj):
            v = obj[k]
            if isinstance(v, list) and v:
                inner = ",\n".join("  " + json.dumps(x, sort_keys=True, ensure_ascii=False) for x in v)
                parts.append(f"{json.dumps(k)}: [\n{inner}\n ]")
            else:
                parts.append(f"{json.dumps(k)}: {json.dumps(v, sort_keys=True, ensure_ascii=False)}")
        return "{\n " + ",\n ".join(parts) + "\n}\n"
    return dump({"cases": obj})


def main(argv):
    files = {
        "words.json": dump({"version": core.VERSION, "cases": words_vectors()}),
        "decide.json": dump(dict(decide_vectors(), version=core.VERSION)),
        "redact.json": dump({"version": core.VERSION, "cases": redact_vectors()}),
        "log.json": dump(dict(log_vectors(), version=core.VERSION)),
        "zones.json": dump(dict(zones_vectors(), version=core.VERSION)),
    }
    counts = {}
    for name, text in files.items():
        data = json.loads(text)
        counts[name] = sum(len(v) for k, v in data.items() if isinstance(v, list) and k not in ("actions", "contexts", "reasons"))
    total = sum(counts.values())
    print(f"gate {core.VERSION}: {total} vectors ({', '.join(f'{k} {v}' for k, v in counts.items())}); "
          f"{SKIPPED['python_raises']} cases left out because Python raises")
    if "--check" in argv:
        bad = [n for n, t in files.items() if not (OUT / n).exists() or (OUT / n).read_text(encoding="utf-8") != t]
        if bad:
            print("parity vectors are out of date (run python actionmap/gate/tests/export_vectors.py and commit):", ", ".join(bad))
            return 1
        print("parity vectors up to date")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for n, t in files.items():
        (OUT / n).write_text(t, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
