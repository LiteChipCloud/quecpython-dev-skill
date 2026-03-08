#!/usr/bin/env python3
"""
Search QuecPython online docs via official search index.

Uses:
https://developer.quectel.com/doc/quecpython/static/search_index/index.json
and index_*.json files.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

import requests


BASE = "https://developer.quectel.com/doc/quecpython/static/search_index"


@dataclass
class DocHit:
    url: str
    title: str
    score: int
    snippet: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "score": self.score,
            "snippet": self.snippet,
        }


def load_manifest(timeout: int) -> Dict[str, List[str]]:
    r = requests.get(f"{BASE}/index.json", timeout=timeout)
    r.raise_for_status()
    data = r.json()
    out: Dict[str, List[str]] = {}
    for k, v in data.items():
        if isinstance(v, list):
            out[k] = [str(x) for x in v]
    return out


def select_index_files(
    manifest: Dict[str, List[str]],
    lang: str,
    sections: List[str],
) -> List[str]:
    selected: Set[str] = set()
    lang = lang.lower()
    sec_norm = [s.strip().strip("/").lower() for s in sections if s.strip()]

    for path, files in manifest.items():
        p = path.lower()
        if lang in {"zh", "en"} and ("/%s/" % lang) not in p:
            continue
        if sec_norm and not any(("/%s/" % s) in p for s in sec_norm):
            continue
        for f in files:
            s = str(f).strip()
            if ".json" not in s.lower():
                continue
            if s.startswith("http://") or s.startswith("https://"):
                selected.add(s.rsplit("/", 1)[-1])
            elif s.startswith("/"):
                selected.add(s.rsplit("/", 1)[-1])
            else:
                selected.add(s)
    return sorted(selected)


def load_index_file(name: str, timeout: int) -> Dict[str, Dict[str, str]]:
    r = requests.get(f"{BASE}/{name}", timeout=timeout)
    r.raise_for_status()
    j = r.json()
    out: Dict[str, Dict[str, str]] = {}
    if isinstance(j, dict):
        for url, payload in j.items():
            if isinstance(payload, dict):
                out[str(url)] = {
                    "title": str(payload.get("title") or ""),
                    "content": str(payload.get("content") or ""),
                }
    return out


def make_snippet(text: str, terms: List[str], limit: int = 180) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return ""
    idx = -1
    for t in terms:
        i = clean.lower().find(t.lower())
        if i >= 0 and (idx < 0 or i < idx):
            idx = i
    if idx < 0:
        return clean[:limit]
    start = max(0, idx - 50)
    end = min(len(clean), idx + 50 + limit // 2)
    return clean[start:end]


def score_hit(title: str, content: str, url: str, terms: List[str], model: str) -> int:
    blob = (title + " " + content + " " + url).lower()
    s = 0
    for t in terms:
        tl = t.lower()
        if tl in title.lower():
            s += 6
        if tl in url.lower():
            s += 4
        if tl in blob:
            s += 2
    if model:
        m = model.lower()
        if m in content.lower() or m in title.lower():
            s += 5
    return s


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Search official QuecPython docs with online search index."
    )
    p.add_argument("--keyword", action="append", default=[], help="Search keyword, repeatable.")
    p.add_argument(
        "--section",
        action="append",
        default=[],
        help="Section filter, repeatable: API_reference, Getting_started, Dev_board_guide, Application_guide, FAQ",
    )
    p.add_argument("--lang", choices=["zh", "en", "all"], default="zh", help="Language scope.")
    p.add_argument("--model", help="Optional model token to boost/filter pages, e.g. EC800K.")
    p.add_argument("--top", type=int, default=20, help="Max output rows.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    p.add_argument("--open-first", action="store_true", help="Open first hit in browser.")
    p.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    terms = [k.strip() for k in args.keyword if k.strip()]
    if not terms:
        print("At least one --keyword is required.")
        return 2

    manifest = load_manifest(timeout=max(5, args.timeout))
    files: List[str] = []
    if args.lang == "all":
        # gather both zh and en
        files = sorted(
            set(
                select_index_files(manifest, "zh", args.section)
                + select_index_files(manifest, "en", args.section)
            )
        )
    else:
        files = select_index_files(manifest, args.lang, args.section)

    hits: List[DocHit] = []
    model = (args.model or "").strip()
    for f in files:
        pages = load_index_file(f, timeout=max(5, args.timeout))
        for url, payload in pages.items():
            title = payload.get("title") or ""
            content = payload.get("content") or ""
            blob = (title + " " + content + " " + url).lower()
            if any(t.lower() not in blob for t in terms):
                continue
            if model and model.lower() not in blob:
                # model acts as additional filter if provided
                continue
            score = score_hit(title, content, url, terms, model)
            snippet = make_snippet(content, terms)
            full_url = url if url.startswith("http") else ("https://developer.quectel.com" + url)
            hits.append(DocHit(url=full_url, title=title, score=score, snippet=snippet))

    hits.sort(key=lambda x: (x.score, x.title), reverse=True)
    hits = hits[: max(1, args.top)]

    if args.open_first and hits:
        import webbrowser

        webbrowser.open(hits[0].url)

    if args.json:
        print(
            json.dumps(
                {
                    "keywords": terms,
                    "section": args.section,
                    "lang": args.lang,
                    "model": model,
                    "count": len(hits),
                    "results": [h.as_dict() for h in hits],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print("Keywords: %s" % ", ".join(terms))
    print("Lang: %s" % args.lang)
    print("Section: %s" % (", ".join(args.section) if args.section else "<all>"))
    if model:
        print("Model filter: %s" % model)
    print("")
    if not hits:
        print("No matching pages.")
        return 0

    for i, h in enumerate(hits, start=1):
        print("%d. [score=%d] %s" % (i, h.score, h.title))
        print("   %s" % h.url)
        if h.snippet:
            print("   %s" % h.snippet)
    print("")
    print("Matched: %d" % len(hits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
