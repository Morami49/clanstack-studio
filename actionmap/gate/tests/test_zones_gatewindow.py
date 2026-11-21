import gate_core as core


def _z():
    import json, pathlib
    return json.loads((pathlib.Path(__file__).resolve().parents[1] / "zones.json").read_text(encoding="utf-8"))


def test_gate_window_in_front_allows_reads_and_launches_but_not_input():
    z = _z()
    ctx = {"app": "pythonw.exe", "title": "Nodach Gate", "element_name": ""}
    assert core.decide({"tool": "Snapshot", "args": {}}, ctx, z)[0] == "auto"
    zone, _ = core.decide({"tool": "App", "args": {"mode": "launch", "name": "Notepad"}}, dict(ctx, target_app="notepad", target_title="Notepad"), z)
    assert zone in ("auto", "confirm")
    assert core.decide({"tool": "Click", "args": {"loc": [10, 10]}}, ctx, z)[0] == "never"
    assert core.decide({"tool": "App", "args": {"mode": "switch", "name": "Nodach Gate"}}, ctx, z)[0] == "never"


def test_secret_file_windows_are_never_read():
    z = _z()
    ctx = {"app": "Notepad.exe", "title": "github-recovery-codes.txt - Notepad"}
    assert core.decide({"tool": "Snapshot", "args": {}}, ctx, z)[0] == "never"
    assert core.decide({"tool": "Type", "args": {"loc": [1, 1], "text": "x"}}, {"app": "Notepad.exe", "title": "Untitled - Notepad"}, z)[0] == "auto"
