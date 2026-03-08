#!/usr/bin/env python3
"""
Shared tool-path discovery helpers for QuecPython host scripts.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, List, Optional


def _dedup_paths(paths: Iterable[Path]) -> List[Path]:
    out: List[Path] = []
    seen = set()
    for p in paths:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def candidate_roots(start_file: str) -> List[Path]:
    here = Path(start_file).resolve().parent
    cwd = Path.cwd().resolve()
    roots = [here, cwd]
    roots.extend(list(here.parents))
    roots.extend(list(cwd.parents))
    return _dedup_paths(roots)


def candidate_script_paths(exe_name: str, start_file: str) -> List[Path]:
    name = exe_name.strip()
    if not name:
        return []
    out: List[Path] = []
    for root in candidate_roots(start_file):
        out.extend(
            [
                root / name,
                root / "scripts" / name,
                root
                / "3rd"
                / "qpy-vscode-extension-master"
                / "qpy-vscode-extension-master"
                / "scripts"
                / name,
                root
                / "quectel-modules"
                / "quecpython"
                / "3rd"
                / "qpy-vscode-extension-master"
                / "qpy-vscode-extension-master"
                / "scripts"
                / name,
                root
                / "quecpython"
                / "3rd"
                / "qpy-vscode-extension-master"
                / "qpy-vscode-extension-master"
                / "scripts"
                / name,
            ]
        )
    return _dedup_paths(out)


def _normalize_candidate(value: str, exe_name: str) -> List[Path]:
    text = (value or "").strip()
    if not text:
        return []
    p = Path(text).expanduser()
    if p.is_dir():
        return [p / exe_name]
    return [p]


def resolve_windows_exe(
    exe_name: str,
    start_file: str,
    explicit: str = "",
    env_vars: Optional[List[str]] = None,
) -> Optional[str]:
    candidates: List[Path] = []

    candidates.extend(_normalize_candidate(explicit, exe_name))

    for key in env_vars or []:
        val = os.environ.get(key, "")
        candidates.extend(_normalize_candidate(val, exe_name))

    which_path = shutil.which(exe_name)
    if which_path:
        candidates.append(Path(which_path))

    candidates.extend(candidate_script_paths(exe_name, start_file))

    for p in _dedup_paths(candidates):
        try:
            if p.is_file():
                return str(p.resolve())
        except Exception:
            continue
    return None

