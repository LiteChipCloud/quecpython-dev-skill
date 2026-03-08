#!/usr/bin/env python3
"""
QuecPython project/component manager for AI IDE workflows.

Capabilities:
1) Discover official QuecPython solution/component repositories from GitHub.
2) Query releases for a repository.
3) Clone repository by branch/tag with submodules.
4) Add/remove/list git submodules in a workspace.
5) Maintain a local "My Projects" registry JSON (evidence and quick reuse).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests


GITHUB_API = "https://api.github.com"
ORG = "QuecPython"
MARKER_FILE = ".vscode/quec-python-project.json"


@dataclass
class RepoRecord:
    id: int
    name: str
    full_name: str
    description: str
    default_branch: str
    clone_url: str
    html_url: str
    topics: List[str]
    pushed_at: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "full_name": self.full_name,
            "description": self.description,
            "default_branch": self.default_branch,
            "clone_url": self.clone_url,
            "html_url": self.html_url,
            "topics": self.topics,
            "pushed_at": self.pushed_at,
        }


def run_cmd(cmd: List[str], cwd: Optional[str] = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def ensure_git_available() -> None:
    if shutil.which("git"):
        return
    raise RuntimeError("git is not available in PATH.")


def normalize_repo_input(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        p = urlparse(text)
        seg = [x for x in p.path.split("/") if x]
        if len(seg) >= 2:
            owner = seg[0]
            name = seg[1].replace(".git", "")
            return "%s/%s" % (owner, name)
        return text
    if "/" not in text:
        return "%s/%s" % (ORG, text)
    return text.replace(".git", "")


def github_headers(token: str) -> Dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = "Bearer %s" % token
    return h


def github_get(url: str, token: str, timeout: int, params: Optional[Dict[str, Any]] = None) -> Any:
    r = requests.get(url, headers=github_headers(token), params=params, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError("GitHub API error %s: %s" % (r.status_code, r.text[:240]))
    return r.json()


def parse_repo_item(item: Dict[str, Any]) -> RepoRecord:
    return RepoRecord(
        id=int(item.get("id") or 0),
        name=str(item.get("name") or ""),
        full_name=str(item.get("full_name") or ""),
        description=str(item.get("description") or ""),
        default_branch=str(item.get("default_branch") or "main"),
        clone_url=str(item.get("clone_url") or ""),
        html_url=str(item.get("html_url") or ""),
        topics=[str(x) for x in (item.get("topics") or [])],
        pushed_at=str(item.get("pushed_at") or ""),
    )


def search_repos(topic: str, limit: int, token: str, timeout: int) -> List[RepoRecord]:
    per_page = min(max(1, limit), 100)
    page = 1
    out: List[RepoRecord] = []
    while len(out) < limit:
        data = github_get(
            "%s/search/repositories" % GITHUB_API,
            token=token,
            timeout=timeout,
            params={
                "q": "org:%s topic:%s" % (ORG, topic),
                "sort": "updated",
                "order": "desc",
                "per_page": per_page,
                "page": page,
            },
        )
        items = data.get("items") or []
        if not items:
            break
        for item in items:
            out.append(parse_repo_item(item))
            if len(out) >= limit:
                break
        if len(items) < per_page:
            break
        page += 1
    return out


def get_repo(repo: str, token: str, timeout: int) -> RepoRecord:
    normalized = normalize_repo_input(repo)
    if "/" not in normalized:
        raise RuntimeError("Invalid repository reference: %s" % repo)
    owner, name = normalized.split("/", 1)
    data = github_get("%s/repos/%s/%s" % (GITHUB_API, owner, name), token=token, timeout=timeout)
    return parse_repo_item(data)


def list_releases(repo: str, token: str, timeout: int, top: int) -> List[Dict[str, Any]]:
    normalized = normalize_repo_input(repo)
    owner, name = normalized.split("/", 1)
    data = github_get(
        "%s/repos/%s/%s/releases" % (GITHUB_API, owner, name),
        token=token,
        timeout=timeout,
        params={"per_page": min(max(1, top), 100)},
    )
    out: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "tag_name": str(item.get("tag_name") or ""),
                "name": str(item.get("name") or ""),
                "draft": bool(item.get("draft")),
                "prerelease": bool(item.get("prerelease")),
                "published_at": str(item.get("published_at") or ""),
                "html_url": str(item.get("html_url") or ""),
                "zipball_url": str(item.get("zipball_url") or ""),
            }
        )
    return out


def default_registry_path() -> str:
    here = Path(__file__).resolve().parent
    return str((here / ".." / "review" / "user_projects_registry.json").resolve())


def load_registry(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_registry(path: str, rows: List[Dict[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_registry(path: str, item: Dict[str, Any]) -> None:
    rows = load_registry(path)
    key = str(item.get("repo_full_name") or "")
    out: List[Dict[str, Any]] = []
    updated = False
    for row in rows:
        if str(row.get("repo_full_name") or "") == key and str(row.get("local_path") or "") == str(
            item.get("local_path") or ""
        ):
            out.append(item)
            updated = True
        else:
            out.append(row)
    if not updated:
        out.append(item)
    save_registry(path, out)


def remove_registry(path: str, repo_or_path: str) -> int:
    target = (repo_or_path or "").strip().lower()
    if not target:
        return 0
    rows = load_registry(path)
    out: List[Dict[str, Any]] = []
    removed = 0
    for row in rows:
        full_name = str(row.get("repo_full_name") or "").lower()
        local_path = str(row.get("local_path") or "").lower()
        if target in {full_name, local_path}:
            removed += 1
        else:
            out.append(row)
    save_registry(path, out)
    return removed


def write_marker(project_dir: str) -> str:
    marker = Path(project_dir) / MARKER_FILE
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "managedBy": "QuecPython.qpy-ide",
        "createdAt": datetime.now().isoformat(timespec="seconds"),
    }
    marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(marker)


def clone_repo(
    record: RepoRecord,
    dest_root: str,
    ref: str,
    depth: int,
    timeout: int,
    force: bool,
) -> str:
    root = Path(dest_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / record.name
    if target.exists() and any(target.iterdir()) and not force:
        raise RuntimeError("Target exists and is not empty: %s (use --force)" % str(target))
    if target.exists() and force:
        shutil.rmtree(target)
    cmd = ["git", "clone", "--recurse-submodules"]
    if ref:
        cmd.extend(["--branch", ref])
    if depth > 0:
        cmd.extend(["--depth", str(depth)])
    cmd.extend([record.clone_url, str(target)])
    cp = run_cmd(cmd, timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError("git clone failed: %s" % ((cp.stdout or "") + (cp.stderr or "")))
    return str(target)


def add_submodule(workspace: str, repo_url: str, path: str, ref: str, timeout: int) -> Dict[str, Any]:
    cmd = ["git", "-C", workspace, "submodule", "add", "-f"]
    if ref:
        cmd.extend(["-b", ref])
    cmd.append(repo_url)
    if path:
        cmd.append(path)
    cp = run_cmd(cmd, timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError("git submodule add failed: %s" % ((cp.stdout or "") + (cp.stderr or "")))
    cp2 = run_cmd(["git", "-C", workspace, "submodule", "update", "--init", "--recursive"], timeout=timeout)
    if cp2.returncode != 0:
        raise RuntimeError("git submodule update failed: %s" % ((cp2.stdout or "") + (cp2.stderr or "")))
    return {"add_output": (cp.stdout or "") + (cp.stderr or ""), "update_output": (cp2.stdout or "") + (cp2.stderr or "")}


def remove_submodule(workspace: str, path: str, timeout: int) -> Dict[str, str]:
    cp1 = run_cmd(["git", "-C", workspace, "submodule", "deinit", "-f", "--", path], timeout=timeout)
    cp2 = run_cmd(["git", "-C", workspace, "rm", "-f", path], timeout=timeout)
    if cp2.returncode != 0:
        raise RuntimeError("git rm submodule failed: %s" % ((cp2.stdout or "") + (cp2.stderr or "")))
    # Optional cleanup of .git/modules/<path>
    mod_dir = Path(workspace) / ".git" / "modules" / path
    if mod_dir.exists():
        shutil.rmtree(mod_dir, ignore_errors=True)
    return {
        "deinit_output": (cp1.stdout or "") + (cp1.stderr or ""),
        "rm_output": (cp2.stdout or "") + (cp2.stderr or ""),
    }


def list_submodules(workspace: str) -> List[Dict[str, str]]:
    gm = Path(workspace) / ".gitmodules"
    if not gm.exists():
        return []
    text = gm.read_text(encoding="utf-8", errors="replace")
    out: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[submodule "):
            if current.get("name"):
                out.append(current)
            m = re.search(r'\[submodule "([^"]+)"\]', s)
            current = {"name": m.group(1) if m else "", "path": "", "url": ""}
        elif s.startswith("path = "):
            current["path"] = s[len("path = ") :].strip()
        elif s.startswith("url = "):
            current["url"] = s[len("url = ") :].strip()
    if current.get("name"):
        out.append(current)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="QuecPython project/component manager.")
    p.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""), help="GitHub token (or env GITHUB_TOKEN).")
    p.add_argument("--timeout", type=int, default=60, help="HTTP/command timeout seconds.")
    p.add_argument("--json", action="store_true", help="Output JSON.")

    sp = p.add_subparsers(dest="action", required=True)

    p_discover = sp.add_parser("discover", help="Discover official QuecPython repos.")
    p_discover.add_argument("--kind", choices=["solution", "component", "all"], default="all")
    p_discover.add_argument("--limit", type=int, default=30, help="Max repositories per kind.")

    p_rel = sp.add_parser("releases", help="List releases for a repo.")
    p_rel.add_argument("--repo", required=True, help="Repo name/full_name/url.")
    p_rel.add_argument("--top", type=int, default=20, help="Max release rows.")

    p_clone = sp.add_parser("clone", help="Clone repo with submodules.")
    p_clone.add_argument("--repo", required=True, help="Repo name/full_name/url.")
    p_clone.add_argument("--dest", required=True, help="Destination root directory.")
    p_clone.add_argument("--ref", default="", help="Branch or tag name (optional).")
    p_clone.add_argument("--depth", type=int, default=0, help="Git clone depth. 0 means full history.")
    p_clone.add_argument("--force", action="store_true", help="Delete existing target directory if needed.")
    p_clone.add_argument("--registry", default=default_registry_path(), help="Path to local project registry JSON.")
    p_clone.add_argument("--no-register", action="store_true", help="Do not write local registry record.")

    p_add = sp.add_parser("add-submodule", help="Add component submodule into workspace.")
    p_add.add_argument("--workspace", required=True, help="Workspace root path.")
    p_add.add_argument("--repo", required=True, help="Component repo name/full_name/url.")
    p_add.add_argument("--path", default="", help="Submodule target path in workspace.")
    p_add.add_argument("--ref", default="", help="Branch name for submodule.")

    p_rm = sp.add_parser("remove-submodule", help="Remove submodule from workspace.")
    p_rm.add_argument("--workspace", required=True, help="Workspace root path.")
    p_rm.add_argument("--path", required=True, help="Submodule path to remove.")

    p_ls = sp.add_parser("list-submodules", help="List submodules from .gitmodules.")
    p_ls.add_argument("--workspace", required=True, help="Workspace root path.")

    p_rl = sp.add_parser("registry-list", help="List local My Projects registry.")
    p_rl.add_argument("--registry", default=default_registry_path(), help="Path to local project registry JSON.")

    p_rr = sp.add_parser("registry-remove", help="Remove entry from local registry by repo full name or local path.")
    p_rr.add_argument("--registry", default=default_registry_path(), help="Path to local project registry JSON.")
    p_rr.add_argument("--target", required=True, help="Exact repo full_name or local_path.")

    return p


def print_repo_list(rows: List[RepoRecord], title: str) -> None:
    print(title)
    for i, r in enumerate(rows, start=1):
        print("%d. %s" % (i, r.full_name))
        print("   default_branch: %s" % r.default_branch)
        print("   pushed_at: %s" % r.pushed_at)
        if r.description:
            print("   description: %s" % r.description)
        print("   clone_url: %s" % r.clone_url)


def main() -> int:
    args = build_parser().parse_args()
    ensure_git_available()
    timeout = max(10, int(args.timeout))
    token = args.token or ""

    try:
        if args.action == "discover":
            kinds = ["solution", "component"] if args.kind == "all" else [args.kind]
            merged: Dict[str, Dict[str, Any]] = {}
            for kind in kinds:
                rows = search_repos(kind, limit=max(1, args.limit), token=token, timeout=timeout)
                for r in rows:
                    d = r.as_dict()
                    d["kind"] = kind
                    merged[r.full_name] = d
            out = sorted(merged.values(), key=lambda x: x.get("pushed_at", ""), reverse=True)
            if args.kind == "all":
                out = out[: max(1, args.limit)]
            payload = {"org": ORG, "kind": args.kind, "count": len(out), "results": out}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                if args.kind in {"solution", "component"}:
                    print_repo_list([RepoRecord(**{k: v for k, v in d.items() if k in RepoRecord.__annotations__}) for d in out], "Found %s repositories: %d" % (args.kind, len(out)))
                else:
                    print("Found repositories: %d" % len(out))
                    for i, d in enumerate(out, start=1):
                        print("%d. [%s] %s" % (i, d.get("kind", ""), d.get("full_name", "")))
                        print("   default_branch: %s" % d.get("default_branch", ""))
                        print("   pushed_at: %s" % d.get("pushed_at", ""))
                        print("   clone_url: %s" % d.get("clone_url", ""))
            return 0

        if args.action == "releases":
            rows = list_releases(args.repo, token=token, timeout=timeout, top=max(1, args.top))
            payload = {"repo": normalize_repo_input(args.repo), "count": len(rows), "releases": rows}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Repo: %s" % payload["repo"])
                if not rows:
                    print("No releases found.")
                for i, r in enumerate(rows, start=1):
                    print("%d. %s" % (i, r.get("tag_name", "")))
                    print("   published_at: %s" % r.get("published_at", ""))
                    print("   prerelease: %s" % r.get("prerelease", False))
                    print("   url: %s" % r.get("html_url", ""))
            return 0

        if args.action == "clone":
            repo = get_repo(args.repo, token=token, timeout=timeout)
            local_path = clone_repo(
                repo,
                dest_root=args.dest,
                ref=(args.ref or "").strip(),
                depth=max(0, int(args.depth)),
                timeout=max(60, timeout * 3),
                force=bool(args.force),
            )
            marker = write_marker(local_path)
            record = {
                "id": "%s_%s" % (int(datetime.now().timestamp()), repo.name),
                "name": repo.name,
                "repo_full_name": repo.full_name,
                "clone_url": repo.clone_url,
                "default_branch": repo.default_branch,
                "ref": (args.ref or repo.default_branch),
                "local_path": local_path,
                "marker_file": marker,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "source": "qpy_project_manager.py",
            }
            if not args.no_register:
                upsert_registry(args.registry, record)
            payload = {"ok": True, "repo": repo.as_dict(), "local_path": local_path, "marker_file": marker, "registry": args.registry, "registered": (not args.no_register)}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Clone completed.")
                print("Local path: %s" % local_path)
                print("Marker file: %s" % marker)
                if not args.no_register:
                    print("Registry updated: %s" % args.registry)
            return 0

        if args.action == "add-submodule":
            ws = str(Path(args.workspace).resolve())
            if not (Path(ws) / ".git").exists():
                raise RuntimeError("Workspace is not a git repository: %s" % ws)
            repo = get_repo(args.repo, token=token, timeout=timeout)
            result = add_submodule(
                workspace=ws,
                repo_url=repo.clone_url,
                path=(args.path or "").strip(),
                ref=(args.ref or "").strip(),
                timeout=max(60, timeout * 2),
            )
            payload = {
                "ok": True,
                "workspace": ws,
                "repo": repo.as_dict(),
                "path": (args.path or repo.name),
                "ref": (args.ref or ""),
                "result": result,
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Submodule added.")
                print("Workspace: %s" % ws)
                print("Repo: %s" % repo.full_name)
                print("Path: %s" % (args.path or repo.name))
            return 0

        if args.action == "remove-submodule":
            ws = str(Path(args.workspace).resolve())
            result = remove_submodule(workspace=ws, path=args.path, timeout=max(60, timeout * 2))
            payload = {"ok": True, "workspace": ws, "path": args.path, "result": result}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Submodule removed.")
                print("Workspace: %s" % ws)
                print("Path: %s" % args.path)
            return 0

        if args.action == "list-submodules":
            ws = str(Path(args.workspace).resolve())
            rows = list_submodules(ws)
            payload = {"workspace": ws, "count": len(rows), "submodules": rows}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Workspace: %s" % ws)
                if not rows:
                    print("No submodules found.")
                for i, row in enumerate(rows, start=1):
                    print("%d. %s" % (i, row.get("name", "")))
                    print("   path: %s" % row.get("path", ""))
                    print("   url: %s" % row.get("url", ""))
            return 0

        if args.action == "registry-list":
            rows = load_registry(args.registry)
            payload = {"registry": args.registry, "count": len(rows), "projects": rows}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Registry: %s" % args.registry)
                if not rows:
                    print("No projects recorded.")
                for i, row in enumerate(rows, start=1):
                    print("%d. %s" % (i, row.get("repo_full_name", "")))
                    print("   local_path: %s" % row.get("local_path", ""))
                    print("   created_at: %s" % row.get("created_at", ""))
            return 0

        if args.action == "registry-remove":
            removed = remove_registry(args.registry, args.target)
            payload = {"registry": args.registry, "target": args.target, "removed": removed}
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Registry: %s" % args.registry)
                print("Removed entries: %d" % removed)
            return 0

        print("Unknown action.")
        return 2
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except Exception as e:
        if args.json:
            print(json.dumps({"ok": False, "error": str(e), "action": args.action}, ensure_ascii=False, indent=2))
        else:
            print("Error: %s" % e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
