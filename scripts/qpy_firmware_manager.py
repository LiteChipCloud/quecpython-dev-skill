#!/usr/bin/env python3
"""
QuecPython firmware manager.

Capabilities:
1) Query whether a model has QuecPython firmware resources.
2) Resolve latest firmware version for a model from developer.quectel.com.
3) Download selected firmware package from official URL.
4) Optionally extract package and flash device with QuecPythonDownload.exe.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from qpy_tool_paths import resolve_windows_exe


ENDPOINTS = [
    "https://developer.quectel.com/wp-admin/admin-ajax.php",
    "https://developer.quectel.com/en/wp-admin/admin-ajax.php",
]

FLASH_EXT_PRIORITY = [".pac", ".bin", ".mbn", ".img", ".hex"]


@dataclass
class FirmwareRecord:
    title: str
    version: str
    version_title: str
    release_date: str
    download_url: str
    file_size: int
    category: str
    description: str
    capability_description: str
    item_id: Any
    is_beta: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "version": self.version,
            "version_title": self.version_title,
            "release_date": self.release_date,
            "download_url": self.download_url,
            "file_size": self.file_size,
            "category": self.category,
            "description": self.description,
            "capability_description": self.capability_description,
            "item_id": self.item_id,
            "is_beta": self.is_beta,
        }


def normalize(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def compact_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\r", " ").replace("\n", " ")).strip()


def version_key(v: str) -> Tuple[int, int, int, str]:
    text = (v or "").upper()
    beta = 1 if "BETA" in text else 0
    nums = re.findall(r"\d+", text)
    n1 = int(nums[0]) if nums else -1
    n2 = int(nums[1]) if len(nums) > 1 else -1
    n3 = int(nums[2]) if len(nums) > 2 else -1
    return (1 - beta, n1, n2, text)


def date_key(d: str) -> Tuple[int, int, int]:
    m = re.match(r"^\s*(\d{4})-(\d{2})-(\d{2})\s*$", d or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def fetch_page(
    endpoint: str,
    category: int,
    page: int,
    page_num: int,
    keywords: str,
    timeout: int,
) -> Dict[str, Any]:
    payload = {
        "action": "get_download_list",
        "category": str(category),
        "product_category": "",
        "page": str(page),
        "page_num": str(page_num),
        "orderby": "date",
        "order": "desc",
        "keywords": keywords,
    }
    r = requests.post(endpoint, data=payload, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if not j.get("success"):
        raise RuntimeError("API success=false on endpoint: %s" % endpoint)
    return j.get("data", {})


def fetch_all_items(
    category: int,
    page_num: int,
    keywords: str,
    timeout: int,
) -> Tuple[str, List[Dict[str, Any]]]:
    last_err: Optional[Exception] = None
    for ep in ENDPOINTS:
        try:
            first = fetch_page(ep, category, 1, page_num, keywords, timeout)
            total_page = int(first.get("total_page") or 1)
            rows = list(first.get("data") or [])
            for p in range(2, total_page + 1):
                d = fetch_page(ep, category, p, page_num, keywords, timeout)
                rows.extend(list(d.get("data") or []))
            return ep, rows
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError("All endpoints failed: %r" % last_err)


def is_qpy_firmware_item(item: Dict[str, Any]) -> bool:
    title = str(item.get("title") or "").upper()
    desc = str(item.get("description") or "").upper()
    cat = str(item.get("download_category") or "").upper()
    if "QPY" in title or "QPY" in desc:
        return True
    if "QUECPYTHON" in title or "QUECPYTHON" in desc:
        return True
    if cat in {"固件", "FIRMWARE"} and "_FW" in title:
        return True
    return False


def flatten_records(items: Iterable[Dict[str, Any]]) -> List[FirmwareRecord]:
    out: List[FirmwareRecord] = []
    for item in items:
        if not is_qpy_firmware_item(item):
            continue
        title = str(item.get("title") or "")
        raw_cat = str(item.get("download_category") or "")
        cat = "firmware" if raw_cat else ""
        desc = compact_text(str(item.get("description") or ""))
        item_id = item.get("id")
        versions = item.get("download_content") or []
        if not isinstance(versions, list):
            continue
        for v in versions:
            if not isinstance(v, dict):
                continue
            f = v.get("download_file") or {}
            url = str(f.get("url") or "").strip()
            if not url:
                continue
            ver = str(v.get("version") or item.get("version") or "").strip()
            version_title = compact_text(str(v.get("version_title") or title))
            rel = str(v.get("release_date") or item.get("new_date") or "").strip()
            size = int(f.get("filesize") or 0)
            ver_desc = compact_text(str(v.get("download_description") or desc))
            tag = (title + " " + ver).upper()
            is_beta = "BETA" in tag
            out.append(
                FirmwareRecord(
                    title=title,
                    version=ver,
                    version_title=version_title,
                    release_date=rel,
                    download_url=url,
                    file_size=size,
                    category=cat,
                    description=desc,
                    capability_description=ver_desc,
                    item_id=item_id,
                    is_beta=is_beta,
                )
            )
    return out


def matches_model(rec: FirmwareRecord, model: str) -> bool:
    m = normalize(model)
    if not m:
        return True
    blob = normalize(
        "%s %s %s %s %s"
        % (
            rec.title,
            rec.version_title,
            rec.description,
            rec.capability_description,
            rec.download_url,
        )
    )
    return m in blob


def filter_records(
    records: List[FirmwareRecord],
    model: str,
    keywords: List[str],
    stable_only: bool,
) -> List[FirmwareRecord]:
    kws = [k.strip().upper() for k in keywords if k.strip()]
    out: List[FirmwareRecord] = []
    for r in records:
        if stable_only and r.is_beta:
            continue
        if model and not matches_model(r, model):
            continue
        blob = (
            r.title
            + " "
            + r.version
            + " "
            + r.version_title
            + " "
            + r.description
            + " "
            + r.capability_description
        ).upper()
        if any(k not in blob for k in kws):
            continue
        out.append(r)
    return out


def contains_keyword(blob: str, keyword: str) -> bool:
    k = (keyword or "").strip()
    if not k:
        return True
    b = blob or ""
    if k.casefold() in b.casefold():
        return True
    kn = normalize(k)
    if not kn:
        return False
    return kn in normalize(b)


def evaluate_feature_match(rec: FirmwareRecord, required_features: List[str]) -> Dict[str, Any]:
    req = [x.strip() for x in required_features if x and x.strip()]
    blob = " ".join(
        [
            rec.title,
            rec.version,
            rec.version_title,
            rec.description,
            rec.capability_description,
            rec.download_url,
        ]
    )
    matched: List[str] = []
    missing: List[str] = []
    for rf in req:
        if contains_keyword(blob, rf):
            matched.append(rf)
        else:
            missing.append(rf)
    return {
        "required_features": req,
        "matched_features": matched,
        "missing_features": missing,
        "all_matched": len(missing) == 0,
    }


def build_version_capability_matrix(records: List[FirmwareRecord], required_features: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rec in sort_records(records):
        row = rec.as_dict()
        row["feature_match"] = evaluate_feature_match(rec, required_features)
        out.append(row)
    return out


def sort_records(records: List[FirmwareRecord]) -> List[FirmwareRecord]:
    return sorted(
        records,
        key=lambda x: (date_key(x.release_date), version_key(x.version), x.title),
        reverse=True,
    )


def pick_latest(records: List[FirmwareRecord]) -> Optional[FirmwareRecord]:
    s = sort_records(records)
    return s[0] if s else None


def human_size(n: int) -> str:
    if n <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    x = float(n)
    i = 0
    while x >= 1024 and i < len(units) - 1:
        x /= 1024.0
        i += 1
    return "%.2f %s" % (x, units[i])


def filename_from_url(url: str) -> str:
    p = urlparse(url)
    name = os.path.basename(p.path)
    return name or ("qpy_fw_%s.bin" % datetime.now().strftime("%Y%m%d_%H%M%S"))


def download_file(url: str, out_dir: str, timeout: int) -> str:
    os.makedirs(out_dir, exist_ok=True)
    name = filename_from_url(url)
    dest = os.path.join(out_dir, name)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    return dest


def extract_if_zip(path: str, out_dir: str) -> List[str]:
    if not path.lower().endswith(".zip"):
        return [path]
    os.makedirs(out_dir, exist_ok=True)
    files: List[str] = []
    with zipfile.ZipFile(path, "r") as zf:
        zf.extractall(out_dir)
    for root, _, names in os.walk(out_dir):
        for n in names:
            files.append(os.path.join(root, n))
    return files


def choose_flash_file(paths: List[str]) -> Optional[str]:
    candidates = [p for p in paths if os.path.isfile(p)]
    if not candidates:
        return None

    def score(p: str) -> Tuple[int, int]:
        ext = os.path.splitext(p)[1].lower()
        ext_rank = 0
        for i, x in enumerate(FLASH_EXT_PRIORITY):
            if ext == x:
                ext_rank = len(FLASH_EXT_PRIORITY) - i
                break
        size = os.path.getsize(p)
        return (ext_rank, size)

    candidates.sort(key=score, reverse=True)
    return candidates[0]


def resolve_flash_candidate(downloaded_file: str, extract_base: str) -> Tuple[List[str], str]:
    # First extraction pass.
    extracted = extract_if_zip(downloaded_file, extract_base)
    chosen = choose_flash_file(extracted) or ""
    if chosen and os.path.splitext(chosen)[1].lower() != ".zip":
        return extracted, chosen

    # If chosen is zip (or only zip files exist), try second extraction.
    zips = [p for p in extracted if p.lower().endswith(".zip") and os.path.isfile(p)]
    for z in zips:
        sub_dir = os.path.join(extract_base, "nested_" + os.path.splitext(os.path.basename(z))[0])
        nested = extract_if_zip(z, sub_dir)
        candidate = choose_flash_file(nested) or ""
        if candidate and os.path.splitext(candidate)[1].lower() != ".zip":
            return extracted + nested, candidate

    return extracted, chosen


def find_flash_tool(explicit: Optional[str]) -> Optional[str]:
    return resolve_windows_exe(
        exe_name="QuecPythonDownload.exe",
        start_file=__file__,
        explicit=explicit or "",
        env_vars=["QUECPYTHON_DOWNLOAD_EXE"],
    )


def run_flash(tool: str, port: str, baud: int, firmware_file: str, timeout: int) -> int:
    cmd = [tool, "-d", port, "-b", str(baud), "-f", firmware_file]
    p = subprocess.run(cmd, timeout=timeout)
    return int(p.returncode)


def run_powershell(script: str, timeout: int) -> str:
    cp = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()


def list_windows_serial_ports(timeout: int) -> List[Dict[str, str]]:
    ps = (
        "Get-CimInstance Win32_SerialPort | "
        "Sort-Object DeviceID | "
        "ForEach-Object { \"$($_.DeviceID)|$($_.Name)\" }"
    )
    raw = run_powershell(ps, timeout=max(6, timeout))
    rows: List[Dict[str, str]] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or "|" not in s:
            continue
        did, name = s.split("|", 1)
        did = did.strip().upper()
        if did.startswith("COM"):
            rows.append({"port": did, "name": name.strip()})
    return rows


def detect_at_port(ports: List[Dict[str, str]], prefer: str) -> str:
    pref = (prefer or "").strip().upper()
    if pref and any(x["port"] == pref for x in ports):
        return pref
    for rgx in [r"Quectel USB AT Port", r"\bAT Port\b", r"\bModem\b"]:
        for item in ports:
            if re.search(rgx, item["name"], flags=re.IGNORECASE):
                return item["port"]
    for item in ports:
        if "Quectel" in item["name"]:
            return item["port"]
    return pref


def wait_postflash_identity(prefer_port: str, baud: int, wait_seconds: int, step_seconds: int = 4) -> Dict[str, Any]:
    end = datetime.now().timestamp() + max(6, wait_seconds)
    attempts: List[Dict[str, Any]] = []
    last_identity: Dict[str, Any] = {}
    while datetime.now().timestamp() < end:
        ports = list_windows_serial_ports(timeout=8)
        picked = detect_at_port(ports, prefer=prefer_port)
        if picked:
            identity = read_at_identity(picked, baud=baud, timeout=10)
            identity["candidate_port"] = picked
            identity["ports_snapshot"] = ports
            attempts.append({"port": picked, "ok": bool(identity.get("ok")), "model": identity.get("model", ""), "revision": identity.get("revision", "")})
            last_identity = identity
            if identity.get("ok") and identity.get("model"):
                identity["attempts"] = attempts
                return identity
        else:
            attempts.append({"port": "", "ok": False, "model": "", "revision": "", "ports_snapshot": ports})
        subprocess.run(["powershell", "-NoProfile", "-Command", "Start-Sleep -Seconds %d" % max(1, step_seconds)])
    if last_identity:
        last_identity["attempts"] = attempts
        return last_identity
    return {"ok": False, "model": "", "revision": "", "raw": "", "attempts": attempts}


def read_at_identity(port: str, baud: int, timeout: int) -> Dict[str, str]:
    ps = (
        "$sp=$null; try {"
        f" $sp=New-Object System.IO.Ports.SerialPort '{port}',{baud},'None',8,'One';"
        " $sp.ReadTimeout=1500; $sp.WriteTimeout=1500;"
        " $sp.DtrEnable=$true; $sp.RtsEnable=$true;"
        " $sp.Open(); Start-Sleep -Milliseconds 200;"
        " $cmds=@('AT','ATI','AT+CGMR');"
        " foreach($c in $cmds){"
        "  $sp.DiscardInBuffer(); $sp.DiscardOutBuffer();"
        "  $sp.Write($c + \"`r`n\");"
        "  Start-Sleep -Milliseconds 550;"
        "  $resp=$sp.ReadExisting();"
        "  Write-Output ('=== ' + $c + ' ===');"
        "  if($resp){Write-Output ($resp -replace \"`r\",\"<CR>\" -replace \"`n\",\"<LF>\")} else {Write-Output '<empty>'}"
        " }"
        "} catch { Write-Output ('ERR: ' + $_.Exception.Message) }"
        " finally { if($sp -and $sp.IsOpen){ $sp.Close() } }"
    )
    raw = run_powershell(ps, timeout=max(8, timeout))
    ok = ("ERR:" not in raw) and ("OK" in raw)
    model = ""
    revision = ""
    cgmr = ""
    model_match = re.search(r"Quectel<CR><LF>\s*([A-Z0-9]+)\s*<CR><LF>", raw, flags=re.IGNORECASE)
    if model_match:
        model = model_match.group(1).upper()
    if not model:
        fallback_model = re.search(r"\b(EC[0-9]{3,}[A-Z0-9]*)\b", raw, flags=re.IGNORECASE)
        if fallback_model:
            model = fallback_model.group(1).upper()
    rev_match = re.search(r"Revision:\s*([A-Z0-9_]+)", raw, flags=re.IGNORECASE)
    if rev_match:
        revision = rev_match.group(1).upper()
    if not revision:
        qpy_match = re.search(r"\b([A-Z0-9_]*QPY[A-Z0-9_]*)\b", raw, flags=re.IGNORECASE)
        if qpy_match:
            revision = qpy_match.group(1).upper()
    cgmr_match = re.search(r"\+CGMR:\s*([^\r\n<]+)", raw, flags=re.I)
    if cgmr_match:
        cgmr = cgmr_match.group(1).strip().strip('"')
    return {
        "ok": ok,
        "port": port.upper(),
        "baud": str(baud),
        "model": model,
        "revision": revision,
        "cgmr": cgmr,
        "raw": raw,
    }


def check_model_match(rec: FirmwareRecord, query_model: str, identity: Dict[str, str]) -> Tuple[bool, str]:
    dev_model = normalize(identity.get("model", ""))
    dev_rev = normalize(identity.get("revision", ""))
    rec_blob = normalize(
        "%s %s %s %s %s %s"
        % (
            rec.title,
            rec.version,
            rec.version_title,
            rec.description,
            rec.capability_description,
            rec.download_url,
        )
    )
    query_norm = normalize(query_model or "")

    if not dev_model:
        return False, "Cannot parse device model from AT+CGMR response."
    if dev_model not in rec_blob and rec_blob not in dev_model:
        return (
            False,
            "Device model %s does not match selected firmware record %s."
            % (identity.get("model", ""), rec.title),
        )
    if query_norm and query_norm not in rec_blob and query_norm not in dev_rev and query_norm not in dev_model:
        return (
            False,
            "Requested model %s is inconsistent with device/firmware match result." % (query_model,),
        )
    return True, "Device model matches selected firmware."


def run_post_flash_smoke(
    smoke_script: str,
    follow_seconds: int,
    timeout: int,
    json_report: str,
    risk_mode: str,
    qpycom: Optional[str],
) -> Tuple[int, str]:
    cmd = [
        sys.executable,
        smoke_script,
        "--risk-mode",
        (risk_mode or "safe"),
        "--auto-ports",
        "--print-port-map",
        "--skip-deploy",
        "--follow-seconds",
        str(max(0, follow_seconds)),
        "--json-report",
        json_report,
    ]
    if qpycom:
        cmd.extend(["--qpycom", qpycom])
    cp = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(30, timeout),
    )
    output = ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()
    return int(cp.returncode), output


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Query/download/flash QuecPython firmware from official resource API."
    )
    p.add_argument("--model", help="Model keyword, for example EC800K, EG800AK, BG95M3.")
    p.add_argument("--keyword", action="append", default=[], help="Extra filter keyword.")
    p.add_argument("--category", type=int, default=15, help="Resource category id. Default 15.")
    p.add_argument("--page-size", type=int, default=30, help="API page size for crawling.")
    p.add_argument("--stable-only", action="store_true", help="Exclude beta firmware.")
    p.add_argument("--top", type=int, default=20, help="Max rows for list output.")
    p.add_argument("--latest-only", action="store_true", help="Only print latest record.")
    p.add_argument(
        "--enumerate-capabilities",
        action="store_true",
        help="Include all matched versions and their per-version capability descriptions.",
    )
    p.add_argument(
        "--require-feature",
        action="append",
        default=[],
        help="Required firmware capability keyword; can be specified multiple times.",
    )
    p.add_argument("--json", action="store_true", help="Output JSON.")
    p.add_argument("--open-url", action="store_true", help="Open first matched URL in browser.")
    p.add_argument("--download-dir", help="Download selected firmware package to this directory.")
    p.add_argument(
        "--select-version",
        help="Prefer exact version match (for example V0001). If absent, pick latest.",
    )
    p.add_argument(
        "--extract-dir",
        help="Extract zip package here (default: <download-dir>/extracted_<name>).",
    )
    p.add_argument("--flash", action="store_true", help="Flash selected file using QuecPythonDownload.exe.")
    p.add_argument("--flash-port", help="Flash serial port, for example COM7.")
    p.add_argument("--flash-baud", type=int, default=115200, help="Flash baudrate.")
    p.add_argument("--flash-tool", help="Path to QuecPythonDownload.exe.")
    p.add_argument(
        "--at-port",
        help="AT port for strict pre-flash model check (default uses --flash-port).",
    )
    p.add_argument("--at-baud", type=int, default=115200, help="AT baudrate for pre-flash check.")
    p.add_argument(
        "--no-strict-model-check",
        action="store_true",
        help="Disable strict pre-flash model verification via AT+CGMR.",
    )
    p.add_argument(
        "--strict-feature-check",
        action="store_true",
        help="When flashing, block auto-flash on feature mismatch and return candidate versions for manual selection.",
    )
    p.add_argument(
        "--choose-best-compatible",
        action="store_true",
        help="When strict feature check fails, auto-switch to the newest compatible version and continue.",
    )
    p.add_argument(
        "--post-smoke",
        action="store_true",
        help="Run device_smoke_test.py automatically after successful flash.",
    )
    p.add_argument(
        "--post-smoke-follow-seconds",
        type=int,
        default=8,
        help="Follow-seconds value used by post-flash smoke.",
    )
    p.add_argument(
        "--post-smoke-json",
        help="Custom JSON report path for post-flash smoke result.",
    )
    p.add_argument(
        "--post-smoke-risk-mode",
        choices=["safe", "standard", "aggressive"],
        default="safe",
        help="Risk mode for post-flash smoke run; default safe.",
    )
    p.add_argument(
        "--qpycom",
        help="Optional QPYcom.exe path passed to post-flash smoke.",
    )
    p.add_argument(
        "--post-version-wait-seconds",
        type=int,
        default=90,
        help="Seconds to wait for AT port re-enumeration and post-flash version read.",
    )
    p.add_argument("--timeout", type=int, default=40, help="Network/command timeout seconds.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    model = (args.model or "").strip()
    keywords = [k for k in args.keyword if k]
    required_features = [k.strip() for k in (args.require_feature or []) if k and k.strip()]

    endpoint, items = fetch_all_items(
        category=args.category,
        page_num=max(1, args.page_size),
        keywords=model,
        timeout=max(5, args.timeout),
    )
    all_records = flatten_records(items)
    matched = filter_records(all_records, model=model, keywords=keywords, stable_only=args.stable_only)
    matched = sort_records(matched)

    support = bool(matched)
    latest = pick_latest(matched)

    selected = latest
    if args.select_version:
        target = args.select_version.strip().upper()
        for r in matched:
            if r.version.upper() == target:
                selected = r
                break

    if args.open_url and selected:
        import webbrowser

        webbrowser.open(selected.download_url)

    payload = {
        "endpoint": endpoint,
        "query_model": model,
        "query_keywords": keywords,
        "required_features": required_features,
        "supports_quecpython": support,
        "matched_count": len(matched),
        "latest": latest.as_dict() if latest else None,
        "selected": selected.as_dict() if selected else None,
        "results": [x.as_dict() for x in matched[: max(1, args.top)]],
    }

    show_matrix = bool(args.enumerate_capabilities or args.flash or required_features)
    if show_matrix:
        matrix = build_version_capability_matrix(matched, required_features)
        payload["version_capability_matrix"] = matrix
        if required_features:
            compatible = [x for x in matrix if x.get("feature_match", {}).get("all_matched")]
            payload["compatible_candidates_count"] = len(compatible)
            payload["recommended_candidate"] = compatible[0] if compatible else None
    if selected:
        payload["selected_feature_match"] = evaluate_feature_match(selected, required_features)

    # In strict feature mode, do not fail with hard error.
    # Instead, block flash and return candidate versions for explicit user selection.
    if args.flash and args.strict_feature_check and required_features:
        sfm = payload.get("selected_feature_match") or {}
        if not bool(sfm.get("all_matched", False)):
            matrix = payload.get("version_capability_matrix") or []
            compatible = [x for x in matrix if x.get("feature_match", {}).get("all_matched")]
            payload["candidate_versions"] = [
                {
                    "version": x.get("version", ""),
                    "release_date": x.get("release_date", ""),
                    "version_title": x.get("version_title", ""),
                    "capability_description": x.get("capability_description", ""),
                }
                for x in compatible
            ]
            payload.setdefault("warnings", [])
            payload["warnings"].append(
                "Selected firmware does not satisfy all required features: %s"
                % ", ".join(sfm.get("missing_features") or [])
            )

            if args.choose_best_compatible and compatible:
                target_ver = str(compatible[0].get("version", "")).strip().upper()
                picked = None
                for rec in matched:
                    if rec.version.upper() == target_ver:
                        picked = rec
                        break
                if picked:
                    selected = picked
                    payload["selected"] = selected.as_dict()
                    payload["selected_feature_match"] = evaluate_feature_match(selected, required_features)
                    payload["auto_selected_candidate"] = selected.as_dict()
                    payload["auto_selection_reason"] = (
                        "strict_feature_check_mismatch_and_choose_best_compatible_enabled"
                    )
                    payload["warnings"].append(
                        "Auto-selected compatible version %s due to --choose-best-compatible."
                        % (selected.version,)
                    )
                else:
                    payload["flash_blocked"] = True
                    payload["flash_block_reason"] = "required_features_not_matched"
                    payload["selection_required"] = True
                    payload["user_action"] = "Please choose a compatible version via --select-version and retry flash."
                    payload["warnings"].append(
                        "Internal record mismatch while auto-selecting compatible version; manual selection required."
                    )
                    if args.json:
                        print(json.dumps(payload, ensure_ascii=False, indent=2))
                    else:
                        print("Flash blocked by strict feature check (no hard error).")
                        print("Choose one with --select-version and re-run.")
                    return 0
            else:
                payload["flash_blocked"] = True
                payload["flash_block_reason"] = "required_features_not_matched"
                payload["selection_required"] = True
                payload["user_action"] = "Please choose a compatible version via --select-version and retry flash."
                if not compatible:
                    payload["warnings"].append(
                        "No compatible versions found for all required features; adjust requirements or switch model."
                    )

                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    print("Flash blocked by strict feature check (no hard error).")
                    print("Missing features: %s" % ", ".join(sfm.get("missing_features") or []))
                    print("Candidate versions:")
                    for c in payload["candidate_versions"]:
                        print(
                            "- %s %s %s"
                            % (
                                c.get("version_title", "") or c.get("version", ""),
                                c.get("release_date", ""),
                                c.get("capability_description", "") or "<none>",
                            )
                        )
                    print("Choose one with --select-version and re-run.")
                return 0

    downloaded_file = ""
    extracted_files: List[str] = []
    flash_file = ""
    if args.download_dir and selected:
        downloaded_file = download_file(
            selected.download_url,
            out_dir=args.download_dir,
            timeout=max(5, args.timeout),
        )
        payload["downloaded_file"] = downloaded_file

        extract_dir = args.extract_dir
        if not extract_dir:
            base = os.path.splitext(os.path.basename(downloaded_file))[0]
            extract_dir = os.path.join(args.download_dir, "extracted_%s" % base)
        extracted_files, flash_file = resolve_flash_candidate(downloaded_file, extract_dir)
        payload["extracted_count"] = len(extracted_files)
        payload["flash_candidate"] = flash_file

    if args.flash:
        if not args.flash_port:
            print("Flash requires --flash-port.")
            return 2
        if not selected:
            print("No matched firmware to flash.")
            return 2
        if not downloaded_file:
            print("Flash requires --download-dir to fetch package first.")
            return 2
        tool = find_flash_tool(args.flash_tool)
        if not tool:
            print("QuecPythonDownload.exe not found. Pass --flash-tool.")
            return 2
        if not flash_file:
            print("No flash candidate found after extraction.")
            return 2

        at_port = (args.at_port or args.flash_port or "").strip().upper()
        pre_identity: Dict[str, Any] = {}
        if at_port:
            pre_identity = read_at_identity(at_port, args.at_baud, timeout=max(8, args.timeout))
            payload["preflash_identity"] = pre_identity
        else:
            payload["preflash_identity"] = {"ok": False, "reason": "no_at_port"}

        if not args.no_strict_model_check:
            if not at_port:
                print("Strict model check requires --at-port (or --flash-port).")
                return 2
            ok, reason = check_model_match(selected, model, pre_identity)
            payload["preflash_model_match"] = ok
            payload["preflash_model_match_reason"] = reason
            if not ok:
                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    print("Strict model check failed: %s" % reason)
                return 3

        if required_features:
            sfm = payload.get("selected_feature_match") or evaluate_feature_match(selected, required_features)
            payload["selected_feature_match"] = sfm
            if not sfm.get("all_matched", False):
                payload.setdefault("warnings", [])
                payload["warnings"].append(
                    "Selected firmware does not satisfy all required features: %s"
                    % ", ".join(sfm.get("missing_features") or [])
                )

        code = run_flash(
            tool=tool,
            port=args.flash_port,
            baud=args.flash_baud,
            firmware_file=flash_file,
            timeout=max(20, args.timeout * 3),
        )
        payload["flash_tool"] = tool
        payload["flash_port"] = args.flash_port
        payload["flash_baud"] = args.flash_baud
        payload["flash_exit_code"] = code
        if code != 0:
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Flash failed with exit code %d" % code)
            return code

        post_identity = wait_postflash_identity(
            prefer_port=at_port or args.flash_port,
            baud=args.at_baud,
            wait_seconds=max(20, int(args.post_version_wait_seconds)),
            step_seconds=4,
        )
        payload["postflash_identity"] = post_identity
        payload["version_compare"] = {
            "pre_model": payload.get("preflash_identity", {}).get("model", ""),
            "post_model": payload.get("postflash_identity", {}).get("model", ""),
            "pre_revision": payload.get("preflash_identity", {}).get("revision", ""),
            "post_revision": payload.get("postflash_identity", {}).get("revision", ""),
            "pre_cgmr": payload.get("preflash_identity", {}).get("cgmr", ""),
            "post_cgmr": payload.get("postflash_identity", {}).get("cgmr", ""),
        }
        payload["version_compare"]["revision_changed"] = (
            bool(payload["version_compare"]["pre_revision"])
            and bool(payload["version_compare"]["post_revision"])
            and payload["version_compare"]["pre_revision"] != payload["version_compare"]["post_revision"]
        )
        payload["version_compare"]["cgmr_changed"] = (
            bool(payload["version_compare"]["pre_cgmr"])
            and bool(payload["version_compare"]["post_cgmr"])
            and payload["version_compare"]["pre_cgmr"] != payload["version_compare"]["post_cgmr"]
        )
        if not post_identity.get("ok"):
            payload.setdefault("warnings", [])
            payload["warnings"].append(
                "Post-flash AT identity unavailable. Device may still be in download mode; power-cycle and re-check versions."
            )

        if args.post_smoke:
            smoke_script = str((Path(__file__).resolve().parent / "device_smoke_test.py").resolve())
            report_path = args.post_smoke_json
            if not report_path:
                base_dir = args.download_dir or os.getcwd()
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                report_path = os.path.join(base_dir, "post_flash_smoke_%s.json" % stamp)
            smoke_rc, smoke_out = run_post_flash_smoke(
                smoke_script=smoke_script,
                follow_seconds=args.post_smoke_follow_seconds,
                timeout=max(30, args.timeout * 3),
                json_report=report_path,
                risk_mode=args.post_smoke_risk_mode,
                qpycom=args.qpycom,
            )
            payload["post_smoke"] = {
                "script": smoke_script,
                "exit_code": smoke_rc,
                "json_report": report_path,
                "risk_mode": args.post_smoke_risk_mode,
                "ok": smoke_rc == 0,
                "output": smoke_out,
            }
            if smoke_rc != 0:
                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    print("Post-flash smoke failed. See report: %s" % report_path)
                return 4

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("Endpoint: %s" % endpoint)
    print("Model: %s" % (model or "<none>"))
    print("Supports QuecPython: %s" % ("YES" if support else "NO"))
    print("Matched records: %d" % len(matched))
    if selected:
        print("")
        print("Latest/Selected:")
        print("- title: %s" % selected.title)
        print("- version: %s" % selected.version)
        print("- release_date: %s" % selected.release_date)
        print("- file_size: %s" % human_size(selected.file_size))
        print("- url: %s" % selected.download_url)
    else:
        print("")
        print("No matching QuecPython firmware records.")

    if downloaded_file:
        print("")
        print("Downloaded: %s" % downloaded_file)
    if flash_file:
        print("Flash candidate: %s" % flash_file)
    if args.flash:
        print("Flash done.")
        vc = payload.get("version_compare", {})
        if vc:
            print("Pre/Post version compare:")
            print("- pre_model: %s" % (vc.get("pre_model", "") or "<unknown>"))
            print("- pre_revision: %s" % (vc.get("pre_revision", "") or "<unknown>"))
            print("- post_model: %s" % (vc.get("post_model", "") or "<unknown>"))
            print("- post_revision: %s" % (vc.get("post_revision", "") or "<unknown>"))
            print("- revision_changed: %s" % vc.get("revision_changed", False))
    if show_matrix:
        rows = payload.get("version_capability_matrix") or []
        print("")
        print("Version capability matrix:")
        for r in rows:
            cap = r.get("capability_description") or "<none>"
            print("- %s %s %s" % (r.get("title", ""), r.get("version", ""), r.get("release_date", "")))
            print("  capability: %s" % cap)
            if required_features:
                fm = r.get("feature_match") or {}
                print("  all_required_matched: %s" % bool(fm.get("all_matched", False)))
                miss = fm.get("missing_features") or []
                if miss:
                    print("  missing: %s" % ", ".join(miss))
        if required_features:
            sfm = payload.get("selected_feature_match", {})
            print("")
            print("Selected firmware feature check:")
            print("- all_required_matched: %s" % bool(sfm.get("all_matched", False)))
            print("- missing_features: %s" % ", ".join(sfm.get("missing_features") or []))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
