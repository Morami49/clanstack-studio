"""AUD-secrets-state (1): guard the names that hold the hub's data.

A Durable Object's storage belongs to its Worker name and class. Renaming the Worker (clanstack-hub,
clanstack-hub-staging), the RECORD binding's class, or adding a delete/rename migration makes the record seem to
vanish: a deploy points at a fresh, empty namespace. Cloudflare's point-in-time recovery can't bring it back
under the new name. This check fails CI when any of those change, so a rename has to be an explicit, reviewed
edit of PINNED below (a high-risk file) rather than a slip.

Usage: python scripts/check_worker_names.py [hub/wrangler.toml]   (exit 1 and reasons on stderr when unsafe)
"""
import sys
import tomllib

PINNED = {
    "": "clanstack-hub",                # production
    "staging": "clanstack-hub-staging",  # staging
}
BINDING, CLASS = "RECORD", "Record"
ONE_WAY = ("deleted_classes", "renamed_classes", "transferred_classes")


def problems(cfg: dict) -> list[str]:
    out = []
    for env, want in PINNED.items():
        sec = cfg if not env else cfg.get("env", {}).get(env)
        where = env or "production"
        if sec is None:
            out.append(f"[{where}] environment is missing")
            continue
        if sec.get("name") != want:
            out.append(f"[{where}] Worker name is {sec.get('name')!r}, must stay {want!r} (its Durable Object data lives under that name)")
        binds = {b.get("name"): b.get("class_name") for b in sec.get("durable_objects", {}).get("bindings", [])}
        if binds.get(BINDING) != CLASS:
            out.append(f"[{where}] binding {BINDING} points at {binds.get(BINDING)!r}, must stay {CLASS!r}")
        migs = sec.get("migrations", [])
        if not any(CLASS in (m.get("new_sqlite_classes") or []) for m in migs):
            out.append(f"[{where}] the migration that created {CLASS} was removed; migrations are history and must be kept")
        for m in migs:
            for k in ONE_WAY:
                if m.get(k):
                    out.append(f"[{where}] migration {m.get('tag')!r} has {k}: one-way change to stored data, needs Nowed")
    return out


def main(path: str) -> int:
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    found = problems(cfg)
    for p in found:
        print("::error::" + p, file=sys.stderr)
    print("worker names and Durable Object classes unchanged" if not found else f"{len(found)} unsafe change(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "hub/wrangler.toml"))
