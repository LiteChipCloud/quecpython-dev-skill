#!/usr/bin/env python3
"""
Normalize imported QuecPython markdown docs by removing known site-export noise.
"""

from __future__ import annotations

import argparse
import os
import re


REMOVE_PATTERNS = [
    r".*Edit this page.*",
    r".*toscode\.gitee\.com.*",
    r".*mermaid\.initialize.*",
]


def normalize_text(text: str) -> str:
    lines = text.splitlines()
    out = []
    for line in lines:
        skip = False
        for pattern in REMOVE_PATTERNS:
            if re.match(pattern, line):
                skip = True
                break
        if not skip:
            out.append(line.rstrip())
    # Collapse excessive blank lines.
    normalized = "\n".join(out)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip() + "\n"


def process_file(src: str, dst: str) -> None:
    with open(src, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    cleaned = normalize_text(text)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(cleaned)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize QuecPython markdown docs.")
    parser.add_argument("--src", required=True, help="Source directory containing .md files.")
    parser.add_argument("--out", required=True, help="Output directory for cleaned files.")
    args = parser.parse_args()

    if not os.path.isdir(args.src):
        print("Source directory not found: %s" % args.src)
        return 2

    count = 0
    for dirpath, _, filenames in os.walk(args.src):
        for name in filenames:
            if not name.lower().endswith(".md"):
                continue
            src_file = os.path.join(dirpath, name)
            rel = os.path.relpath(src_file, args.src)
            dst_file = os.path.join(args.out, rel)
            process_file(src_file, dst_file)
            count += 1

    print("Normalized markdown files: %d" % count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
