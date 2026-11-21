"""84b a: Send and other input inside Nodach's own Watch/Desktop windows go through without the popup, trusted by
process (script under %USERPROFILE%\\nodach\\app), never by title."""
import gate_core as core

HOME = r"C:\Users\akabd\nodach"
PYW = r"C:\Python314\pythonw.exe"


def _z():
    import json, pathlib
    return json.loads((pathlib.Path(__file__).resolve().parents[1] / "zones.json").read_text(encoding="utf-8"))


def dec(tool, args, ctx):
    return core.decide({"tool": tool, "args": args}, dict(ctx, watch=True), _z())


def test_trusted_own_by_process():
    assert core.trusted_own(PYW, [PYW, HOME + r"\app\watch\watch_app.py"], HOME) == "watch_app.py"
    assert core.trusted_own(PYW, [PYW, HOME + r"\app\shell\desktop_gui.py"], HOME) == "desktop_gui.py"


def test_not_trusted_elsewhere_or_spoofed():
    # same script name outside the Nodach app folder
    assert core.trusted_own(PYW, [PYW, r"C:\Temp\watch\watch_app.py"], HOME) == ""
    # not a Python interpreter
    assert core.trusted_own(r"C:\evil\app.exe", [r"C:\evil\app.exe", HOME + r"\app\watch\watch_app.py"], HOME) == ""
    # path tricks
    assert core.trusted_own(PYW, [PYW, HOME + r"\app\..\..\x\watch\watch_app.py"], HOME) == ""
    # Gate's own popup and GUI are never trusted for input
    assert core.trusted_own(PYW, [PYW, HOME + r"\app\gate\gate_popup.py"], HOME) == ""


def test_send_in_own_window_skips_popup():
    ctx = {"app": "pythonw.exe", "title": "Nodach Watch", "element_name": "Send", "own_trusted": "watch_app.py"}
    zone, reason = dec("Click", {"loc": [10, 10]}, ctx)
    assert zone == core.OWN_ZONE and "checked by process" in reason


def test_title_alone_does_not_skip_popup():
    ctx = {"app": "fake.exe", "title": "Nodach Watch", "element_name": "Send", "own_trusted": ""}
    assert dec("Click", {"loc": [10, 10]}, ctx)[0] == "confirm"


def test_gate_window_still_never_even_if_trusted():
    ctx = {"app": "pythonw.exe", "title": "Nodach Gate", "element_name": "Allow", "own_trusted": "watch_app.py"}
    assert dec("Click", {"loc": [10, 10]}, ctx)[0] == "never"
