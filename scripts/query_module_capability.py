#!/usr/bin/env python3
"""
Query module capability/resource data for QuecPython projects.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any, Dict, List, Optional
from pathlib import Path


def parse_size_to_kb(value: Any) -> Optional[int]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Handle value like "384K/128K" by taking the first component.
    text = text.split("/")[0].strip()
    m = re.match(r"(?i)^(\d+(?:\.\d+)?)\s*([KM])$", text)
    if not m:
        return None
    num = float(m.group(1))
    unit = m.group(2).upper()
    if unit == "M":
        return int(num * 1024)
    return int(num)


def candidate_data_paths() -> List[Path]:
    here = Path(__file__).resolve()
    skill_root = here.parent.parent
    names = [
        Path("data/modules_sheet03.normalized.json"),
        Path("assets/data/modules_sheet03.normalized.json"),
    ]
    out: List[Path] = []
    for rel in names:
        out.append((skill_root / rel).resolve())
    # Workspace-relative fallbacks for this repo layout.
    cwd = Path.cwd().resolve()
    search_bases = [cwd] + list(cwd.parents)
    for base in search_bases:
        out.append((base / "quectel-modules/quecpython/docs/spec/data/modules_sheet03.normalized.json").resolve())
        out.append((base / "quectel-modules/quecpython/libs/docs/modules_sheet03.normalized.json").resolve())
        out.append((base / "docs/spec/data/modules_sheet03.normalized.json").resolve())
    # De-duplicate while preserving order.
    uniq: List[Path] = []
    seen = set()
    for p in out:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return uniq


def default_data_path() -> str:
    for p in candidate_data_paths():
        if p.exists():
            return str(p)
    # Return first candidate for consistent error display when nothing exists.
    return str(candidate_data_paths()[0])


def load_json(path: str) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_model(text: str) -> str:
    return text.strip().upper().replace(" ", "")


def filter_by_module(rows: List[Dict[str, Any]], module: str) -> List[Dict[str, Any]]:
    target = normalize_model(module)
    exact = [
        r
        for r in rows
        if normalize_model(str(r.get("模组", ""))) == target
    ]
    if exact:
        return exact
    return [
        r
        for r in rows
        if target in normalize_model(str(r.get("模组", "")))
    ]


def has_feature(row: Dict[str, Any], feature: str) -> bool:
    value = row.get(feature)
    if value is True:
        return True
    text = str(value).strip().lower()
    return text in {"true", "optional"}


def filter_by_features(rows: List[Dict[str, Any]], features: List[str]) -> List[Dict[str, Any]]:
    if not features:
        return rows
    output = []
    for row in rows:
        ok = True
        for feat in features:
            if not has_feature(row, feat):
                ok = False
                break
        if ok:
            output.append(row)
    return output


def filter_by_resources(
    rows: List[Dict[str, Any]],
    min_runtime_kb: Optional[int],
    min_fs_kb: Optional[int],
    min_ram_kb: Optional[int],
) -> List[Dict[str, Any]]:
    out = []
    for row in rows:
        runtime_kb = parse_size_to_kb(row.get("运行内存"))
        fs_kb = parse_size_to_kb(row.get("文件系统"))
        ram_kb = parse_size_to_kb(row.get("RAM"))
        if min_runtime_kb is not None and (runtime_kb is None or runtime_kb < min_runtime_kb):
            continue
        if min_fs_kb is not None and (fs_kb is None or fs_kb < min_fs_kb):
            continue
        if min_ram_kb is not None and (ram_kb is None or ram_kb < min_ram_kb):
            continue
        out.append(row)
    return out


def collect_feature_keys(rows: List[Dict[str, Any]]) -> List[str]:
    reserved = {"模组", "平台", "芯片组", "RAM", "FLASH", "运行内存", "文件系统", "备注"}
    keys = set()
    for row in rows:
        keys.update(row.keys())
    return sorted([k for k in keys if k not in reserved])


def normalize_requested_features(
    requested: List[str], rows: List[Dict[str, Any]]
) -> tuple[List[str], List[str]]:
    valid = collect_feature_keys(rows)
    lookup = {k.lower(): k for k in valid}
    normalized: List[str] = []
    missing: List[str] = []
    for feat in requested:
        key = feat.strip()
        if not key:
            continue
        mapped = lookup.get(key.lower())
        if mapped is None:
            missing.append(key)
            normalized.append(key)
        else:
            normalized.append(mapped)
    return normalized, missing


def print_table(rows: List[Dict[str, Any]], features: List[str]) -> None:
    if not rows:
        print("No matching modules.")
        return

    for row in rows:
        print("-" * 72)
        print("Model: %s" % row.get("模组", ""))
        print("Platform/Chipset: %s / %s" % (row.get("平台", ""), row.get("芯片组", "")))
        print(
            "Resources: RAM=%s, FLASH=%s, Runtime=%s, FS=%s"
            % (
                row.get("RAM", ""),
                row.get("FLASH", ""),
                row.get("运行内存", ""),
                row.get("文件系统", ""),
            )
        )
        if features:
            for feat in features:
                print("Feature %-16s : %s" % (feat, row.get(feat, "<missing>")))
        else:
            print("Tip: use --feature to print feature-specific support lines.")
    print("-" * 72)
    print("Matched modules: %d" % len(rows))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query QuecPython module capabilities.")
    parser.add_argument(
        "--data",
        default=default_data_path(),
        help="Path to modules_sheet03.normalized.json",
    )
    parser.add_argument("--module", help="Module model name (exact or contains).")
    parser.add_argument(
        "--feature",
        action="append",
        default=[],
        help="Required feature key. Repeatable.",
    )
    parser.add_argument("--min-runtime-kb", type=int, help="Minimum runtime memory in KB.")
    parser.add_argument("--min-fs-kb", type=int, help="Minimum file system budget in KB.")
    parser.add_argument("--min-ram-kb", type=int, help="Minimum RAM in KB.")
    parser.add_argument("--list-modules", action="store_true", help="List all module names.")
    parser.add_argument("--list-features", action="store_true", help="List available feature keys.")
    parser.add_argument("--json", action="store_true", help="Output matched rows as JSON.")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not os.path.exists(args.data):
        print("Data file not found: %s" % args.data)
        guesses = [str(p) for p in candidate_data_paths() if p.exists()]
        if guesses:
            print("Found candidate data files:")
            for g in guesses:
                print("- %s" % g)
            print("Tip: pass one via --data.")
        return 2

    rows = load_json(args.data)
    norm_features, missing_features = normalize_requested_features(args.feature, rows)

    if args.list_modules:
        for name in sorted({str(r.get("模组", "")).strip() for r in rows if r.get("模组")}):
            print(name)
        return 0

    if args.list_features:
        for key in collect_feature_keys(rows):
            print(key)
        return 0

    filtered = rows
    if args.module:
        filtered = filter_by_module(filtered, args.module)
    filtered = filter_by_features(filtered, norm_features)
    filtered = filter_by_resources(
        filtered,
        min_runtime_kb=args.min_runtime_kb,
        min_fs_kb=args.min_fs_kb,
        min_ram_kb=args.min_ram_kb,
    )
    if missing_features:
        print(
            "Warning: unknown feature keys: %s"
            % ", ".join(sorted(set(missing_features)))
        )
        print("Tip: use --list-features to inspect valid keys.")
        print("")

    if args.json:
        print(json.dumps(filtered, ensure_ascii=False, indent=2))
    else:
        print_table(filtered, norm_features)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
