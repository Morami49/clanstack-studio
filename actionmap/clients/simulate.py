"""Simulated human sessions, so the whole system can be tested on any OS
before the Windows capture is switched on.

    python -m clients.simulate --runs 6
"""
from __future__ import annotations

import argparse
import random
import time

from .common import Spine

# An invoice-chasing workflow with branches. Outlook is on the default private
# list, so its steps collapse into one '[private]' placeholder (that's the point).
FLOW = [
    ("focus_window", "ClickUp.exe", "Invoices board - ClickUp", None),
    ("click", "ClickUp.exe", "Invoices board - ClickUp", "Overdue filter"),
    ("click", "ClickUp.exe", "Invoices board - ClickUp", "Task card"),
    ("focus_window", "EXCEL.EXE", "Invoices.xlsx - Excel", None),
    ("click", "EXCEL.EXE", "Invoices.xlsx - Excel", "Status column cell"),
    ("type_text", "EXCEL.EXE", "Invoices.xlsx - Excel", "Status column cell"),
    ("hotkey", "EXCEL.EXE", "Invoices.xlsx - Excel", "ctrl+s"),
    ("focus_window", "ClickUp.exe", "Invoices board - ClickUp", None),
    ("click", "ClickUp.exe", "Invoices board - ClickUp", "Mark complete"),
]
BRANCH = [  # sometimes the invoice is missing and needs chasing
    ("focus_window", "chrome.exe", "Supplier portal - Chrome", None),
    ("click", "chrome.exe", "Supplier portal - Chrome", "Download invoice"),
    ("observation", "chrome.exe", "Supplier portal - Chrome", "Download complete bar"),
    ("focus_window", "OUTLOOK.EXE", "Inbox - Outlook", None),
    ("click", "OUTLOOK.EXE", "Inbox - Outlook", "Reply"),
    ("click", "OUTLOOK.EXE", "RE: Invoice - Message", "Send"),
]


def run(spine: Spine, runs: int, delay: float, human_id: str):
    spine.register_node(["capture.desktop.sim"])
    for app in ("ClickUp.exe", "EXCEL.EXE", "chrome.exe"):   # answer the first-seen questions
        spine.control("set_privacy", app=app, rule="allowed", actor_id=human_id)
    for r in range(runs):
        steps = list(FLOW)
        if random.random() < 0.35:
            steps[3:3] = BRANCH
        for act, app, window, el in steps:
            kind = "observation" if act == "observation" else "action"
            actor = ("screen", f"screen:{spine.node_id}") if kind == "observation" else ("human", human_id)
            payload = {"chars": random.randint(5, 40), "redacted": True} if act == "type_text" else {}
            if act == "hotkey":
                payload = {"keys": el}
            spine.emit(actor[0], actor[1], kind, "appeared" if kind == "observation" else act,
                       target={"app": app, "window": window, "element": el or window},
                       payload=payload)
            time.sleep(delay)
        print(f"run {r + 1}/{runs} recorded in session {spine.session_id}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--delay", type=float, default=0.05)
    ap.add_argument("--session", default=None)
    ap.add_argument("--human", default="human:nowed")
    a = ap.parse_args()
    run(Spine(node_id="sim-desktop", session_id=a.session), a.runs, a.delay, a.human)
