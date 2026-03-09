#!/usr/bin/env python3
"""
Query QuecPython official docs for pin-to-GPIO mapping clues.

This script focuses on development-board mapping tables and returns
traceable source rows with confidence scores.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from typing import Any, Dict, List, Tuple

import requests


DEFAULT_DOC_URLS_ZH = [
    "https://developer.quectel.com/doc/quecpython/API_reference/zh/peripherals/machine.Pin.html",
    "https://developer.quectel.com/doc/quecpython/API_reference/en/peripherals/machine.Pin.html",
    "https://developer.quectel.com/doc/quecpython/Dev_board_guide/zh/ec800x-evb.html",
    "https://developer.quectel.com/doc/quecpython/Dev_board_guide/zh/ec600x-ec800x-core-evb.html",
]

DEFAULT_DOC_URLS_EN = [
    "https://developer.quectel.com/doc/quecpython/API_reference/en/peripherals/machine.Pin.html",
    "https://developer.quectel.com/doc/quecpython/Dev_board_guide/en/ec800x-evb.html",
    "https://developer.quectel.com/doc/quecpython/Dev_board_guide/en/ec600x-ec800x-core-evb.html",
]


def normalize(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def fetch_html(url: str, timeout: int) -> str:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def strip_tags(text: str) -> str:
    no_tag = re.sub(r"<[^>]+>", " ", text, flags=re.S)
    no_tag = html.unescape(no_tag)
    no_tag = re.sub(r"\s+", " ", no_tag).strip()
    return no_tag


def parse_table_rows(page_html: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    tables = re.findall(r"<table([^>]*)>(.*?)</table>", page_html, flags=re.I | re.S)
    for attrs, body in tables:
        cls_match = re.search(r'class="([^"]+)"', attrs, flags=re.I)
        table_class = cls_match.group(1).strip() if cls_match else ""
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, flags=re.I | re.S):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, flags=re.I | re.S)
            cleaned = [strip_tags(c) for c in cells]
            if cleaned:
                rows.append({"row": cleaned, "table_class": table_class})
    return rows


def model_mentioned(page_html: str, model: str) -> bool:
    if not model:
        return True
    n = normalize(model)
    if not n:
        return True
    return n in normalize(strip_tags(page_html))


def model_matches_table(model: str, table_class: str) -> bool:
    if not model:
        return True
    if not table_class:
        return False
    model_norm = normalize(model)
    if not model_norm:
        return True
    raw_tokens = re.split(r"[,\s/|]+", table_class)
    tokens = [normalize(t) for t in raw_tokens if normalize(t)]
    if not tokens:
        return False
    for t in tokens:
        if t in model_norm or model_norm in t:
            return True
    return False


def score_row_for_pin(row: List[str], pin: int) -> Tuple[int, List[str], str]:
    pin_s = str(pin)
    row_text = " | ".join(row)
    row_norm = normalize(row_text)
    reasons: List[str] = []
    score = 0

    if any(c.strip() == pin_s for c in row):
        score = max(score, 3)
        reasons.append("cell_exact_pin")
    if re.search(r"\bP%s\b" % pin_s, row_text, flags=re.I):
        score = max(score, 2)
        reasons.append("contains_Pxx")
    if ("PIN" + pin_s) in row_norm:
        score = max(score, 2)
        reasons.append("contains_PINxx")

    gpio_hits = sorted(set(re.findall(r"GPIO\s*([0-9]+)", row_text, flags=re.I)))
    gpios = ["GPIO%s" % x for x in gpio_hits]
    return score, gpios, ",".join(reasons)


def score_row_for_gpio(row: List[str], gpio: int) -> Tuple[int, List[str], str]:
    gpio_s = str(gpio)
    row_text = " | ".join(row)
    row_norm = normalize(row_text)
    reasons: List[str] = []
    score = 0

    if ("GPIO" + gpio_s) in row_norm:
        score = max(score, 3)
        reasons.append("contains_gpio")

    pin_hits = sorted(set(re.findall(r"\bP([0-9]+)\b", row_text, flags=re.I)))
    pin_hits.extend(sorted(set(re.findall(r"\bPIN\s*([0-9]+)\b", row_text, flags=re.I))))
    pins = sorted(set(["PIN%s" % x for x in pin_hits]))
    return score, pins, ",".join(reasons)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Query official docs for pin mapping clues.")
    p.add_argument("--model", default="", help="Module/model hint, for example EC800KCNLC.")
    p.add_argument("--pin", type=int, help="Pin number to query, for example 20.")
    p.add_argument("--gpio", type=int, help="GPIO number to reverse query, for example 28.")
    p.add_argument("--lang", choices=["zh", "en"], default="zh", help="Doc language.")
    p.add_argument("--url", action="append", default=[], help="Custom page URL, can pass multiple.")
    p.add_argument(
        "--strict-model",
        action="store_true",
        help="Only keep rows where model is mentioned in page and table class matches model.",
    )
    p.add_argument(
        "--include-low-confidence",
        action="store_true",
        help="Keep non-model-matched rows even when model-matched rows exist.",
    )
    p.add_argument("--top", type=int, default=10, help="Max results.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    p.add_argument("--timeout", type=int, default=25, help="HTTP timeout seconds.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.pin is None and args.gpio is None:
        print("Need --pin or --gpio.")
        return 2

    urls = list(args.url)
    if not urls:
        urls = DEFAULT_DOC_URLS_ZH if args.lang == "zh" else DEFAULT_DOC_URLS_EN

    results: List[Dict[str, Any]] = []
    fetch_errors: List[str] = []

    for url in urls:
        try:
            page = fetch_html(url, timeout=max(5, args.timeout))
        except Exception as e:
            fetch_errors.append("%s: %s" % (url, e))
            continue

        rows = parse_table_rows(page)
        mentioned = model_mentioned(page, args.model)

        for item in rows:
            row = item["row"]
            table_class = item.get("table_class", "")
            table_match = model_matches_table(args.model, table_class)
            if args.pin is not None:
                score, gpios, reason = score_row_for_pin(row, args.pin)
                if score <= 0 or not gpios:
                    continue
                results.append(
                    {
                        "url": url,
                        "model_mentioned_in_page": mentioned,
                        "model_matched_table_class": table_match,
                        "table_class": table_class,
                        "query": {"pin": args.pin},
                        "score": score,
                        "reason": reason,
                        "gpio_candidates": gpios,
                        "row": row,
                    }
                )
            if args.gpio is not None:
                score, pins, reason = score_row_for_gpio(row, args.gpio)
                if score <= 0:
                    continue
                results.append(
                    {
                        "url": url,
                        "model_mentioned_in_page": mentioned,
                        "model_matched_table_class": table_match,
                        "table_class": table_class,
                        "query": {"gpio": args.gpio},
                        "score": score,
                        "reason": reason,
                        "pin_candidates": pins,
                        "row": row,
                    }
                )

    results.sort(
        key=lambda x: (
            int(bool(x.get("model_matched_table_class"))),
            int(bool(x.get("model_mentioned_in_page"))),
            int(x.get("score", 0)),
            x.get("url", ""),
        ),
        reverse=True,
    )

    strict_filter_applied = False
    if args.model and args.strict_model:
        strict_filter_applied = True
        results = [
            r
            for r in results
            if bool(r.get("model_matched_table_class")) and bool(r.get("model_mentioned_in_page"))
        ]
    elif args.model and not args.include_low_confidence:
        high_conf = [r for r in results if r.get("model_matched_table_class")]
        if high_conf:
            results = high_conf

    results = results[: max(1, args.top)]

    payload = {
        "query": {"model": args.model, "pin": args.pin, "gpio": args.gpio, "lang": args.lang},
        "strict_model": bool(args.strict_model),
        "strict_model_filter_applied": strict_filter_applied,
        "sources": urls,
        "matched_count": len(results),
        "results": results,
        "errors": fetch_errors,
        "policy": "NO_COMMERCIAL_VERDICT",
        "note": (
            "Reference evidence only. This script never outputs a commercial-release verdict. "
            "Cross-check module hardware design specs and run electrical validation."
        ),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("Model: %s" % (args.model or "<none>"))
    if args.strict_model:
        print("Strict model filter: ON")
    if args.pin is not None:
        print("Query PIN: %s" % args.pin)
    if args.gpio is not None:
        print("Query GPIO: %s" % args.gpio)
    print("Matched: %d" % len(results))
    print("")
    for i, r in enumerate(results, 1):
        print(
            "%d) score=%s model_mentioned=%s table_match=%s"
            % (
                i,
                r.get("score"),
                r.get("model_mentioned_in_page"),
                r.get("model_matched_table_class"),
            )
        )
        print("   url: %s" % r.get("url"))
        if r.get("table_class"):
            print("   table_class: %s" % r.get("table_class"))
        if "gpio_candidates" in r:
            print("   gpio_candidates: %s" % ", ".join(r.get("gpio_candidates") or []))
        if "pin_candidates" in r:
            print("   pin_candidates: %s" % ", ".join(r.get("pin_candidates") or []))
        print("   row: %s" % " | ".join(r.get("row") or []))
        print("")

    if fetch_errors:
        print("Errors:")
        for e in fetch_errors:
            print("- %s" % e)

    print("Policy: NO_COMMERCIAL_VERDICT")
    print("Note: Reference evidence only; hardware design spec + electrical validation are mandatory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
