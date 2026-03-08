#!/usr/bin/env python3
"""
Query QuecPython official API document links by keyword.

Default source priority:
1) --source argument (if given)
2) repo local docs/QuecPython-API-链接清单.md (if present)
3) bundled references/official-doc-links.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import webbrowser
from dataclasses import dataclass
from typing import List, Optional


URL_RE = re.compile(r"https?://[^\s]+")


@dataclass
class DocEntry:
    url: str
    module: str
    category: str

    def as_dict(self) -> dict:
        return {"url": self.url, "module": self.module, "category": self.category}


def parse_entry(url: str) -> DocEntry:
    parts = [p for p in url.split("/") if p]
    module = ""
    category = ""

    if "API_reference" in parts:
        idx = parts.index("API_reference")
        # .../API_reference/<lang>/<category>/<module>.html
        if len(parts) > idx + 3:
            category = parts[idx + 3]
        if len(parts) > idx + 4:
            module = parts[idx + 4]
        elif len(parts) > idx + 3:
            module = parts[idx + 3]

    if module.endswith(".html"):
        module = module[:-5]
    if not module:
        module = parts[-1].replace(".html", "")
    return DocEntry(url=url, module=module.lower(), category=category.lower())


def read_links(path: str) -> List[DocEntry]:
    items: List[DocEntry] = []
    seen = set()
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            for m in URL_RE.findall(line):
                url = m.strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                items.append(parse_entry(url))
    return items


def default_sources() -> List[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    skill_root = os.path.abspath(os.path.join(here, ".."))
    repo_local = os.path.abspath(
        os.path.join(skill_root, "..", "..", "..", "QuecPython-API-链接清单.md")
    )
    bundled = os.path.abspath(
        os.path.join(skill_root, "references", "official-doc-links.md")
    )
    return [repo_local, bundled]


def choose_source(explicit: Optional[str]) -> Optional[str]:
    candidates: List[str] = []
    if explicit:
        candidates.append(os.path.abspath(explicit))
    candidates.extend(default_sources())
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def match_entry(entry: DocEntry, terms: List[str], lang: str) -> bool:
    if lang:
        token = "/%s/" % lang.lower()
        if token not in entry.url.lower():
            return False
    if not terms:
        return True
    blob = (entry.url + " " + entry.module + " " + entry.category).lower()
    return all(t in blob for t in terms)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query QuecPython official documentation links from local index."
    )
    parser.add_argument(
        "--source",
        help="Path to link index markdown file (for example docs/QuecPython-API-链接清单.md).",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Filter keyword, repeatable. Example: --keyword uart --keyword machine",
    )
    parser.add_argument(
        "--lang",
        default="zh",
        choices=["zh", "en", "all"],
        help="Language segment in URL path. Default zh.",
    )
    parser.add_argument("--top", type=int, default=20, help="Maximum output rows.")
    parser.add_argument("--json", action="store_true", help="Output JSON.")
    parser.add_argument(
        "--open-first",
        action="store_true",
        help="Open first matched URL in default browser.",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        help="List all detected API categories and exit.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    src = choose_source(args.source)
    if not src:
        print("No source index found.")
        print("Pass --source or ensure references/official-doc-links.md exists.")
        return 2

    entries = read_links(src)
    if not entries:
        print("No links parsed from source: %s" % src)
        return 2

    if args.list_categories:
        cats = sorted({e.category for e in entries if e.category})
        for c in cats:
            print(c)
        return 0

    lang = "" if args.lang == "all" else args.lang
    terms = [k.strip().lower() for k in args.keyword if k.strip()]
    matched = [e for e in entries if match_entry(e, terms, lang)]
    matched = matched[: max(1, args.top)]

    if args.open_first and matched:
        webbrowser.open(matched[0].url)

    if args.json:
        print(
            json.dumps(
                {
                    "source": src,
                    "keywords": terms,
                    "lang": args.lang,
                    "count": len(matched),
                    "results": [e.as_dict() for e in matched],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("Source: %s" % src)
        print("Keywords: %s" % (", ".join(terms) if terms else "<none>"))
        print("Lang: %s" % args.lang)
        print("")
        if not matched:
            print("No matching docs.")
            print(
                "Tip: local index may be incomplete. Try online search: "
                "python scripts/query_qpy_docs_online.py --keyword <term> --lang %s"
                % (args.lang,)
            )
        else:
            for idx, item in enumerate(matched, start=1):
                print(
                    "%d. [%s/%s] %s"
                    % (idx, item.category or "misc", item.module or "index", item.url)
                )
            print("")
            print("Matched: %d" % len(matched))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
