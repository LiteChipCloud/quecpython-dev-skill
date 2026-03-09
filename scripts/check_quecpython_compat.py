#!/usr/bin/env python3
"""
Static checker for common QuecPython compatibility issues.

This script is intended for device-side runtime files.
"""

from __future__ import annotations

import argparse
import ast
import io
import os
import re
import tokenize
from dataclasses import dataclass
from typing import Iterable, List, Optional


DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "build",
    "dist",
    "out",
    ".cursor",
    ".trae",
    "3rd",
}

BANNED_IMPORT_SUGGESTIONS = {
    "json": "ujson",
    "time": "utime",
    "os": "uos",
    "re": "ure",
    "socket": "usocket",
    "ssl": "ussl",
    "struct": "ustruct",
    "binascii": "ubinascii",
    "collections": "ucollections",
    "random": "urandom",
    "zlib": "uzlib",
    "hashlib": "uhashlib",
    "typing": None,
    "pathlib": None,
    "threading": "_thread",
    "asyncio": None,
    "subprocess": None,
}


@dataclass
class Issue:
    file_path: str
    line: int
    col: int
    rule: str
    message: str

    def format(self) -> str:
        return "%s:%d:%d [%s] %s" % (
            self.file_path,
            self.line,
            self.col,
            self.rule,
            self.message,
        )


def should_skip_dir(dir_name: str, excluded: set[str]) -> bool:
    return dir_name in excluded


def iter_py_files(root: str, excluded: set[str]) -> Iterable[str]:
    if os.path.isfile(root):
        if root.endswith(".py"):
            yield root
        return

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d, excluded)]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


def detect_fstrings(source: str, file_path: str) -> List[Issue]:
    issues: List[Issue] = []
    stream = io.StringIO(source)
    try:
        for tok in tokenize.generate_tokens(stream.readline):
            if tok.type != tokenize.STRING:
                continue
            token_text = tok.string
            # Prefix before first quote
            prefix_match = re.match(r"^([rRuUbBfF]*)['\"]", token_text)
            if not prefix_match:
                continue
            prefix = prefix_match.group(1)
            if "f" in prefix.lower():
                issues.append(
                    Issue(
                        file_path=file_path,
                        line=tok.start[0],
                        col=tok.start[1] + 1,
                        rule="FSTRING",
                        message="f-string detected in device-side code baseline.",
                    )
                )
    except tokenize.TokenError:
        # Parsing errors are handled in AST phase.
        pass
    return issues


def detect_regex_rules(lines: List[str], file_path: str) -> List[Issue]:
    checks = [
        (r"\bnonlocal\b", "NONLOCAL", "nonlocal detected."),
        (r":=", "WALRUS", "walrus operator ':=' detected."),
        (r"^\s*async\s+def\b", "ASYNC_DEF", "async function detected."),
        (r"\bawait\b", "AWAIT", "await keyword detected."),
        (
            r"\.\s*removeprefix\s*\(",
            "REMOVEPREFIX",
            "str.removeprefix() may be unsupported in target baseline.",
        ),
        (
            r"\.\s*removesuffix\s*\(",
            "REMOVESUFFIX",
            "str.removesuffix() may be unsupported in target baseline.",
        ),
    ]
    issues: List[Issue] = []
    for idx, line in enumerate(lines, start=1):
        for pattern, rule, msg in checks:
            m = re.search(pattern, line)
            if m:
                issues.append(
                    Issue(
                        file_path=file_path,
                        line=idx,
                        col=m.start() + 1,
                        rule=rule,
                        message=msg,
                    )
                )
    return issues


def detect_ast_rules(
    source: str, lines: List[str], file_path: str, allow_annotations: bool
) -> List[Issue]:
    issues: List[Issue] = []
    try:
        tree = ast.parse(source, filename=file_path)
    except SyntaxError as exc:
        issues.append(
            Issue(
                file_path=file_path,
                line=exc.lineno or 1,
                col=(exc.offset or 1),
                rule="SYNTAX",
                message="syntax error: %s" % (exc.msg,),
            )
        )
        return issues

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                suggestion = BANNED_IMPORT_SUGGESTIONS.get(base)
                if suggestion is not None or base in BANNED_IMPORT_SUGGESTIONS:
                    msg = "import '%s' is not preferred in QuecPython runtime." % base
                    if suggestion:
                        msg += " Use '%s' if applicable." % suggestion
                    issues.append(
                        Issue(
                            file_path=file_path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            rule="IMPORT",
                            message=msg,
                        )
                    )

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                base = node.module.split(".")[0]
                suggestion = BANNED_IMPORT_SUGGESTIONS.get(base)
                if suggestion is not None or base in BANNED_IMPORT_SUGGESTIONS:
                    msg = "from '%s' import ... is not preferred in QuecPython runtime." % (
                        base,
                    )
                    if suggestion:
                        msg += " Use '%s' if applicable." % suggestion
                    issues.append(
                        Issue(
                            file_path=file_path,
                            line=node.lineno,
                            col=node.col_offset + 1,
                            rule="IMPORT_FROM",
                            message=msg,
                        )
                    )

        if allow_annotations:
            continue

        if isinstance(node, ast.FunctionDef):
            if node.returns is not None:
                issues.append(
                    Issue(
                        file_path=file_path,
                        line=node.lineno,
                        col=node.col_offset + 1,
                        rule="ANNOTATION",
                        message="function return type annotation detected.",
                    )
                )
            for arg in list(node.args.args) + list(node.args.kwonlyargs):
                if arg.annotation is not None:
                    issues.append(
                        Issue(
                            file_path=file_path,
                            line=arg.lineno,
                            col=arg.col_offset + 1,
                            rule="ANNOTATION",
                            message="function argument type annotation detected.",
                        )
                    )
            if node.args.vararg and node.args.vararg.annotation is not None:
                issues.append(
                    Issue(
                        file_path=file_path,
                        line=node.args.vararg.lineno,
                        col=node.args.vararg.col_offset + 1,
                        rule="ANNOTATION",
                        message="vararg type annotation detected.",
                    )
                )
            if node.args.kwarg and node.args.kwarg.annotation is not None:
                issues.append(
                    Issue(
                        file_path=file_path,
                        line=node.args.kwarg.lineno,
                        col=node.args.kwarg.col_offset + 1,
                        rule="ANNOTATION",
                        message="kwarg type annotation detected.",
                    )
                )

        elif isinstance(node, ast.AnnAssign):
            issues.append(
                Issue(
                    file_path=file_path,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    rule="ANNOTATION",
                    message="variable type annotation detected.",
                )
            )

    return issues


def check_file(file_path: str, allow_annotations: bool) -> List[Issue]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="gbk", errors="ignore") as f:
            source = f.read()

    lines = source.splitlines()
    issues: List[Issue] = []
    issues.extend(detect_fstrings(source, file_path))
    issues.extend(detect_regex_rules(lines, file_path))
    issues.extend(detect_ast_rules(source, lines, file_path, allow_annotations))
    return issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check common QuecPython compatibility issues in .py files. "
            "Target device runtime code paths (for example code/ or /usr mirrors)."
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help=(
            "File or directory to scan. Use device runtime code paths. "
            "Default: current directory."
        ),
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Extra directory names to exclude from recursive scan.",
    )
    parser.add_argument(
        "--allow-annotations",
        action="store_true",
        help="Allow type annotations (host-side scripts), do not report ANNOTATION issues.",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Do not use built-in excluded directories.",
    )
    parser.add_argument(
        "--fail-on-issues",
        dest="fail_on_issues",
        action="store_true",
        default=True,
        help="Exit with code 1 when issues are found (default).",
    )
    parser.add_argument(
        "--no-fail-on-issues",
        dest="fail_on_issues",
        action="store_false",
        help="Always exit with code 0 even when issues are found.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    excluded = set(args.exclude_dir)
    if not args.no_default_excludes:
        excluded.update(DEFAULT_EXCLUDE_DIRS)

    all_issues: List[Issue] = []
    scanned = 0
    for file_path in iter_py_files(args.path, excluded):
        scanned += 1
        all_issues.extend(check_file(file_path, args.allow_annotations))

    all_issues.sort(key=lambda x: (x.file_path, x.line, x.col, x.rule))

    for issue in all_issues:
        print(issue.format())

    print("")
    print("Scanned files: %d" % scanned)
    print("Issues found: %d" % len(all_issues))
    print(
        "Tip: run this checker on device runtime folders only; "
        "for host tooling scripts, use --allow-annotations --no-fail-on-issues."
    )

    if all_issues and args.fail_on_issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
