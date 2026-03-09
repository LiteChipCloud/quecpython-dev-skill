#!/usr/bin/env python3
"""
Windows smoke test for QuecPython DTU workflows.

Flow:
1) Probe AT port with basic commands.
2) Probe REPL port with a token print.
3) List /usr via REPL (default) or QPYcom.
4) Optionally deploy a probe file to /usr (REPL default), import it, then cleanup.
5) Optionally capture continuous REPL logs into file.
6) Emit failure classification hints for fast triage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qpy_tool_paths import resolve_windows_exe


@dataclass
class StepResult:
    name: str
    ok: bool
    details: str
    stage: str = "GENERAL"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "stage": self.stage,
            "details": self.details,
        }


def run_cmd(cmd: List[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def run_powershell(script: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return run_cmd(["powershell", "-NoProfile", "-Command", script], timeout=timeout)


def has_qpycom_process() -> bool:
    cp = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq QPYcom.exe"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    text = ((cp.stdout or "") + "\n" + (cp.stderr or "")).lower()
    return "qpycom.exe" in text


def kill_qpycom(mode: str, allow_force: bool, allow_force_guard: bool) -> str:
    m = (mode or "").strip().lower()
    if m in {"off", "none", "disable"}:
        return "off"

    subprocess.run(
        ["taskkill", "/IM", "QPYcom.exe", "/T"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not has_qpycom_process():
        return "soft"

    if m == "force":
        if not allow_force:
            return "force_blocked"
        if not allow_force_guard:
            return "force_guard_blocked"
        subprocess.run(
            ["taskkill", "/IM", "QPYcom.exe", "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return "force"

    return "soft_unfinished"


def sanitize_port(port: str) -> str:
    p = port.strip().upper()
    if not p.startswith("COM"):
        raise ValueError("Serial port must look like COMx, got: %s" % port)
    return p


def list_windows_serial_ports(timeout: int) -> List[Dict[str, str]]:
    script = (
        "Get-CimInstance Win32_SerialPort | "
        "Sort-Object DeviceID | "
        "ForEach-Object { \"$($_.DeviceID)|$($_.Name)\" }"
    )
    cp = run_powershell(script, timeout=timeout)
    rows: List[Dict[str, str]] = []
    for line in (cp.stdout or "").splitlines():
        text = line.strip()
        if not text or "|" not in text:
            continue
        device_id, name = text.split("|", 1)
        device_id = device_id.strip().upper()
        name = name.strip()
        if device_id.startswith("COM"):
            rows.append({"port": device_id, "name": name})
    if rows:
        return rows

    # Fallback when Win32_SerialPort is empty on some driver stacks.
    cp2 = run_powershell("[System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object", timeout=timeout)
    for line in (cp2.stdout or "").splitlines():
        p = line.strip().upper()
        if p.startswith("COM"):
            rows.append({"port": p, "name": p})
    return rows


def list_ports_from_get_com(get_com: str, timeout: int) -> List[Dict[str, str]]:
    cp = run_cmd([get_com], timeout=timeout)
    text = (cp.stdout or "") + "\n" + (cp.stderr or "")
    rows: List[Dict[str, str]] = []
    for line in text.splitlines():
        s = line.strip()
        if "=" not in s or "COM" not in s.upper():
            continue
        left, right = s.split("=", 1)
        left = left.strip()
        right = right.strip()
        # Most outputs are COMx=<friendly-name>; keep both directions as fallback.
        if left.upper().startswith("COM"):
            rows.append({"port": left.upper(), "name": right})
        elif right.upper().startswith("COM"):
            rows.append({"port": right.upper(), "name": left})
    return rows


def detect_port_roles(ports: List[Dict[str, str]]) -> Dict[str, str]:
    roles: Dict[str, str] = {}

    def pick(regexes: List[str]) -> str:
        for rgx in regexes:
            for item in ports:
                name = item["name"]
                if re.search(rgx, name, flags=re.IGNORECASE):
                    return item["port"]
        return ""

    roles["at"] = pick([r"Quectel USB AT Port", r"\bAT Port\b", r"\bModem\b"])
    roles["diag"] = pick([r"\bDIAG\b", r"\bDM Port\b"])
    roles["repl"] = pick([r"\bREPL\b", r"\bUSB Serial\b", r"\bNMEA\b"])
    return roles


def format_port_map(ports: List[Dict[str, str]], roles: Dict[str, str]) -> str:
    lines: List[str] = ["Detected serial ports:"]
    for item in ports:
        tags: List[str] = []
        if roles.get("at") == item["port"]:
            tags.append("AT")
        if roles.get("diag") == item["port"]:
            tags.append("DIAG")
        if roles.get("repl") == item["port"]:
            tags.append("REPL")
        suffix = (" [" + ",".join(tags) + "]") if tags else ""
        lines.append("- %s: %s%s" % (item["port"], item["name"], suffix))
    return "\n".join(lines)


def escape_ps_dq(text: str) -> str:
    return text.replace("`", "``").replace('"', '`"')


def probe_at(port: str, baud: int, timeout: int) -> StepResult:
    script = (
        "$sp=$null; try {"
        f" $sp=New-Object System.IO.Ports.SerialPort '{port}',{baud},'None',8,'One';"
        " $sp.ReadTimeout=1500; $sp.WriteTimeout=1500;"
        " $sp.DtrEnable=$true; $sp.RtsEnable=$true;"
        " $sp.Open(); Start-Sleep -Milliseconds 200;"
        " $cmds=@('AT','ATI','AT+CSQ');"
        " foreach($c in $cmds){"
        "  $sp.DiscardInBuffer(); $sp.DiscardOutBuffer();"
        "  $sp.Write($c + \"`r`n\");"
        "  Start-Sleep -Milliseconds 500;"
        "  $resp=$sp.ReadExisting();"
        "  Write-Output ('=== ' + $c + ' ===');"
        "  if($resp){Write-Output ($resp -replace \"`r\",\"<CR>\" -replace \"`n\",\"<LF>\")} else {Write-Output '<empty>'}"
        " }"
        "} catch { Write-Output ('ERR: ' + $_.Exception.Message) }"
        " finally { if($sp -and $sp.IsOpen){ $sp.Close() } }"
    )
    cp = run_powershell(script, timeout=timeout)
    output = (cp.stdout or "") + (cp.stderr or "")
    ok = "OK" in output and "ERR:" not in output
    return StepResult("AT probe", ok, output.strip(), stage="AT")


def probe_repl(port: str, baud: int, timeout: int, token: str) -> StepResult:
    script = (
        "$sp=$null; try {"
        f" $sp=New-Object System.IO.Ports.SerialPort '{port}',{baud},'None',8,'One';"
        " $sp.ReadTimeout=1500; $sp.WriteTimeout=1500;"
        " $sp.DtrEnable=$true; $sp.RtsEnable=$true;"
        " $sp.Open(); Start-Sleep -Milliseconds 200;"
        " $sp.DiscardInBuffer(); $sp.DiscardOutBuffer();"
        " $sp.Write([string][char]3 + [string][char]3 + \"`r`n\");"
        " Start-Sleep -Milliseconds 200;"
        f" $sp.Write(\"print('{token}')`r`n\");"
        " Start-Sleep -Milliseconds 700;"
        " $resp=$sp.ReadExisting();"
        " if($resp){Write-Output ($resp -replace \"`r\",\"<CR>\" -replace \"`n\",\"<LF>\")} else {Write-Output '<empty>'}"
        "} catch { Write-Output ('ERR: ' + $_.Exception.Message) }"
        " finally { if($sp -and $sp.IsOpen){ $sp.Close() } }"
    )
    cp = run_powershell(script, timeout=timeout)
    output = (cp.stdout or "") + (cp.stderr or "")
    ok = token in output and "ERR:" not in output
    return StepResult("REPL probe", ok, output.strip(), stage="REPL")


def repl_exec(port: str, baud: int, timeout: int, command: str) -> StepResult:
    escaped_cmd = escape_ps_dq(command)
    ps = (
        "$sp=$null; try {"
        f" $sp=New-Object System.IO.Ports.SerialPort '{port}',{baud},'None',8,'One';"
        " $sp.ReadTimeout=1500; $sp.WriteTimeout=1500;"
        " $sp.DtrEnable=$true; $sp.RtsEnable=$true;"
        " $sp.Open(); Start-Sleep -Milliseconds 200;"
        " $sp.DiscardInBuffer(); $sp.DiscardOutBuffer();"
        " $sp.Write([string][char]3 + [string][char]3 + \"`r`n\");"
        " Start-Sleep -Milliseconds 150;"
        f" $sp.Write(\"{escaped_cmd}`r`n\");"
        " Start-Sleep -Milliseconds 900;"
        " $resp=$sp.ReadExisting();"
        " if($resp){Write-Output ($resp -replace \"`r\",\"<CR>\" -replace \"`n\",\"<LF>\")} else {Write-Output '<empty>'}"
        "} catch { Write-Output ('ERR: ' + $_.Exception.Message) }"
        " finally { if($sp -and $sp.IsOpen){ $sp.Close() } }"
    )
    cp = run_powershell(ps, timeout=timeout)
    output = (cp.stdout or "") + (cp.stderr or "")
    ok = "ERR:" not in output
    return StepResult("REPL exec", ok, output.strip(), stage="REPL")


def capture_repl_log(port: str, baud: int, seconds: int, timeout: int, initial_cmd: str) -> StepResult:
    escaped_cmd = escape_ps_dq(initial_cmd)
    ps = (
        "$sp=$null; try {"
        f" $sp=New-Object System.IO.Ports.SerialPort '{port}',{baud},'None',8,'One';"
        " $sp.ReadTimeout=400; $sp.WriteTimeout=1500;"
        " $sp.DtrEnable=$true; $sp.RtsEnable=$true;"
        " $sp.Open(); Start-Sleep -Milliseconds 200;"
        " $sp.DiscardInBuffer(); $sp.DiscardOutBuffer();"
        " $sp.Write([string][char]3 + [string][char]3 + \"`r`n\");"
        " Start-Sleep -Milliseconds 200;"
        f" if(\"{escaped_cmd}\" -ne \"\"){{ $sp.Write(\"{escaped_cmd}`r`n\") }}"
        f" $end=(Get-Date).AddSeconds({seconds});"
        " while((Get-Date) -lt $end){"
        "  if($sp.BytesToRead -gt 0){"
        "   $resp=$sp.ReadExisting();"
        "   if($resp){"
        "    $stamp=(Get-Date).ToString('yyyy-MM-ddTHH:mm:ss.fffK');"
        "    $line=$resp -replace \"`r\",\"<CR>\" -replace \"`n\",\"<LF>\";"
        "    Write-Output ($stamp + ' ' + $line)"
        "   }"
        "  }"
        "  Start-Sleep -Milliseconds 120;"
        " }"
        "} catch { Write-Output ('ERR: ' + $_.Exception.Message) }"
        " finally { if($sp -and $sp.IsOpen){ $sp.Close() } }"
    )
    cp = run_powershell(ps, timeout=max(timeout, seconds + 10))
    output = (cp.stdout or "") + (cp.stderr or "")
    ok = "ERR:" not in output
    return StepResult("REPL follow logs (%ds)" % seconds, ok, output.strip(), stage="RUNTIME_LOG")


def repl_ls_usr(port: str, baud: int, timeout: int) -> StepResult:
    res = repl_exec(
        port,
        baud,
        timeout,
        "import uos,ujson; print('ls_probe_ok', ujson.dumps(uos.listdir('/usr')))",
    )
    ok = res.ok and "ls_probe_ok" in res.details
    return StepResult("REPL ls /usr", ok, res.details, stage="REPL")


def repl_deploy_probe_file(port: str, baud: int, timeout: int, probe_name: str, probe_token: str) -> StepResult:
    remote_path = "/usr/%s" % probe_name
    cmd = (
        "import ql_fs; ql_fs.mkdirs('/usr'); "
        "f=open('%s','w'); f.write('print(\\'%s\\')\\n'); f.close(); print('deploy_probe_ok')"
        % (remote_path, probe_token)
    )
    res = repl_exec(port, baud, timeout, cmd)
    ok = res.ok and "deploy_probe_ok" in res.details
    return StepResult("REPL deploy probe file", ok, res.details, stage="REPL")


def find_qpycom(explicit: Optional[str]) -> Optional[str]:
    return resolve_windows_exe(
        exe_name="QPYcom.exe",
        start_file=__file__,
        explicit=explicit or "",
        env_vars=["QPYCOM_PATH"],
    )


def find_get_com(explicit_qpycom: Optional[str]) -> Optional[str]:
    candidates: List[str] = []
    if explicit_qpycom:
        candidates.append(str(Path(explicit_qpycom).resolve().parent / "get_com.exe"))
    env_qpy = os.environ.get("QPYCOM_PATH", "")
    if env_qpy:
        p = Path(env_qpy).expanduser()
        if p.is_dir():
            candidates.append(str(p / "get_com.exe"))
        else:
            candidates.append(str(p.parent / "get_com.exe"))
    for c in candidates:
        if c and Path(c).is_file():
            return str(Path(c).resolve())
    return resolve_windows_exe(
        exe_name="get_com.exe",
        start_file=__file__,
        env_vars=["GET_COM_PATH"],
    )


def qpycom_call(qpycom: str, args: List[str], timeout: int) -> StepResult:
    cp = run_cmd([qpycom] + args, timeout=timeout)
    output = (cp.stdout or "") + (cp.stderr or "")
    ok = cp.returncode == 0
    return StepResult("QPYcom %s" % " ".join(args), ok, output.strip(), stage="QPYCOM")


def write_probe_file(path: Path, token: str) -> None:
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("print('%s')\n" % token)


def parse_device_context(at_details: str) -> Dict[str, str]:
    model = ""
    revision = ""

    rev_match = re.search(r"Revision:\s*([^\s<]+)", at_details)
    if rev_match:
        revision = rev_match.group(1).strip()

    model_match = re.search(r"Quectel<CR><LF>\s*([A-Z0-9]+)\s*<CR><LF>", at_details)
    if model_match:
        model = model_match.group(1).strip()
    else:
        fallback_model = re.search(r"\b(EC\d+[A-Z0-9]*)\b", at_details)
        if fallback_model:
            model = fallback_model.group(1).strip()

    return {"model": model, "revision": revision}


def classify_failure(result: StepResult) -> Tuple[str, str]:
    d = result.details.lower()
    if "resource is in use" in d:
        return ("PORT_IN_USE", "Serial port is occupied; close monitor tools and retry.")
    if "failed to access" in d or "access is denied" in d:
        return (
            "PORT_ACCESS",
            "Serial port cannot be accessed; check port, driver, cable and permissions.",
        )
    if "qpycom.exe not found" in d:
        return ("TOOL_MISSING", "QPYcom.exe is missing; pass --qpycom or set QPYCOM_PATH.")
    if "timeout" in d:
        return ("TIMEOUT", "Step timed out; increase --timeout or check device responsiveness.")
    if "nameerror: name '???print'" in d or "nameerror: name 'ï»¿print'" in d:
        return (
            "ENCODING_BOM",
            "Possible BOM issue; use ASCII/UTF-8 without BOM for deployed scripts.",
        )
    if "importerror: no module named" in d:
        return ("IMPORT_PATH", "Import failed; verify /usr path and sys.path.append('/usr').")
    if "err:" in d:
        return ("GENERIC_ERROR", "Device interaction failed; inspect raw step output.")
    return ("UNKNOWN", "Unknown failure class; continue with stage-by-stage logs.")


def write_text_log(path: str, results: List[StepResult], summary: str) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("QuecPython device smoke results\n")
        f.write("Generated: %s\n\n" % datetime.now().isoformat(timespec="seconds"))
        for r in results:
            mark = "PASS" if r.ok else "FAIL"
            f.write("[%s] %s (%s)\n" % (mark, r.name, r.stage))
            if r.details:
                f.write(r.details)
                f.write("\n")
            f.write("\n")
        f.write(summary + "\n")


def write_json_report(path: str, results: List[StepResult], context: Dict[str, Any]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "context": context,
        "results": [r.as_dict() for r in results],
        "failed_count": len([r for r in results if not r.ok]),
        "pass_count": len([r for r in results if r.ok]),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run QuecPython DTU smoke tests (AT + REPL + optional QPYcom path)."
    )
    parser.add_argument(
        "--risk-mode",
        choices=["safe", "standard", "aggressive"],
        default="safe",
        help="Execution risk mode. safe disables QPYcom and deploy checks by default.",
    )
    parser.add_argument("--at-port", default="COM7", help="AT port, default COM7.")
    parser.add_argument("--at-baud", type=int, default=115200, help="AT baudrate.")
    parser.add_argument("--repl-port", default="COM6", help="REPL port, default COM6.")
    parser.add_argument("--repl-baud", type=int, default=115200, help="REPL baudrate.")
    parser.add_argument(
        "--auto-ports",
        action="store_true",
        help="Auto-detect Quectel AT/DIAG/REPL ports from Windows serial devices.",
    )
    parser.add_argument(
        "--print-port-map",
        action="store_true",
        help="Print discovered serial ports and inferred roles.",
    )
    parser.add_argument("--wait", type=int, default=2, help="QPYcom wait seconds.")
    parser.add_argument("--timeout", type=int, default=25, help="Per-step timeout seconds.")
    parser.add_argument("--qpycom", help="Path to QPYcom.exe.")
    parser.add_argument(
        "--enable-qpycom-check",
        action="store_true",
        help="Enable QPYcom ls probe in standard mode. Disabled by default for stability.",
    )
    parser.add_argument(
        "--ls-via",
        choices=["repl", "qpycom"],
        default="repl",
        help="Directory list backend. Default repl for host stability.",
    )
    parser.add_argument(
        "--deploy-via",
        choices=["repl", "qpycom"],
        default="repl",
        help="Probe deploy backend. Default repl to avoid QPYcom lock dependency.",
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Skip write/import/cleanup deploy checks and run read-only probes.",
    )
    parser.add_argument(
        "--keep-probe",
        action="store_true",
        help="Keep /usr/skill_probe.py after test (default removes it).",
    )
    parser.add_argument(
        "--no-kill-qpycom",
        action="store_true",
        help="Do not kill stale QPYcom.exe processes before testing.",
    )
    parser.add_argument(
        "--kill-qpycom-mode",
        choices=["soft", "force", "off"],
        default="soft",
        help="How to cleanup stale QPYcom.exe before testing. Default soft.",
    )
    parser.add_argument(
        "--allow-force-kill",
        action="store_true",
        help="Allow taskkill /F only when kill mode is force. Disabled by default for host stability.",
    )
    parser.add_argument(
        "--follow-seconds",
        type=int,
        default=0,
        help="Capture REPL logs for N seconds after smoke test (0 disables).",
    )
    parser.add_argument(
        "--repl-log-cmd",
        default="print('log_probe_start')",
        help="Command sent before REPL log follow starts.",
    )
    parser.add_argument("--log-file", help="Write full textual output to this file.")
    parser.add_argument("--json-report", help="Write structured JSON report to this file.")
    return parser


def main() -> int:
    if os.name != "nt":
        print("This smoke script currently supports Windows only.")
        return 2

    parser = build_parser()
    args = parser.parse_args()

    at_port = sanitize_port(args.at_port)
    repl_port = sanitize_port(args.repl_port)
    timeout = max(5, args.timeout)

    risk_mode = (args.risk_mode or "safe").strip().lower()
    policy_notes: List[str] = []
    qpycom_enabled = False
    effective_skip_deploy = bool(args.skip_deploy)

    kill_mode = "off" if args.no_kill_qpycom else args.kill_qpycom_mode
    if risk_mode == "safe":
        qpycom_enabled = False
        effective_skip_deploy = True
        kill_mode = "off"
        policy_notes.append(
            "safe mode: disable QPYcom operations, disable deploy/import checks, and disable QPYcom process kill."
        )
    elif risk_mode == "standard":
        qpycom_enabled = bool(args.enable_qpycom_check)
        if qpycom_enabled:
            policy_notes.append("standard mode: QPYcom checks enabled by --enable-qpycom-check.")
        else:
            policy_notes.append("standard mode: QPYcom checks disabled by default; REPL/AT probes only.")
    else:
        qpycom_enabled = True
        policy_notes.append("aggressive mode: advanced operations enabled; use only when stability is confirmed.")

    force_guard = (
        os.environ.get("QPY_FORCE_KILL_GUARD", "").strip() == "I_UNDERSTAND_RISK"
    )
    kill_result = kill_qpycom(
        kill_mode,
        allow_force=bool(args.allow_force_kill),
        allow_force_guard=force_guard,
    )
    if kill_result == "force_blocked":
        policy_notes.append("force kill blocked: set --allow-force-kill explicitly to permit taskkill /F.")
    if kill_result == "force_guard_blocked":
        policy_notes.append(
            "force kill blocked by guard: set env QPY_FORCE_KILL_GUARD=I_UNDERSTAND_RISK and --allow-force-kill."
        )

    results: List[StepResult] = []
    discovered_ports: List[Dict[str, str]] = []
    role_map: Dict[str, str] = {}
    qpycom = ""

    if policy_notes:
        results.append(StepResult("Execution policy", True, "\n".join(policy_notes), stage="POLICY"))

    if args.auto_ports:
        get_com = find_get_com(args.qpycom)
        if get_com:
            discovered_ports = list_ports_from_get_com(get_com, timeout)
        if not discovered_ports:
            discovered_ports = list_windows_serial_ports(timeout)
        role_map = detect_port_roles(discovered_ports)
        if role_map.get("at"):
            at_port = role_map["at"]
        if role_map.get("repl"):
            repl_port = role_map["repl"]

        map_text = format_port_map(discovered_ports, role_map) if discovered_ports else "No serial ports discovered."
        results.append(
            StepResult("Auto port detection", bool(discovered_ports), map_text, stage="PORT_DISCOVERY")
        )

    at_res = probe_at(at_port, args.at_baud, timeout)
    results.append(at_res)

    repl_token = "repl_probe_ok"
    repl_res = probe_repl(repl_port, args.repl_baud, timeout, repl_token)
    results.append(repl_res)

    env_res = repl_exec(
        repl_port,
        args.repl_baud,
        timeout,
        "import sys,uos; print('cwd', uos.getcwd()); print('sys_path', sys.path); print('has_main', '_main.py' in uos.listdir('/usr'))",
    )
    results.append(StepResult("REPL env snapshot", env_res.ok, env_res.details, stage="REPL"))

    qpycom_needed = (str(args.ls_via).lower() == "qpycom") or (
        (not effective_skip_deploy) and (str(args.deploy_via).lower() == "qpycom")
    )
    if qpycom_needed and not qpycom_enabled:
        results.append(
            StepResult(
                "QPYcom policy gate",
                False,
                "Requested qpycom backend but qpycom checks are disabled by risk-mode policy.",
                stage="POLICY",
            )
        )
    elif qpycom_needed:
        if has_qpycom_process():
            results.append(
                StepResult(
                    "QPYcom precheck",
                    False,
                    "QPYcom process already running; skip qpycom backend to avoid contention.",
                    stage="QPYCOM",
                )
            )
            qpycom = ""
        else:
            qpycom = find_qpycom(args.qpycom) or ""
            if not qpycom:
                results.append(
                    StepResult(
                        "QPYcom discovery",
                        False,
                        "QPYcom.exe not found. Pass --qpycom or set QPYCOM_PATH.",
                        stage="QPYCOM",
                    )
                )
            else:
                results.append(StepResult("QPYcom discovery", True, qpycom, stage="QPYCOM"))
    else:
        results.append(
            StepResult(
                "QPYcom policy gate",
                True,
                "QPYcom backend not required in this run.",
                stage="POLICY",
            )
        )

    if str(args.ls_via).lower() == "repl":
        results.append(repl_ls_usr(repl_port, args.repl_baud, timeout))
    else:
        if qpycom:
            ls_res = qpycom_call(
                qpycom,
                [
                    "-d",
                    repl_port,
                    "-b",
                    str(args.repl_baud),
                    "-w",
                    str(args.wait),
                    "-f",
                    "ls",
                    ":/usr",
                    "--no-follow",
                ],
                timeout=timeout,
            )
            results.append(ls_res)

    if not effective_skip_deploy:
        probe_name = "skill_probe.py"
        probe_token = "skill_probe_ok"
        deploy_ok = False

        if str(args.deploy_via).lower() == "repl":
            deploy_res = repl_deploy_probe_file(
                repl_port,
                args.repl_baud,
                timeout,
                probe_name=probe_name,
                probe_token=probe_token,
            )
            results.append(deploy_res)
            deploy_ok = deploy_res.ok
        else:
            if qpycom:
                with tempfile.TemporaryDirectory(prefix="qpy_smoke_") as tmp:
                    local_probe = Path(tmp) / probe_name
                    write_probe_file(local_probe, probe_token)

                    cp_res = qpycom_call(
                        qpycom,
                        [
                            "-d",
                            repl_port,
                            "-b",
                            str(args.repl_baud),
                            "-w",
                            str(args.wait),
                            "-f",
                            "cp",
                            str(local_probe),
                            ":/usr/%s" % probe_name,
                            "--no-follow",
                        ],
                        timeout=timeout,
                    )
                    results.append(cp_res)
                    deploy_ok = cp_res.ok
            else:
                results.append(
                    StepResult(
                        "QPYcom deploy gate",
                        False,
                        "deploy-via qpycom requested but qpycom is unavailable or blocked.",
                        stage="QPYCOM",
                    )
                )

        if deploy_ok:
            import_res = repl_exec(
                repl_port,
                args.repl_baud,
                timeout,
                "import sys; "
                "sys.path.append('/usr'); "
                "_m=sys.modules.pop('skill_probe', None); "
                "import skill_probe; print('import_probe_ok')",
            )
            import_ok = (
                import_res.ok
                and probe_token in import_res.details
                and "import_probe_ok" in import_res.details
            )
            results.append(StepResult("REPL import probe", import_ok, import_res.details, stage="REPL"))

            if not args.keep_probe:
                cleanup_res = repl_exec(
                    repl_port,
                    args.repl_baud,
                    timeout,
                    "import uos; uos.remove('/usr/skill_probe.py'); print('cleanup_ok')",
                )
                cleanup_ok = cleanup_res.ok and "cleanup_ok" in cleanup_res.details
                results.append(
                    StepResult("REPL cleanup probe file", cleanup_ok, cleanup_res.details, stage="REPL")
                )
        else:
            results.append(
                StepResult(
                    "REPL import probe",
                    False,
                    "Skipped because probe deploy step failed.",
                    stage="REPL",
                )
            )

    if args.follow_seconds > 0:
        follow_res = capture_repl_log(
            repl_port,
            args.repl_baud,
            args.follow_seconds,
            timeout,
            args.repl_log_cmd,
        )
        results.append(follow_res)

    print("QuecPython device smoke results:")
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print("")
        print("[%s] %s" % (mark, r.name))
        if r.details:
            print(r.details)

    failed = [r for r in results if not r.ok]
    print("")
    summary = "Summary: %d passed, %d failed" % (len(results) - len(failed), len(failed))
    print(summary)

    if args.print_port_map and discovered_ports:
        print("")
        print(format_port_map(discovered_ports, role_map))

    if failed:
        print("")
        print("Failure classification:")
        for item in failed:
            code, hint = classify_failure(item)
            print("- %s [%s]: %s" % (item.name, code, hint))

    context: Dict[str, Any] = {
        "risk_mode": risk_mode,
        "at_port": at_port,
        "at_baud": args.at_baud,
        "repl_port": repl_port,
        "repl_baud": args.repl_baud,
        "qpycom": qpycom,
        "qpycom_enabled": qpycom_enabled,
        "auto_ports": bool(args.auto_ports),
        "effective_skip_deploy": effective_skip_deploy,
        "ls_via": str(args.ls_via).lower(),
        "deploy_via": str(args.deploy_via).lower(),
        "policy_notes": policy_notes,
        "kill_qpycom_mode": kill_mode,
        "kill_qpycom_result": kill_result,
        "force_kill_guard_enabled": force_guard,
        "discovered_ports": discovered_ports,
        "role_map": role_map,
    }
    context.update(parse_device_context(at_res.details))

    if args.log_file:
        write_text_log(args.log_file, results, summary)
        print("Text log saved: %s" % args.log_file)
    if args.json_report:
        write_json_report(args.json_report, results, context)
        print("JSON report saved: %s" % args.json_report)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
