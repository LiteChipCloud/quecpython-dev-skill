#!/usr/bin/env python3
"""
Windows crash triage for QuecPython host workflows.

Read-only collector:
1) kernel bugcheck events and dump paths,
2) Kernel-Power 41 reboot evidence,
3) app crash signals (QPYcom / ARPProtection / heap),
4) security/driver signals related to USB and filter stack.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def run_cmd(cmd: List[str], timeout: int = 40) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def run_powershell_json(script: str, timeout: int = 40) -> List[Dict[str, Any]]:
    cp = run_cmd(["powershell", "-NoProfile", "-Command", script], timeout=timeout)
    text = ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except Exception:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def query_events(log_name: str, ids: List[int], days: int, max_events: int, where_clause: str = "") -> List[Dict[str, Any]]:
    id_expr = "@(" + ",".join(str(int(x)) for x in ids) + ")"
    where_extra = ""
    if where_clause.strip():
        where_extra = " | Where-Object { " + where_clause + " }"
    script = (
        "$start=(Get-Date).AddDays(-%d); "
        "$rows=Get-WinEvent -FilterHashtable @{LogName='%s'; StartTime=$start} -ErrorAction SilentlyContinue "
        "| Where-Object { %s -contains $_.Id }%s "
        "| Select-Object -First %d @{N='TimeCreated';E={$_.TimeCreated.ToString('yyyy-MM-ddTHH:mm:ss')}},Id,ProviderName,LevelDisplayName,Message; "
        "$rows | ConvertTo-Json -Depth 5 -Compress"
        % (days, log_name, id_expr, where_extra, max_events)
    )
    return run_powershell_json(script, timeout=60)


def query_provider_events(log_name: str, provider: str, days: int, max_events: int, where_clause: str = "") -> List[Dict[str, Any]]:
    where_extra = ""
    if where_clause.strip():
        where_extra = " | Where-Object { " + where_clause + " }"
    script = (
        "$start=(Get-Date).AddDays(-%d); "
        "$rows=Get-WinEvent -FilterHashtable @{LogName='%s'; ProviderName='%s'; StartTime=$start} -ErrorAction SilentlyContinue%s "
        "| Select-Object -First %d @{N='TimeCreated';E={$_.TimeCreated.ToString('yyyy-MM-ddTHH:mm:ss')}},Id,ProviderName,LevelDisplayName,Message; "
        "$rows | ConvertTo-Json -Depth 5 -Compress"
        % (days, log_name, provider, where_extra, max_events)
    )
    return run_powershell_json(script, timeout=60)


def parse_bugcheck(message: str) -> Dict[str, str]:
    msg = message or ""
    code = ""
    params = ""
    dump_path = ""
    m_cn = re.search(r"检测错误:\s*(0x[0-9A-Fa-f]+)\s*\(([^)]*)\)", msg)
    if m_cn:
        code = m_cn.group(1).upper()
        params = m_cn.group(2).strip()
    m_en = re.search(r"bugcheck was:\s*(0x[0-9A-Fa-f]+)\s*\(([^)]*)\)", msg, flags=re.I)
    if m_en and not code:
        code = m_en.group(1).upper()
        params = m_en.group(2).strip()
    d_cn = re.search(r"保存在:\s*([A-Za-z]:\\[^\r\n。]*?\.dmp)", msg, flags=re.I)
    if d_cn:
        dump_path = d_cn.group(1).strip()
    d_en = re.search(r"saved in:\s*([A-Za-z]:\\[^\r\n]*?\.dmp)", msg, flags=re.I)
    if d_en and not dump_path:
        dump_path = d_en.group(1).strip()
    return {"code": code, "params": params, "dump_path": dump_path}


def clean_text(text: str) -> str:
    t = text or ""
    t = t.replace("\u200e", "").replace("\u200f", "").replace("\ufeff", "")
    t = "".join(ch for ch in t if ch == "\n" or ch == "\r" or ord(ch) >= 32)
    return t


def normalize_event_rows(rows: List[Dict[str, Any]], include_message: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        msg = clean_text(str(row.get("Message") or ""))
        item: Dict[str, Any] = {
            "time": str(row.get("TimeCreated") or ""),
            "id": int(row.get("Id") or 0),
            "provider": str(row.get("ProviderName") or ""),
            "level": str(row.get("LevelDisplayName") or ""),
        }
        if include_message:
            item["message"] = msg
        else:
            item["message_head"] = msg[:220].replace("\r", " ").replace("\n", " ")
        out.append(item)
    return out


def list_minidumps(limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    base = Path("C:/Windows/Minidump")
    if not base.is_dir():
        return out
    files = sorted(base.glob("*.dmp"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files[: max(1, limit)]:
        st = p.stat()
        out.append(
            {
                "path": str(p),
                "size_bytes": int(st.st_size),
                "last_write_time": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return out


def build_assessment(
    bugchecks: List[Dict[str, Any]],
    app_crashes: List[Dict[str, Any]],
    filter_signals: List[Dict[str, Any]],
    hcmon_signals: List[Dict[str, Any]],
) -> Dict[str, Any]:
    reasons: List[str] = []
    recommendations: List[str] = []
    bug_codes = [str(x.get("bugcheck_code") or "").upper() for x in bugchecks if x.get("bugcheck_code")]
    same_139 = len([x for x in bug_codes if x == "0X00000139"])
    has_arp_heap = any(
        ("ARPProtection.exe" in str(x.get("message", "")))
        and ("0xc0000374" in str(x.get("message", "")).lower())
        for x in app_crashes
    )
    has_qpycom_crash = any("QPYcom" in str(x.get("message", "")) for x in app_crashes)
    has_filter = len(filter_signals) > 0
    has_hcmon = len(hcmon_signals) > 0

    if same_139 >= 2:
        reasons.append("近期重复出现 BugCheck 0x00000139，属于内核级异常。")
    elif "0X00000139" in bug_codes:
        reasons.append("出现 BugCheck 0x00000139，属于内核级异常。")
    if has_arp_heap:
        reasons.append("同时间窗出现 ARPProtection.exe 在 ntdll 的 heap 崩溃(0xc0000374)。")
    if has_filter or has_hcmon:
        reasons.append("系统日志出现安全/USB 过滤链路信号（BzProtect/sysdiag/hrdevmon/hcmon）。")
    if not has_qpycom_crash:
        reasons.append("未检出 QPYcom.exe 应用层崩溃记录，不能直接归因到单个用户态进程。")

    recommendations.append("将设备运维脚本保持在 safe 模式：禁用 QPYcom 路径、禁用强杀、禁用自动部署。")
    recommendations.append("避免并发串口访问：同一时刻仅保留一个串口占用进程（IDE/监视器/脚本三选一）。")
    recommendations.append("与安全软件策略联调：对 QPYcom、串口端口、Quectel 下载工具建立白名单或临时放行。")
    recommendations.append("故障复现期仅做只读探测（AT/REPL 查询），暂停烧录与批量 push。")
    recommendations.append("若仍蓝屏，使用 WinDbg 分析最新 minidump 的故障驱动模块后再恢复高风险操作。")

    return {
        "confidence": "medium",
        "root_cause_hypothesis": "kernel_or_driver_stack_instability_under_usb_serial_workload",
        "reasons": reasons,
        "recommendations": recommendations,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only Windows crash triage for QuecPython host operations.")
    p.add_argument("--days", type=int, default=2, help="Lookback window in days.")
    p.add_argument("--max-events", type=int, default=60, help="Max events per query.")
    p.add_argument("--minidump-limit", type=int, default=10, help="Max minidumps to include.")
    p.add_argument("--include-message", action="store_true", help="Include full event message text.")
    p.add_argument("--json-out", default="", help="Write JSON report to this path.")
    p.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    days = max(1, int(args.days))
    max_events = max(10, int(args.max_events))

    bugcheck_events = query_events(
        log_name="System",
        ids=[1001],
        days=days,
        max_events=max_events,
        where_clause="$_.ProviderName -eq 'Microsoft-Windows-WER-SystemErrorReporting'",
    )
    kernel_power_events = query_events(
        log_name="System",
        ids=[41],
        days=days,
        max_events=max_events,
    )
    app_crash_events = query_events(
        log_name="Application",
        ids=[1000, 1001],
        days=days,
        max_events=max_events,
        where_clause=(
            "$_.Message -match 'ARPProtection|QPYcom|QPYcom.exe|QuecPythonDownload|hrdevmon|BzProtect|sysdiag'"
        ),
    )
    filter_signals_raw = query_provider_events(
        log_name="System",
        provider="Microsoft-Windows-FilterManager",
        days=days,
        max_events=max_events * 2,
        where_clause="$_.Message -match 'BzProtect|sysdiag|hrdevmon|Huorong'",
    )
    hcmon_signals_raw = query_provider_events(
        log_name="System",
        provider="hcmon",
        days=days,
        max_events=max_events * 2,
        where_clause="$_.Message -match 'hrdevmon|USB driver|unrecognized'",
    )

    bugchecks: List[Dict[str, Any]] = []
    for row in bugcheck_events:
        msg = clean_text(str(row.get("Message") or ""))
        parsed = parse_bugcheck(msg)
        bugchecks.append(
            {
                "time": str(row.get("TimeCreated") or ""),
                "provider": str(row.get("ProviderName") or ""),
                "bugcheck_code": parsed["code"],
                "bugcheck_params": parsed["params"],
                "dump_path": parsed["dump_path"],
                "message": msg if args.include_message else msg[:220].replace("\r", " ").replace("\n", " "),
            }
        )

    payload: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window_days": days,
        "kernel_bugchecks": bugchecks,
        "kernel_power_41": normalize_event_rows(kernel_power_events, include_message=args.include_message),
        "app_crash_signals": normalize_event_rows(app_crash_events, include_message=args.include_message),
        "security_filter_signals": normalize_event_rows(filter_signals_raw, include_message=args.include_message),
        "usb_monitor_signals": normalize_event_rows(hcmon_signals_raw, include_message=args.include_message),
        "minidumps": list_minidumps(limit=max(1, int(args.minidump_limit))),
        "policy": "READ_ONLY_TRIAGE",
    }
    payload["assessment"] = build_assessment(
        bugchecks=payload["kernel_bugchecks"],
        app_crashes=payload["app_crash_signals"],
        filter_signals=payload["security_filter_signals"],
        hcmon_signals=payload["usb_monitor_signals"],
    )

    if args.json_out:
        out = Path(args.json_out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
    else:
        print("Crash triage summary")
        print("Window(days): %d" % days)
        print("Bugchecks: %d" % len(payload["kernel_bugchecks"]))
        print("Kernel-Power(41): %d" % len(payload["kernel_power_41"]))
        print("App crash signals: %d" % len(payload["app_crash_signals"]))
        print("Security filter signals: %d" % len(payload["security_filter_signals"]))
        print("USB monitor signals: %d" % len(payload["usb_monitor_signals"]))
        print("Minidumps: %d" % len(payload["minidumps"]))
        print("")
        print("Assessment:")
        for line in payload["assessment"]["reasons"]:
            print("- %s" % line)
        print("")
        print("Recommendations:")
        for line in payload["assessment"]["recommendations"]:
            print("- %s" % line)
        if args.json_out:
            print("")
            print("JSON report: %s" % str(Path(args.json_out).resolve()))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
