"""Two-way sync between hubs (D-016), e.g. laptop <-> Oracle VM.

    python -m clients.sync                       # uses config: client.hub_url + sync.peers
    python -m clients.sync --a URL --b URL --once

Each origin's chain is copied link by link; the receiving hub re-checks every
hash, so nothing can be altered in transit. Works after any outage: it simply
continues from the other hub's last known link. Both hubs keep everything;
neither overwrites the other.
"""
from __future__ import annotations

import argparse
import time

import httpx

from .common import config


def hub(url: str, token: str) -> httpx.Client:
    return httpx.Client(base_url=url.rstrip("/"), timeout=20,
                        headers={"X-ActionMap-Token": token} if token else {})


def copy(src: httpx.Client, dst: httpx.Client, batch: int = 500) -> int:
    sh = src.get("/replicate/heads").json()
    dh = dst.get("/replicate/heads").json()
    moved = 0
    for origin, n in sh["heads"].items():
        if origin == dh["origin"]:
            continue                                   # dst is the author of that chain
        have = dh["heads"].get(origin, 0)
        while have < n:
            evs = src.get("/replicate/pull", params={"origin": origin, "after": have, "limit": batch}).json()
            if not evs:
                break
            r = dst.post("/replicate/push", json=evs).json()
            moved += r["added"]
            if r.get("error"):
                print(f"[sync] {origin}: {r['error']}")
                break
            have = r["heads"].get(origin, have)
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a"); ap.add_argument("--a-token", default="")
    ap.add_argument("--b"); ap.add_argument("--b-token", default="")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    cfg = config()
    c = cfg.get("client", {})
    pairs = []
    if args.a and args.b:
        pairs.append((hub(args.a, args.a_token), hub(args.b, args.b_token)))
    else:
        local = hub(c.get("hub_url", "http://127.0.0.1:8765"), c.get("token", ""))
        for p in cfg.get("sync", {}).get("peers", []):
            pairs.append((local, hub(p["url"], p.get("token", ""))))
    if not pairs:
        raise SystemExit("no peers: set sync.peers in config.yaml or pass --a/--b")
    interval = cfg.get("sync", {}).get("interval_s", 5)
    while True:
        for a, b in pairs:
            try:
                n1, n2 = copy(a, b), copy(b, a)
                if n1 or n2:
                    print(f"[sync] {a.base_url} → {b.base_url}: {n1}   ← {n2}")
            except httpx.HTTPError as e:
                print(f"[sync] {e!r} (will retry)")
        if args.once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
