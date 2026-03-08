#!/usr/bin/env python3
"""
QuecPython device file-system CLI.

Capabilities:
1) tree: recursive listing from device path (default /usr) via REPL.
2) mkdir: create directory with ql_fs.mkdirs.
3) rm: remove file with uos.remove.
4) rmdir: remove directory with uos.rmdir.
5) run: execute script via example.exec.
6) push: upload local file to device path via REPL (default) or QPYcom.exe.
7) ls: list directory via REPL (default) or QPYcom.exe.

Safety:
By default, destructive operations are limited to /usr paths.
QPYcom backends are explicitly gated by --allow-qpycom-risk.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from qpy_tool_paths import resolve_windows_exe


def run_cmd(cmd: List[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def run_powershell(script: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run_cmd(["powershell", "-NoProfile", "-Command", script], timeout=timeout)


def sanitize_port(port: str) -> str:
    p = (port or "").strip().upper()
    if not p.startswith("COM"):
        raise ValueError("Serial port must look like COMx, got: %s" % port)
    return p


def normalize_remote_path(path: str) -> str:
    text = (path or "").strip().replace("\\", "/")
    if not text.startswith("/"):
        text = "/" + text
    text = re.sub(r"/{2,}", "/", text)
    return text


def validate_usr_path(path: str, allow_any_path: bool) -> None:
    p = normalize_remote_path(path)
    if allow_any_path:
        return
    if not (p == "/usr" or p.startswith("/usr/")):
        raise RuntimeError("Path must be under /usr unless --allow-any-path is set: %s" % p)


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
    cp2 = run_powershell("[System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object", timeout=timeout)
    for line in (cp2.stdout or "").splitlines():
        p = line.strip().upper()
        if p.startswith("COM"):
            rows.append({"port": p, "name": p})
    return rows


def detect_repl_port(ports: List[Dict[str, str]]) -> str:
    regexes = [r"\bREPL\b", r"\bUSB Serial\b", r"\bNMEA\b", r"Quectel USB MI05 COM Port"]
    for rgx in regexes:
        for item in ports:
            if re.search(rgx, item["name"], flags=re.IGNORECASE):
                return item["port"]
    for item in ports:
        if "Quectel" in item["name"]:
            return item["port"]
    return ""


def resolve_port(explicit_port: str, auto_port: bool, timeout: int) -> str:
    if not auto_port:
        return sanitize_port(explicit_port)
    ports = list_windows_serial_ports(timeout=max(8, timeout))
    port = detect_repl_port(ports)
    if not port:
        raise RuntimeError("Unable to infer REPL port from system serial ports.")
    return sanitize_port(port)


def find_qpycom(explicit: Optional[str]) -> Optional[str]:
    return resolve_windows_exe(
        exe_name="QPYcom.exe",
        start_file=__file__,
        explicit=explicit or "",
        env_vars=["QPYCOM_PATH"],
    )


def _escape_ps_sq(text: str) -> str:
    return text.replace("'", "''")


def is_port_busy_output(text: str) -> bool:
    t = (text or "").lower()
    return any(
        x in t
        for x in [
            "requested resource is in use",
            "access to the port",
            "is denied",
            "could not open port",
            "cannot open",
            "被占用",
        ]
    )


def repl_send_lines(
    port: str,
    baud: int,
    lines: List[str],
    timeout: int,
    line_delay_ms: int = 90,
    settle_ms: int = 800,
    busy_retries: int = 3,
    busy_wait_ms: int = 450,
) -> str:
    payload = json.dumps(lines, ensure_ascii=False)
    here_payload = "\n" + payload + "\n"
    ps = (
        "$sp=$null; try {"
        f" $sp=New-Object System.IO.Ports.SerialPort '{port}',{baud},'None',8,'One';"
        " $sp.ReadTimeout=1800; $sp.WriteTimeout=1800;"
        " $sp.DtrEnable=$true; $sp.RtsEnable=$true;"
        " $sp.Open(); Start-Sleep -Milliseconds 180;"
        " $sp.DiscardInBuffer(); $sp.DiscardOutBuffer();"
        " $sp.Write([string][char]3 + [string][char]3 + \"`r`n\");"
        " Start-Sleep -Milliseconds 150;"
        " $lines = ConvertFrom-Json @'"
        + here_payload
        + "'@;"
        " foreach($ln in $lines){"
        f"  $sp.Write([string]$ln + \"`r`n\"); Start-Sleep -Milliseconds {max(10, line_delay_ms)};"
        " }"
        f" Start-Sleep -Milliseconds {max(80, settle_ms)};"
        " $resp=$sp.ReadExisting();"
        " if($resp){Write-Output ($resp -replace \"`r\",\"<CR>\" -replace \"`n\",\"<LF>\")} else {Write-Output '<empty>'}"
        "} catch { Write-Output ('ERR: ' + $_.Exception.Message) }"
        " finally { if($sp -and $sp.IsOpen){ $sp.Close() } }"
    )
    retries = max(0, int(busy_retries))
    wait_ms = max(150, int(busy_wait_ms))
    last_text = ""
    for attempt in range(0, retries + 1):
        cp = run_powershell(ps, timeout=max(10, timeout))
        text = ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()
        last_text = text
        if not is_port_busy_output(text):
            return text
        if attempt < retries:
            time.sleep(wait_ms / 1000.0)
    return last_text


def qpycom_call(qpycom: str, args: List[str], timeout: int) -> Dict[str, Any]:
    cp = run_cmd([qpycom] + args, timeout=max(10, timeout))
    output = ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()
    return {"ok": cp.returncode == 0, "exit_code": cp.returncode, "output": output, "command": [qpycom] + args}


def single_quote_qpy(text: str) -> str:
    return (text or "").replace("\\", "/").replace("'", "\\'")


def extract_json_array(raw: str) -> tuple[List[Dict[str, Any]], bool]:
    text = raw or ""
    candidates = re.findall(r"(\[\{.*?\}\]|\[\s*\])", text, flags=re.S)
    if not candidates:
        return [], False
    for body in sorted(candidates, key=len, reverse=True):
        clean = body.replace("<CR><LF>", "")
        try:
            data = json.loads(clean)
        except Exception:
            continue
        if isinstance(data, list):
            rows: List[Dict[str, Any]] = [x for x in data if isinstance(x, dict)]
            return rows, True
    return [], False


def print_tree(rows: List[Dict[str, Any]], indent: int = 0) -> None:
    pad = "  " * indent
    for item in rows:
        name = str(item.get("name") or "")
        typ = str(item.get("type") or "")
        size = item.get("size")
        if typ == "dir":
            print("%s[%s]/" % (pad, name))
            sub = item.get("sub") or []
            if isinstance(sub, list):
                print_tree(sub, indent=indent + 1)
        else:
            suffix = "" if size in {None, ""} else " (%s B)" % size
            print("%s%s%s" % (pad, name, suffix))


def run_tree(port: str, baud: int, path: str, max_depth: int, timeout: int) -> Dict[str, Any]:
    safe_path = single_quote_qpy(path)
    code = (
        "def _qt(p,d,m):\n"
        " out=[]\n"
        " for f in uos.ilistdir(p):\n"
        "  n=f[0]\n"
        "  t=f[1]\n"
        "  s=f[3]\n"
        "  q=(p+'/'+n) if p!='/' else '/'+n\n"
        "  item={'name':n,'path':q,'size':s,'type':'dir' if t==16384 else 'file'}\n"
        "  if t==16384 and d<m:\n"
        "   item['sub']=_qt(q,d+1,m)\n"
        "  out.append(item)\n"
        " return out\n"
    )
    lines = [
        "import uos,ujson",
        "_code=%r" % code,
        "exec(_code)",
        "print(ujson.dumps(_qt('%s',0,%d)))" % (safe_path, max_depth),
    ]
    raw = repl_send_lines(port, baud, lines, timeout=max(12, timeout))
    rows, parsed = extract_json_array(raw)
    has_error = any(x in raw for x in ["ERR:", "Traceback", "ParserError", "At line:"])
    ok = (not has_error) and parsed
    return {"ok": ok, "raw": raw, "path": path, "max_depth": max_depth, "rows": rows}


def run_ls_repl(port: str, baud: int, path: str, timeout: int) -> Dict[str, Any]:
    safe_path = single_quote_qpy(path)
    code = (
        "def _qls(p):\n"
        " out=[]\n"
        " for _f in uos.ilistdir(p):\n"
        "  out.append({'name':_f[0],'type':'dir' if _f[1]==16384 else 'file','size':_f[3]})\n"
        " return out\n"
    )
    lines = [
        "import uos,ujson",
        "_code=%r" % code,
        "exec(_code)",
        "print(ujson.dumps(_qls('%s')))" % safe_path,
    ]
    raw = repl_send_lines(port, baud, lines, timeout=max(12, timeout))
    rows, parsed = extract_json_array(raw)
    has_error = any(x in raw for x in ["ERR:", "Traceback", "ParserError", "At line:"])
    ok = (not has_error) and parsed
    return {"ok": ok, "raw": raw, "path": path, "rows": rows}


def sanitize_remote_name(name: str) -> str:
    text = (name or "").strip().replace("\\", "/")
    final_name = text.split("/")[-1].strip()
    if not final_name or final_name in {".", ".."}:
        raise RuntimeError("Invalid remote file name: %s" % name)
    return final_name


def join_remote_path(remote_dir: str, remote_name: str) -> str:
    base = normalize_remote_path(remote_dir).rstrip("/")
    if not base:
        base = "/"
    if base == "/":
        return normalize_remote_path("/" + remote_name)
    return normalize_remote_path(base + "/" + remote_name)


def chunk_hex(data: bytes, chunk_size: int = 96) -> List[str]:
    size = max(32, int(chunk_size))
    chunks: List[str] = []
    for i in range(0, len(data), size):
        chunks.append(data[i : i + size].hex())
    return chunks


def run_push_repl(
    port: str,
    baud: int,
    src: str,
    remote_dir: str,
    remote_name: str,
    timeout: int,
) -> Dict[str, Any]:
    data = Path(src).read_bytes()
    chunks = chunk_hex(data, chunk_size=96)
    remote_path = join_remote_path(remote_dir, remote_name)
    remote_dir_qpy = single_quote_qpy(normalize_remote_path(remote_dir))
    remote_path_qpy = single_quote_qpy(remote_path)
    tmp_path_qpy = single_quote_qpy(remote_path + ".tmp")
    remote_name_qpy = single_quote_qpy(remote_name)
    tmp_name_qpy = single_quote_qpy(remote_name + ".tmp")

    code = (
        "def _qpush(path,tmp_path,dir_path,file_name,tmp_name,chunks):\n"
        " ql_fs.mkdirs(dir_path)\n"
        " entries=uos.listdir(dir_path)\n"
        " if tmp_name in entries:\n"
        "  uos.remove(tmp_path)\n"
        " f=open(tmp_path,'wb')\n"
        " w=0\n"
        " for h in chunks:\n"
        "  w += f.write(ubinascii.unhexlify(h))\n"
        " f.close()\n"
        " entries=uos.listdir(dir_path)\n"
        " if file_name in entries:\n"
        "  uos.remove(path)\n"
        " uos.rename(tmp_path,path)\n"
        " s=uos.stat(path)[6]\n"
        " return (w,s)\n"
    )
    lines: List[str] = [
        "import ql_fs,uos,ubinascii",
        "_code=%r" % code,
        "exec(_code)",
        "_chunks=[]",
    ]
    for hx in chunks:
        lines.append("_chunks.append('%s')" % hx)
    lines.extend(
        [
            "_ret=_qpush('%s','%s','%s','%s','%s',_chunks)"
            % (
                remote_path_qpy,
                tmp_path_qpy,
                remote_dir_qpy,
                remote_name_qpy,
                tmp_name_qpy,
            ),
            "print('push_ok %d %d' % (_ret[0],_ret[1]))",
        ]
    )

    estimated = int((len(lines) * 55) / 1000) + 12
    raw = repl_send_lines(
        port,
        baud,
        lines,
        timeout=max(timeout, estimated),
        line_delay_ms=55,
        settle_ms=1200,
    )
    has_error = any(x in raw for x in ["ERR:", "Traceback", "ParserError", "At line:"])
    m = re.search(r"push_ok\s+(\d+)\s+(\d+)", raw)
    written = int(m.group(1)) if m else -1
    remote_size = int(m.group(2)) if m else -1
    expected = len(data)
    ok = (not has_error) and bool(m) and written == expected and remote_size == expected
    return {
        "ok": ok,
        "raw": raw,
        "local_size": expected,
        "bytes_written": written,
        "remote_size": remote_size,
        "remote_path": remote_path,
        "chunks": len(chunks),
        "backend": "repl",
    }


def run_repl_op(port: str, baud: int, lines: List[str], success_token: str, timeout: int) -> Dict[str, Any]:
    raw = repl_send_lines(port, baud, lines, timeout=max(10, timeout))
    has_error = any(x in raw for x in ["ERR:", "Traceback", "ParserError", "At line:"])
    ok = (success_token in raw) and (not has_error)
    return {"ok": ok, "raw": raw}


def to_exec_path(path: str) -> str:
    p = normalize_remote_path(path)
    if p.startswith("/"):
        p = p[1:]
    return p.replace("\\", "/")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="QuecPython device /usr file-system CLI.")
    p.add_argument("--port", default="COM6", help="REPL port, default COM6.")
    p.add_argument("--auto-port", action="store_true", help="Auto-detect REPL port from system serial list.")
    p.add_argument("--baud", type=int, default=115200, help="REPL baudrate.")
    p.add_argument("--timeout", type=int, default=25, help="Timeout seconds.")
    p.add_argument("--allow-any-path", action="store_true", help="Allow non-/usr paths for operations.")
    p.add_argument(
        "--allow-qpycom-risk",
        action="store_true",
        help="Acknowledge QPYcom-related host stability risk and allow qpycom backend operations.",
    )
    p.add_argument(
        "--ls-via",
        choices=["repl", "qpycom"],
        default="repl",
        help="Backend used by ls action. Default repl to reduce host risk.",
    )
    p.add_argument(
        "--push-via",
        choices=["repl", "qpycom"],
        default="repl",
        help="Backend used by push action. Default repl to avoid QPYcom lock risk.",
    )
    p.add_argument("--qpycom", help="Path to QPYcom.exe.")
    p.add_argument("--wait", type=int, default=2, help="QPYcom wait seconds.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    sp = p.add_subparsers(dest="action", required=True)

    p_tree = sp.add_parser("tree", help="Recursive tree listing via REPL.")
    p_tree.add_argument("--path", default="/usr", help="Root path, default /usr.")
    p_tree.add_argument("--max-depth", type=int, default=6, help="Max recursion depth.")

    p_mkdir = sp.add_parser("mkdir", help="Create directory via ql_fs.mkdirs.")
    p_mkdir.add_argument("--path", required=True, help="Directory path to create.")

    p_rm = sp.add_parser("rm", help="Remove file via uos.remove.")
    p_rm.add_argument("--path", required=True, help="File path to remove.")

    p_rmdir = sp.add_parser("rmdir", help="Remove directory via uos.rmdir.")
    p_rmdir.add_argument("--path", required=True, help="Directory path to remove.")

    p_run = sp.add_parser("run", help="Run script via example.exec.")
    p_run.add_argument("--path", required=True, help="Script path, e.g. /usr/app.py")

    p_push = sp.add_parser("push", help="Upload file via REPL (default) or QPYcom.exe cp.")
    p_push.add_argument("--local", required=True, help="Local file path.")
    p_push.add_argument("--remote-dir", default="/usr", help="Remote directory, default /usr.")
    p_push.add_argument("--remote-name", default="", help="Remote file name (default local basename).")

    p_ls = sp.add_parser("ls", help="List directory via REPL (default) or QPYcom.exe ls.")
    p_ls.add_argument("--path", default="/usr", help="Remote path for ls, default /usr.")

    return p


def main() -> int:
    args = build_parser().parse_args()
    timeout = max(8, int(args.timeout))

    try:
        port = resolve_port(args.port, args.auto_port, timeout=timeout)
        baud = int(args.baud)
        if baud <= 0:
            raise RuntimeError("Invalid baudrate: %s" % args.baud)

        payload: Dict[str, Any] = {
            "action": args.action,
            "port": port,
            "baud": baud,
            "policy": "NO_COMMERCIAL_VERDICT",
            "allow_qpycom_risk": bool(args.allow_qpycom_risk),
        }

        if args.action == "tree":
            path = normalize_remote_path(args.path)
            validate_usr_path(path, args.allow_any_path)
            result = run_tree(port, baud, path, max_depth=max(0, int(args.max_depth)), timeout=timeout)
            payload.update(result)
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("Port: %s" % port)
                print("Path: %s" % path)
                if result["rows"]:
                    print_tree(result["rows"])
                else:
                    print("No entries or parse failed.")
                if not result["ok"]:
                    print("Raw output:")
                    print(result["raw"])
            return 0 if result["ok"] else 1

        if args.action == "mkdir":
            path = normalize_remote_path(args.path)
            validate_usr_path(path, args.allow_any_path)
            result = run_repl_op(
                port,
                baud,
                [
                    "import ql_fs",
                    "ql_fs.mkdirs('%s')" % single_quote_qpy(path),
                    "print('mkdir_ok')",
                ],
                success_token="mkdir_ok",
                timeout=timeout,
            )
            payload.update({"path": path, **result})
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("mkdir %s -> %s" % (path, "OK" if result["ok"] else "FAIL"))
                if not result["ok"]:
                    print(result["raw"])
            return 0 if result["ok"] else 1

        if args.action == "rm":
            path = normalize_remote_path(args.path)
            validate_usr_path(path, args.allow_any_path)
            result = run_repl_op(
                port,
                baud,
                [
                    "import uos",
                    "uos.remove('%s')" % single_quote_qpy(path),
                    "print('rm_ok')",
                ],
                success_token="rm_ok",
                timeout=timeout,
            )
            payload.update({"path": path, **result})
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("rm %s -> %s" % (path, "OK" if result["ok"] else "FAIL"))
                if not result["ok"]:
                    print(result["raw"])
            return 0 if result["ok"] else 1

        if args.action == "rmdir":
            path = normalize_remote_path(args.path)
            validate_usr_path(path, args.allow_any_path)
            result = run_repl_op(
                port,
                baud,
                [
                    "import uos",
                    "uos.rmdir('%s')" % single_quote_qpy(path),
                    "print('rmdir_ok')",
                ],
                success_token="rmdir_ok",
                timeout=timeout,
            )
            payload.update({"path": path, **result})
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("rmdir %s -> %s" % (path, "OK" if result["ok"] else "FAIL"))
                if not result["ok"]:
                    print(result["raw"])
            return 0 if result["ok"] else 1

        if args.action == "run":
            path = normalize_remote_path(args.path)
            validate_usr_path(path, args.allow_any_path)
            exec_path = to_exec_path(path)
            result = run_repl_op(
                port,
                baud,
                [
                    "import example",
                    "example.exec('%s')" % single_quote_qpy(exec_path),
                    "print('run_exec_sent')",
                ],
                success_token="run_exec_sent",
                timeout=timeout,
            )
            payload.update({"path": path, "exec_path": exec_path, **result})
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("run %s -> %s" % (path, "OK" if result["ok"] else "FAIL"))
                print(result["raw"])
            return 0 if result["ok"] else 1

        if args.action in {"push", "ls"}:
            if args.action == "ls" and str(args.ls_via).lower() == "repl":
                remote_path = normalize_remote_path(args.path)
                validate_usr_path(remote_path, args.allow_any_path)
                result = run_ls_repl(port, baud, remote_path, timeout=max(12, timeout))
                payload.update({"path": remote_path, "backend": "repl", **result})
                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    print("ls %s (backend=repl)" % remote_path)
                    print("Result: %s" % ("OK" if result["ok"] else "FAIL"))
                    if result.get("rows"):
                        print_tree(result["rows"], indent=0)
                    else:
                        print(result["raw"])
                return 0 if result["ok"] else 1

            if args.action == "push" and str(args.push_via).lower() == "repl":
                src = str(Path(args.local).resolve())
                if not Path(src).is_file():
                    raise RuntimeError("Local file not found: %s" % src)
                remote_dir = normalize_remote_path(args.remote_dir)
                validate_usr_path(remote_dir, args.allow_any_path)
                remote_name = sanitize_remote_name((args.remote_name or Path(src).name).strip() or Path(src).name)
                result = run_push_repl(port, baud, src, remote_dir, remote_name, timeout=max(15, timeout))
                payload.update({"local": src, "remote_dir": remote_dir, "remote_name": remote_name, **result})
                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    print("push %s -> %s (backend=repl)" % (src, result["remote_path"]))
                    print("Result: %s" % ("OK" if result["ok"] else "FAIL"))
                    print("Bytes: local=%d written=%d remote=%d" % (
                        result.get("local_size", -1),
                        result.get("bytes_written", -1),
                        result.get("remote_size", -1),
                    ))
                    if not result["ok"]:
                        print(result["raw"])
                return 0 if result["ok"] else 1

            if not args.allow_qpycom_risk:
                raise RuntimeError(
                    "QPYcom actions are gated by default. Re-run with --allow-qpycom-risk to continue."
                )
            qpycom = find_qpycom(args.qpycom)
            if not qpycom:
                raise RuntimeError("QPYcom.exe not found. Pass --qpycom or set QPYCOM_PATH.")
            payload["qpycom"] = qpycom
            wait = max(0, int(args.wait))

            if args.action == "push":
                src = str(Path(args.local).resolve())
                if not Path(src).is_file():
                    raise RuntimeError("Local file not found: %s" % src)
                remote_dir = normalize_remote_path(args.remote_dir)
                validate_usr_path(remote_dir, args.allow_any_path)
                remote_name = sanitize_remote_name((args.remote_name or Path(src).name).strip() or Path(src).name)
                dest = ":%s/%s" % (remote_dir, remote_name)
                result = qpycom_call(
                    qpycom,
                    [
                        "-d",
                        port,
                        "-b",
                        str(baud),
                        "-w",
                        str(wait),
                        "-f",
                        "cp",
                        src,
                        dest,
                        "--no-follow",
                    ],
                    timeout=max(15, timeout),
                )
                payload.update(
                    {
                        "local": src,
                        "remote_dir": remote_dir,
                        "remote_name": remote_name,
                        "dest": dest,
                        "backend": "qpycom",
                        **result,
                    }
                )
                if args.json:
                    print(json.dumps(payload, ensure_ascii=False, indent=2))
                else:
                    print("push %s -> %s (backend=qpycom)" % (src, dest))
                    print("Result: %s" % ("OK" if result["ok"] else "FAIL"))
                    print(result["output"])
                return 0 if result["ok"] else 1

            remote_path = normalize_remote_path(args.path)
            validate_usr_path(remote_path, args.allow_any_path)
            result = qpycom_call(
                qpycom,
                [
                    "-d",
                    port,
                    "-b",
                    str(baud),
                    "-w",
                    str(wait),
                    "-f",
                    "ls",
                    ":%s" % remote_path,
                    "--no-follow",
                ],
                timeout=max(15, timeout),
            )
            payload.update({"path": remote_path, "backend": "qpycom", **result})
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("ls %s (backend=qpycom)" % remote_path)
                print("Result: %s" % ("OK" if result["ok"] else "FAIL"))
                print(result["output"])
            return 0 if result["ok"] else 1

        raise RuntimeError("Unsupported action: %s" % args.action)
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
