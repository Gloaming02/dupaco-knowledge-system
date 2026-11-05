#!/usr/bin/env python3
"""Snapshot exploration helper.

  python3 scripts/explore.py grep "60-month"          # which pages mention a phrase, per snapshot
  python3 scripts/explore.py history <url-substring>  # how one page changed across snapshots
  python3 scripts/explore.py diff                     # pages added / removed / changed per snapshot
"""
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "snapshots"


def snaps():
    for d in sorted(p for p in ROOT.iterdir() if (p / "manifest.json").exists()):
        m = json.loads((d / "manifest.json").read_text())
        yield m["snapshot_id"], {p["url"]: (d / p["file"]).read_text(encoding="utf-8") for p in m["pages"]}


def cmd_grep(pat):
    rx = re.compile(pat, re.I)
    for sid, pages in snaps():
        print(f"== {sid}")
        for url, md in sorted(pages.items()):
            for line in md.splitlines():
                if rx.search(line):
                    print(f"  {url}\n      {line.strip()[:200]}")


def cmd_history(sub):
    prev = None
    for sid, pages in snaps():
        hits = [u for u in pages if sub in u]
        if not hits:
            print(f"== {sid}: (absent)"); continue
        url = hits[0]; md = pages[url]
        print(f"== {sid}: {url}")
        if prev is not None:
            for l in difflib.unified_diff(prev.splitlines(), md.splitlines(), lineterm="", n=0):
                if not l.startswith(("---", "+++", "@@")):
                    print("   ", l[:200])
        prev = md


def cmd_diff():
    prev = None
    for sid, pages in snaps():
        if prev is not None:
            changed = sum(1 for u in pages if u in prev and pages[u] != prev[u])
            print(f"{sid}: {len(pages)} pages, +{len(pages.keys()-prev.keys())} -{len(prev.keys()-pages.keys())} ~{changed}")
        else:
            print(f"{sid}: {len(pages)} pages")
        prev = pages


if __name__ == "__main__":
    {"grep": cmd_grep, "history": cmd_history, "diff": lambda *_: cmd_diff()}[sys.argv[1]](*sys.argv[2:])
