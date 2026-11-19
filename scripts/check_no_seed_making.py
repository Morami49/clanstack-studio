"""INC-261118-seed guard: fail if any workflow line could create or replace a *_SEED secret.

Seeds root the hub's signatures and Private-tier keys. They are made once, by hand; CI only checks they exist.
"""
import pathlib
import re
import sys

BAD = re.compile(r"secret put[^\n]*\b[A-Z_]*SEED\b|\b[A-Z_]*SEED\b[^\n]*secret put|rand[^\n]*\|[^\n]*secret put")


def offending(text: str) -> list[str]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        code = line.split("#", 1)[0] if not line.lstrip().startswith("- run") else line
        if BAD.search(code) and "::error::" not in code:
            out.append(f"{n}: {line.strip()}")
    return out


def main(folder: str) -> int:
    bad = []
    for f in sorted(pathlib.Path(folder).glob("*.yml")):
        bad += [f"{f}:{x}" for x in offending(f.read_text())]
    for b in bad:
        print(b)
    print("no workflow makes a seed" if not bad else f"{len(bad)} line(s) could make a seed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
