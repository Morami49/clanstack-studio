"""P1 a: compare a hub's /reliability answer with ops/reliability-baseline.json. Exit 1 with reasons on any drift."""
import json
import sys


def problems(env: str, got: dict, baseline: dict) -> list[str]:
    out = []
    for name, present in (got.get("seeds") or {}).items():
        if not present and not name.endswith("_NEXT"):   # *_NEXT is the optional escrow seed (SD1 a)
            out.append(f"{env}: {name} is missing")
    priv = got.get("private") or {}
    if not priv.get("ready"):
        out.append(f"{env}: the Private tier isn't ready")
    limit = baseline.get(env, {}).get("sealed_rows", 0)
    if priv.get("sealed_rows", 0) > limit:
        out.append(f"{env}: sealed private rows rose to {priv.get('sealed_rows')} (baseline {limit}); a key may have been replaced")
    if not (got.get("record") or {}).get("verified", False):
        out.append(f"{env}: the record's signed chain does not verify")
    return out


if __name__ == "__main__":
    env, answer, base = sys.argv[1], json.load(open(sys.argv[2])), json.load(open(sys.argv[3]))
    found = problems(env, answer, base)
    print("\n".join(found) if found else f"{env}: reliability ok ({json.dumps(answer.get('private'))})")
    sys.exit(1 if found else 0)
