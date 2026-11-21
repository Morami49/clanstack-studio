"""
Nodach Gate confirm popup: a small topmost window on the PC. Started by gate_mcp.py as its own process for each
confirm-zone action, so it never shares a thread with the MCP server.

    python gate_popup.py <request.json>      prints one word: once | app10 | block | timeout

request.json: {"action": "...", "app": "...", "title": "...", "element": "...", "reason": "...", "shot": path|null,
               "timeout_s": 60, "grant_minutes": 10}
The window title starts with "Nodach Gate", which is a never-zone title: Claude can't click its own Allow.
"""
from __future__ import annotations

import json
import sys


def main(argv) -> int:
    req = json.loads(open(argv[1], encoding="utf-8").read())
    import tkinter as tk
    answer = {"v": "timeout"}
    root = tk.Tk()
    root.title("Nodach Gate — confirm")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    pad = {"padx": 12, "pady": 4}
    tk.Label(root, text="Claude wants to:", font=("Segoe UI", 10)).pack(anchor="w", **pad)
    tk.Label(root, text=req.get("action", "?"), font=("Segoe UI", 12, "bold"), wraplength=460, justify="left").pack(anchor="w", **pad)
    info = f"in {req.get('app') or '?'} · {req.get('title') or ''}\nelement: {req.get('element') or '(no name)'}\nwhy asked: {req.get('reason', '')}"
    tk.Label(root, text=info, font=("Segoe UI", 9), fg="#444", wraplength=460, justify="left").pack(anchor="w", **pad)
    if req.get("shot"):
        try:
            img = tk.PhotoImage(file=req["shot"])
            f = max(1, img.width() // 440 + 1, img.height() // 220 + 1)
            img = img.subsample(f, f) if f > 1 else img
            tk.Label(root, image=img, relief="solid", bd=1).pack(**pad)
            root._img = img
        except Exception:
            pass
    left = {"s": int(req.get("timeout_s", 60))}
    timer = tk.Label(root, font=("Segoe UI", 9), fg="#a00")
    timer.pack(anchor="w", **pad)
    row = tk.Frame(root)
    row.pack(fill="x", padx=12, pady=10)

    def done(v):
        answer["v"] = v
        root.destroy()
    tk.Button(row, text="Allow once", width=12, command=lambda: done("once")).pack(side="left")
    tk.Button(row, text=f"Allow for {req.get('grant_minutes', 10)} min in this app", command=lambda: done("app10")).pack(side="left", padx=6)
    tk.Button(row, text="Block", width=10, bg="#c33", fg="white", command=lambda: done("block")).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", lambda: done("block"))
    root.bind("<Escape>", lambda e: done("block"))

    def tick():
        if left["s"] <= 0:
            done("timeout")
            return
        timer.config(text=f"Blocks automatically in {left['s']} s")
        left["s"] -= 1
        root.after(1000, tick)
    tick()
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    root.geometry(f"+{root.winfo_screenwidth() - w - 40}+{root.winfo_screenheight() - h - 80}")
    root.lift()
    root.focus_force()
    root.mainloop()
    print(answer["v"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
