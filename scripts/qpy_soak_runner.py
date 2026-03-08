#!/usr/bin/env python3
"""
QuecPython soak runner.

Runs device_smoke_test.py in a loop to provide long-run validation evidence:
1) periodic AT/REPL/QPYcom health checks,
2) optional deploy probe cadence,
3) failure classification and stop thresholds,
4) structured per-iteration and summary reports.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


def utc_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def default_work_dir() -> str:
    here = Path(__file__).resolve().parent
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str((here / ".." / "review" / "soak_runs" / ("run_%s" % stamp)).resolve())


def default_smoke_script() -> str:
    return str((Path(__file__).resolve().parent / "device_smoke_test.py").resolve())


def classify_failure_text(text: str) -> Tuple[str, str]:
    t = (text or "").lower()
    if "resource is in use" in t:
        return ("PORT_IN_USE", "Serial port occupied by another process.")
    if "access is denied" in t or "failed to access" in t:
        return ("PORT_ACCESS", "Serial port cannot be accessed.")
    if "qpycom.exe not found" in t:
        return ("TOOL_MISSING", "QPYcom tool missing.")
    if "timeout" in t:
        return ("TIMEOUT", "Execution timed out.")
    if "importerror: no module named" in t:
        return ("IMPORT_PATH", "Import path issue on /usr.")
    if "traceback" in t:
        return ("TRACEBACK", "Device side traceback detected.")
    if "err:" in t:
        return ("GENERIC_ERROR", "Generic interaction error.")
    return ("UNKNOWN", "Unclassified failure.")


def classify_failed_steps(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in results:
        if bool(row.get("ok")):
            continue
        details = str(row.get("details") or "")
        code, hint = classify_failure_text(details)
        out.append(
            {
                "name": str(row.get("name") or ""),
                "stage": str(row.get("stage") or ""),
                "code": code,
                "hint": hint,
            }
        )
    return out


def should_skip_deploy(iteration: int, mode: str, interval: int) -> bool:
    if mode == "every":
        return False
    if mode == "never":
        return True
    if interval <= 0:
        return False
    return (iteration % interval) != 0


def run_smoke(
    smoke_script: str,
    iteration: int,
    root_dir: Path,
    args: argparse.Namespace,
    skip_deploy: bool,
) -> Dict[str, Any]:
    iter_dir = root_dir / ("iter_%04d" % iteration)
    iter_dir.mkdir(parents=True, exist_ok=True)
    json_report = iter_dir / "smoke.json"
    log_report = iter_dir / "smoke.log"

    cmd: List[str] = [
        sys.executable,
        smoke_script,
        "--json-report",
        str(json_report),
        "--log-file",
        str(log_report),
        "--timeout",
        str(max(8, int(args.smoke_timeout))),
        "--at-baud",
        str(int(args.at_baud)),
        "--repl-baud",
        str(int(args.repl_baud)),
        "--wait",
        str(max(0, int(args.wait))),
        "--risk-mode",
        str(args.risk_mode),
        "--ls-via",
        str(args.ls_via),
        "--deploy-via",
        str(args.deploy_via),
    ]
    if args.auto_ports:
        cmd.append("--auto-ports")
    else:
        if args.at_port:
            cmd.extend(["--at-port", args.at_port])
        if args.repl_port:
            cmd.extend(["--repl-port", args.repl_port])
    if args.print_port_map and iteration == 1:
        cmd.append("--print-port-map")
    if skip_deploy:
        cmd.append("--skip-deploy")
    if args.keep_probe:
        cmd.append("--keep-probe")
    if args.no_kill_qpycom:
        cmd.append("--no-kill-qpycom")
    if int(args.follow_seconds) > 0:
        cmd.extend(["--follow-seconds", str(int(args.follow_seconds))])
    if args.repl_log_cmd:
        cmd.extend(["--repl-log-cmd", str(args.repl_log_cmd)])
    if args.qpycom:
        cmd.extend(["--qpycom", str(args.qpycom)])

    started = time.time()
    started_at = utc_now()
    raw_output = ""
    exit_code = 1
    timeout_hit = False
    try:
        cp = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(15, int(args.smoke_timeout) + 30),
        )
        raw_output = ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()
        exit_code = int(cp.returncode)
    except subprocess.TimeoutExpired as te:
        timeout_hit = True
        raw_output = ((te.stdout or "") + "\n" + (te.stderr or "")).strip()
        exit_code = 124
    ended = time.time()
    ended_at = utc_now()

    smoke_data: Dict[str, Any] = {}
    if json_report.exists():
        try:
            smoke_data = json.loads(json_report.read_text(encoding="utf-8"))
        except Exception:
            smoke_data = {}

    results = smoke_data.get("results") if isinstance(smoke_data, dict) else []
    if not isinstance(results, list):
        results = []

    failed_steps = classify_failed_steps(results)
    ok = (exit_code == 0) and not failed_steps and not timeout_hit

    return {
        "iteration": iteration,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": round(ended - started, 3),
        "ok": ok,
        "exit_code": exit_code,
        "timeout": timeout_hit,
        "skip_deploy": skip_deploy,
        "command": cmd,
        "smoke_json_report": str(json_report),
        "smoke_log_file": str(log_report),
        "failed_steps": failed_steps,
        "failed_count": len(failed_steps),
        "pass_count": int(smoke_data.get("pass_count") or 0) if isinstance(smoke_data, dict) else 0,
        "raw_output_tail": raw_output[-4000:],
        "context": smoke_data.get("context") if isinstance(smoke_data, dict) else {},
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run periodic QuecPython soak checks via device_smoke_test.py.")
    p.add_argument(
        "--risk-mode",
        choices=["safe", "standard", "aggressive"],
        default="safe",
        help="Risk mode forwarded to device_smoke_test.py; safe is default.",
    )
    p.add_argument("--duration-seconds", type=int, default=3600, help="Total soak duration in seconds.")
    p.add_argument("--duration-hours", type=float, default=0.0, help="Alternative duration in hours (overrides seconds).")
    p.add_argument("--interval-seconds", type=int, default=300, help="Interval between iterations.")
    p.add_argument("--max-iterations", type=int, default=0, help="Optional hard cap. 0 means unlimited until duration.")
    p.add_argument("--work-dir", default=default_work_dir(), help="Output root directory for soak artifacts.")
    p.add_argument("--json-report", default="", help="Summary JSON output path (default: <work-dir>/soak_summary.json).")
    p.add_argument("--smoke-script", default=default_smoke_script(), help="Path to device_smoke_test.py.")
    p.add_argument("--smoke-timeout", type=int, default=40, help="Per smoke execution timeout seconds.")
    p.add_argument("--deploy-mode", choices=["every", "never", "interval"], default="interval")
    p.add_argument("--deploy-interval", type=int, default=6, help="When deploy-mode=interval, run deploy every N iterations.")
    p.add_argument("--max-failures", type=int, default=3, help="Abort when total failed iterations reaches this value. 0 disables.")
    p.add_argument(
        "--max-consecutive-failures",
        type=int,
        default=2,
        help="Abort when consecutive failures reaches this value. 0 disables.",
    )
    p.add_argument(
        "--abort-on-stage",
        action="append",
        default=[],
        help="Abort immediately when a failed step hits one of these stages (repeatable).",
    )
    p.add_argument("--auto-ports", action="store_true", help="Pass --auto-ports to smoke script.")
    p.add_argument("--print-port-map", action="store_true", help="Print serial role map in first iteration.")
    p.add_argument("--at-port", default="", help="AT port when not using --auto-ports.")
    p.add_argument("--at-baud", type=int, default=115200, help="AT baudrate.")
    p.add_argument("--repl-port", default="", help="REPL port when not using --auto-ports.")
    p.add_argument("--repl-baud", type=int, default=115200, help="REPL baudrate.")
    p.add_argument("--wait", type=int, default=2, help="QPYcom wait seconds.")
    p.add_argument(
        "--ls-via",
        choices=["repl", "qpycom"],
        default="repl",
        help="Directory list backend forwarded to device_smoke_test.py.",
    )
    p.add_argument(
        "--deploy-via",
        choices=["repl", "qpycom"],
        default="repl",
        help="Deploy backend forwarded to device_smoke_test.py.",
    )
    p.add_argument("--qpycom", default="", help="Optional QPYcom.exe path.")
    p.add_argument("--no-kill-qpycom", action="store_true", help="Pass through to smoke script.")
    p.add_argument("--follow-seconds", type=int, default=0, help="Follow REPL logs N seconds per iteration.")
    p.add_argument("--repl-log-cmd", default="", help="Command before follow logs.")
    p.add_argument("--keep-probe", action="store_true", help="Keep probe file for deploy-enabled iterations.")
    p.add_argument("--echo-smoke-output", action="store_true", help="Print smoke output tail each iteration.")
    p.add_argument("--json", action="store_true", help="Print final summary JSON to stdout.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    if float(args.duration_hours) > 0:
        duration_seconds = int(float(args.duration_hours) * 3600)
    else:
        duration_seconds = int(args.duration_seconds)
    duration_seconds = max(1, duration_seconds)
    interval_seconds = max(0, int(args.interval_seconds))
    abort_on_stages = {s.strip().upper() for s in args.abort_on_stage if s.strip()}

    smoke_script = str(Path(args.smoke_script).resolve())
    if not Path(smoke_script).is_file():
        print("Smoke script not found: %s" % smoke_script)
        return 2

    root_dir = Path(args.work_dir).resolve()
    root_dir.mkdir(parents=True, exist_ok=True)
    summary_path = Path(args.json_report).resolve() if args.json_report else (root_dir / "soak_summary.json")

    started_at = utc_now()
    start_mono = time.monotonic()
    deadline = start_mono + duration_seconds

    iterations: List[Dict[str, Any]] = []
    total_fail = 0
    consec_fail = 0
    stop_reason = "duration_reached"

    idx = 0
    while True:
        now = time.monotonic()
        if now >= deadline:
            stop_reason = "duration_reached"
            break
        if int(args.max_iterations) > 0 and idx >= int(args.max_iterations):
            stop_reason = "max_iterations_reached"
            break

        idx += 1
        skip_deploy = should_skip_deploy(
            iteration=idx,
            mode=args.deploy_mode,
            interval=max(1, int(args.deploy_interval)),
        )
        if str(args.risk_mode).lower() == "safe":
            skip_deploy = True
        result = run_smoke(smoke_script, idx, root_dir, args, skip_deploy=skip_deploy)
        iterations.append(result)

        if args.echo_smoke_output:
            print("")
            print("Iteration %d output tail:" % idx)
            print(result.get("raw_output_tail", ""))

        if result["ok"]:
            consec_fail = 0
        else:
            total_fail += 1
            consec_fail += 1

            fail_stages = {str(x.get("stage") or "").upper() for x in result.get("failed_steps", [])}
            if abort_on_stages and fail_stages.intersection(abort_on_stages):
                stop_reason = "abort_on_stage"
                break
            if int(args.max_failures) > 0 and total_fail >= int(args.max_failures):
                stop_reason = "max_failures_reached"
                break
            if int(args.max_consecutive_failures) > 0 and consec_fail >= int(args.max_consecutive_failures):
                stop_reason = "max_consecutive_failures_reached"
                break

        if interval_seconds > 0:
            left = deadline - time.monotonic()
            if left <= 0:
                stop_reason = "duration_reached"
                break
            time.sleep(min(interval_seconds, max(0, left)))

    ended_at = utc_now()
    pass_iters = len([x for x in iterations if x.get("ok")])
    fail_iters = len(iterations) - pass_iters
    overall_ok = fail_iters == 0

    summary: Dict[str, Any] = {
        "generated_at": ended_at,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds_target": duration_seconds,
        "duration_seconds_actual": round(time.monotonic() - start_mono, 3),
        "interval_seconds": interval_seconds,
        "iterations_total": len(iterations),
        "iterations_passed": pass_iters,
        "iterations_failed": fail_iters,
        "overall_ok": overall_ok,
        "stop_reason": stop_reason,
        "policy": "NO_COMMERCIAL_VERDICT",
        "smoke_script": smoke_script,
        "work_dir": str(root_dir),
        "config": {
            "deploy_mode": args.deploy_mode,
            "deploy_interval": int(args.deploy_interval),
            "max_failures": int(args.max_failures),
            "max_consecutive_failures": int(args.max_consecutive_failures),
            "abort_on_stage": sorted(abort_on_stages),
            "auto_ports": bool(args.auto_ports),
            "at_port": args.at_port,
            "repl_port": args.repl_port,
            "qpycom": args.qpycom,
            "risk_mode": args.risk_mode,
            "ls_via": args.ls_via,
            "deploy_via": args.deploy_via,
        },
        "iterations": iterations,
    }

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("Soak summary")
        print("Work dir: %s" % root_dir)
        print("Summary JSON: %s" % summary_path)
        print("Iterations: %d (pass=%d, fail=%d)" % (len(iterations), pass_iters, fail_iters))
        print("Stop reason: %s" % stop_reason)
        for row in iterations:
            mark = "PASS" if row.get("ok") else "FAIL"
            print("")
            print("[%s] Iteration %s" % (mark, row.get("iteration")))
            print("  started_at: %s" % row.get("started_at"))
            print("  duration_seconds: %s" % row.get("duration_seconds"))
            print("  skip_deploy: %s" % row.get("skip_deploy"))
            if not row.get("ok"):
                failed_steps = row.get("failed_steps") or []
                for fs in failed_steps:
                    print("  - %s/%s: %s" % (fs.get("stage", ""), fs.get("code", ""), fs.get("hint", "")))

    return 0 if overall_ok else 4


if __name__ == "__main__":
    raise SystemExit(main())
