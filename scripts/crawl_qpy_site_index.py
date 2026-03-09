#!/usr/bin/env python3
"""
Crawl QuecPython docs sitemap and summarize pages by section/language.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, List

import requests


SITEMAP_URL = "https://developer.quectel.com/doc/quecpython/sitemap.xml"


def split_section_lang(url: str) -> tuple[str, str]:
    m = re.search(
        r"/doc/quecpython/(Getting_started|Dev_board_guide|Application_guide|FAQ|API_reference|API_reference_V1\\.0)/(zh|en)/",
        url,
    )
    if m:
        return m.group(1), m.group(2)
    if "/doc/quecpython/" in url:
        return "other", "other"
    return "external", "external"


def fetch_urls(timeout: int) -> List[str]:
    r = requests.get(SITEMAP_URL, timeout=timeout)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls: List[str] = []
    for loc in root.findall(".//sm:loc", ns):
        if loc.text:
            urls.append(loc.text.strip())
    return urls


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Crawl QuecPython docs sitemap.")
    p.add_argument("--lang", choices=["zh", "en", "all"], default="all")
    p.add_argument("--section", help="Optional section filter, e.g. API_reference.")
    p.add_argument("--top", type=int, default=40, help="Show first N URLs.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    p.add_argument("--out", help="Save JSON to file.")
    p.add_argument("--timeout", type=int, default=30)
    return p


def main() -> int:
    args = build_parser().parse_args()
    urls = fetch_urls(timeout=max(5, args.timeout))
    grouped: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))

    for u in urls:
        section, lang = split_section_lang(u)
        grouped[section][lang].append(u)

    filtered: List[str] = []
    for sec, by_lang in grouped.items():
        for lang, arr in by_lang.items():
            if args.section and sec.lower() != args.section.lower():
                continue
            if args.lang != "all" and lang != args.lang:
                continue
            filtered.extend(arr)

    filtered = sorted(set(filtered))

    summary = {
        "sitemap": SITEMAP_URL,
        "total_urls": len(urls),
        "filtered_count": len(filtered),
        "groups": {sec: {lg: len(v) for lg, v in by.items()} for sec, by in grouped.items()},
        "sample_urls": filtered[: max(1, args.top)],
    }

    if args.out:
        parent = os.path.dirname(os.path.abspath(args.out))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print("Sitemap: %s" % SITEMAP_URL)
    print("Total URLs: %d" % len(urls))
    print("Filtered URLs: %d" % len(filtered))
    print("")
    print("Groups:")
    for sec in sorted(grouped.keys()):
        lang_map = grouped[sec]
        parts = ["%s=%d" % (lg, len(arr)) for lg, arr in sorted(lang_map.items())]
        print("- %s: %s" % (sec, ", ".join(parts)))
    print("")
    print("Sample URLs:")
    for u in filtered[: max(1, args.top)]:
        print("- %s" % u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
