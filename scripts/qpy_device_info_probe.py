#!/usr/bin/env python3
"""
QuecPython device info probe.

Collects and summarizes:
1) module model and firmware revision,
2) IMEI,
3) SIM status, ICCID, IMSI,
4) registration status,
5) PDP/IP type and IP address.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


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


def sanitize_port(port: str) -> str:
    p = (port or "").strip().upper()
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
    cp2 = run_powershell("[System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object", timeout=timeout)
    for line in (cp2.stdout or "").splitlines():
        p = line.strip().upper()
        if p.startswith("COM"):
            rows.append({"port": p, "name": p})
    return rows


def detect_at_port(ports: List[Dict[str, str]]) -> str:
    for rgx in [r"Quectel USB AT Port", r"\bAT Port\b", r"\bModem\b"]:
        for item in ports:
            if re.search(rgx, item["name"], flags=re.IGNORECASE):
                return item["port"]
    for item in ports:
        if "Quectel" in item["name"]:
            return item["port"]
    # Fallback: choose the highest COM number.
    ranked: List[Tuple[int, str]] = []
    for item in ports:
        m = re.match(r"COM(\d+)$", item.get("port", "").upper())
        if m:
            ranked.append((int(m.group(1)), item["port"].upper()))
    if ranked:
        ranked.sort()
        return ranked[-1][1]
    return ""


def detect_repl_port(ports: List[Dict[str, str]], at_port: str) -> str:
    for rgx in [r"\bREPL\b", r"\bUSB Serial\b", r"\bNMEA\b", r"\bMI05\b"]:
        for item in ports:
            if re.search(rgx, item["name"], flags=re.IGNORECASE):
                return item["port"]
    # Heuristic fallback: if AT is COMx and COM(x-1) exists, prefer it as REPL.
    m = re.match(r"COM(\d+)$", (at_port or "").upper())
    if m:
        cand = "COM%d" % (int(m.group(1)) - 1)
        if any(x["port"].upper() == cand for x in ports):
            return cand
    for item in ports:
        p = item["port"].upper()
        if p != (at_port or "").upper():
            return p
    return ""


def resolve_at_port(explicit: str, auto_port: bool, timeout: int) -> Tuple[str, List[Dict[str, str]]]:
    if not auto_port:
        return sanitize_port(explicit), []
    ports = list_windows_serial_ports(timeout=max(8, timeout))
    port = detect_at_port(ports)
    if not port:
        raise RuntimeError("Unable to infer AT port from serial device list.")
    return sanitize_port(port), ports


def resolve_repl_port(explicit: str, auto_port: bool, at_port: str, known_ports: List[Dict[str, str]], timeout: int) -> str:
    if not auto_port and explicit:
        return sanitize_port(explicit)
    ports = known_ports or list_windows_serial_ports(timeout=max(8, timeout))
    p = detect_repl_port(ports, at_port=at_port)
    if not p:
        raise RuntimeError("Unable to infer REPL port from serial device list.")
    return sanitize_port(p)


def run_at_batch(port: str, baud: int, commands: List[str], wait_ms: int, timeout: int) -> str:
    payload = json.dumps(commands, ensure_ascii=False)
    here_payload = "\n" + payload + "\n"
    ps = (
        "$sp=$null; try {"
        f" $sp=New-Object System.IO.Ports.SerialPort '{port}',{baud},'None',8,'One';"
        " $sp.ReadTimeout=1600; $sp.WriteTimeout=1600;"
        " $sp.DtrEnable=$true; $sp.RtsEnable=$true;"
        " $sp.Open(); Start-Sleep -Milliseconds 180;"
        " $cmds = ConvertFrom-Json @'"
        + here_payload
        + "'@;"
        " foreach($c in $cmds){"
        "  Write-Output ('__QPY_CMD_BEGIN__' + $c);"
        "  $sp.DiscardInBuffer(); $sp.DiscardOutBuffer();"
        "  $sp.Write($c + \"`r`n\");"
        f"  Start-Sleep -Milliseconds {max(100, wait_ms)};"
        "  $resp=$sp.ReadExisting();"
        "  if($resp){Write-Output ($resp -replace \"`r\",\"<CR>\" -replace \"`n\",\"<LF>\")} else {Write-Output '<empty>'};"
        "  Write-Output '__QPY_CMD_END__';"
        " }"
        "} catch { Write-Output ('ERR: ' + $_.Exception.Message) }"
        " finally { if($sp -and $sp.IsOpen){ $sp.Close() } }"
    )
    cp = run_powershell(ps, timeout=max(10, timeout))
    return ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()


def run_repl_lines(
    port: str,
    baud: int,
    lines: List[str],
    timeout: int,
    line_delay_ms: int = 80,
    settle_ms: int = 900,
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
        f" Start-Sleep -Milliseconds {max(120, settle_ms)};"
        " $resp=$sp.ReadExisting();"
        " if($resp){Write-Output ($resp -replace \"`r\",\"<CR>\" -replace \"`n\",\"<LF>\")} else {Write-Output '<empty>'}"
        "} catch { Write-Output ('ERR: ' + $_.Exception.Message) }"
        " finally { if($sp -and $sp.IsOpen){ $sp.Close() } }"
    )
    cp = run_powershell(ps, timeout=max(10, timeout))
    return ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()


def parse_sections(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    current_cmd = ""
    buf: List[str] = []
    for line in (raw or "").splitlines():
        text = line.strip()
        if text.startswith("__QPY_CMD_BEGIN__"):
            if current_cmd:
                out[current_cmd] = "\n".join(buf).strip()
            current_cmd = text.replace("__QPY_CMD_BEGIN__", "", 1)
            buf = []
            continue
        if text == "__QPY_CMD_END__":
            if current_cmd:
                out[current_cmd] = "\n".join(buf).strip()
            current_cmd = ""
            buf = []
            continue
        if current_cmd:
            buf.append(text)
    if current_cmd:
        out[current_cmd] = "\n".join(buf).strip()
    return out


def decode_markers(text: str) -> str:
    t = (text or "").replace("<CR><LF>", "\n").replace("<CR>", "\n").replace("<LF>", "\n")
    return t


def section_status(section_text: str) -> str:
    txt = decode_markers(section_text or "").upper()
    if "ERROR" in txt:
        return "ERROR"
    if "OK" in txt:
        return "OK"
    if "<EMPTY>" in txt or not txt.strip():
        return "EMPTY"
    return "UNKNOWN"


def response_lines(section_text: str, cmd: str) -> List[str]:
    lines: List[str] = []
    for raw in decode_markers(section_text).splitlines():
        s = raw.strip()
        if not s:
            continue
        if s == "<empty>":
            continue
        if s.upper() == cmd.upper():
            continue
        if s.startswith(">"):
            continue
        lines.append(s)
    return lines


def first_match(lines: List[str], pattern: str, flags: int = 0) -> str:
    rgx = re.compile(pattern, flags=flags)
    for line in lines:
        m = rgx.search(line)
        if m:
            return m.group(1) if m.groups() else m.group(0)
    return ""


def parse_model_ati(lines: List[str]) -> str:
    for line in lines:
        s = line.strip()
        if not s or s.upper() in {"OK", "ERROR", "QUECTEL"}:
            continue
        if re.fullmatch(r"[A-Z]{2}\d{3,}[A-Z0-9]*", s.upper()):
            return s.upper()
    m = first_match(lines, r"\b([A-Z]{2}\d{3,}[A-Z0-9]*)\b", flags=re.I)
    return m.upper() if m else ""


def parse_firmware(lines: List[str]) -> str:
    for line in lines:
        m = re.search(r"Revision:\s*([^\s]+)", line, flags=re.I)
        if m:
            return m.group(1).strip()
    for line in lines:
        if line.upper() not in {"OK", "ERROR"}:
            return line.strip()
    return ""


def parse_imei(lines_gsn: List[str], lines_cgsn: List[str], lines_cgsn_plain: List[str]) -> str:
    for group in (lines_gsn, lines_cgsn, lines_cgsn_plain):
        for line in group:
            m = re.search(r"\b(\d{14,17})\b", line)
            if m:
                return m.group(1)
    return ""


def parse_cpin(lines: List[str]) -> str:
    m = first_match(lines, r"\+CPIN:\s*([A-Z ]+)", flags=re.I)
    if m:
        return m.strip().upper()
    for line in lines:
        s = line.strip().upper()
        if s in {"READY", "SIM PIN", "SIM PUK", "NOT READY"}:
            return s
    return ""


def sim_inserted(cpin: str) -> Optional[bool]:
    s = (cpin or "").upper()
    if not s:
        return None
    if "NOT INSERTED" in s:
        return False
    if s in {"READY", "SIM PIN", "SIM PUK", "PH-NET PIN"}:
        return True
    if "NOT READY" in s:
        return None
    return None


def parse_iccid(lines: List[str]) -> str:
    m = first_match(lines, r"\+QCCID:\s*([0-9]{18,22})", flags=re.I)
    if m:
        return m
    for line in lines:
        m2 = re.search(r"\b([0-9]{18,22})\b", line)
        if m2:
            return m2.group(1)
    return ""


def parse_firmware_from_ati(lines: List[str]) -> str:
    m = first_match(lines, r"Revision:\s*([^\s]+)", flags=re.I)
    return m.strip() if m else ""


def parse_imsi(lines: List[str]) -> str:
    for line in lines:
        m = re.search(r"\b([0-9]{14,16})\b", line)
        if m:
            return m.group(1)
    return ""


def parse_reg_status(lines: List[str], prefix: str) -> Dict[str, Any]:
    # +CEREG: <n>,<stat>[,...]
    for line in lines:
        m = re.search(r"\+%s:\s*([0-9]+)\s*,\s*([0-9]+)" % prefix, line, flags=re.I)
        if m:
            n = int(m.group(1))
            stat = int(m.group(2))
            return {"n": n, "stat": stat}
    return {}


def is_registered(stat: Optional[int]) -> Optional[bool]:
    if stat is None:
        return None
    if stat in {1, 5}:
        return True
    if stat in {0, 2, 3, 4}:
        return False
    return None


def parse_qiact(lines: List[str], prefer_cid: int) -> Dict[str, Any]:
    # +QIACT: <cid>,<state>,<type>,<addr>[,...]
    contexts: List[Dict[str, Any]] = []
    for line in lines:
        m = re.search(
            r"\+QIACT:\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*\"?([A-Z0-9]+)\"?\s*,\s*\"?([^\",]+)\"?",
            line,
            flags=re.I,
        )
        if not m:
            continue
        cid = int(m.group(1))
        state = int(m.group(2))
        ip_type = m.group(3).upper()
        ip_addr = m.group(4).strip()
        contexts.append(
            {
                "cid": cid,
                "state": state,
                "ip_type": ip_type,
                "ip_address": ip_addr,
            }
        )
    if not contexts:
        return {}
    # Prefer active + requested CID
    for c in contexts:
        if c["cid"] == prefer_cid and c["state"] == 1 and c["ip_address"] not in {"0.0.0.0", "::"}:
            return {"source": "QIACT", **c, "contexts": contexts}
    # Any active context
    for c in contexts:
        if c["state"] == 1 and c["ip_address"] not in {"0.0.0.0", "::"}:
            return {"source": "QIACT", **c, "contexts": contexts}
    # Fallback first context
    return {"source": "QIACT", **contexts[0], "contexts": contexts}


def parse_cgpaddr(lines: List[str], prefer_cid: int) -> Dict[str, Any]:
    # +CGPADDR: <cid>,<PDP_addr_1>[,<PDP_addr_2>]
    items: List[Dict[str, Any]] = []
    for line in lines:
        m = re.search(r"\+CGPADDR:\s*([0-9]+)\s*,\s*\"?([^\",]+)\"?", line, flags=re.I)
        if not m:
            continue
        cid = int(m.group(1))
        ip = m.group(2).strip()
        ip_type = "IPV6" if ":" in ip else "IP"
        items.append({"cid": cid, "ip_type": ip_type, "ip_address": ip})
    if not items:
        return {}
    for x in items:
        if x["cid"] == prefer_cid and x["ip_address"] not in {"0.0.0.0", "::"}:
            return {"source": "CGPADDR", **x, "contexts": items}
    for x in items:
        if x["ip_address"] not in {"0.0.0.0", "::"}:
            return {"source": "CGPADDR", **x, "contexts": items}
    return {"source": "CGPADDR", **items[0], "contexts": items}


def valid_qpy_value(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, (int, float)) and int(v) == -1:
        return False
    s = str(v).strip()
    if not s:
        return False
    if s in {"-1", "None", "null", "0.0.0.0", "::"}:
        return False
    return True


def parse_repl_json(raw: str) -> Dict[str, Any]:
    text = decode_markers(raw)
    m = re.search(r"QPY_REPL_JSON_BEGIN\s*(\{.*?\})\s*QPY_REPL_JSON_END", text, flags=re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_repl_datacall(info: Any) -> Dict[str, Any]:
    if not isinstance(info, list) or len(info) < 3:
        return {}
    try:
        cid = int(info[0])
        ip_type_code = int(info[1])
    except Exception:
        cid = None
        ip_type_code = None
    ip_type_map = {0: "IP", 1: "IPV6", 2: "IPV4V6"}
    result: Dict[str, Any] = {
        "cid": cid,
        "ip_type": ip_type_map.get(ip_type_code, str(ip_type_code)),
        "contexts": [],
    }
    # ipType 0/1 usually returns [state, reconnect, addr, dns1, dns2]
    if len(info) >= 3 and isinstance(info[2], list):
        seg = info[2]
        if len(seg) >= 3:
            try:
                result["state"] = int(seg[0])
            except Exception:
                result["state"] = None
            result["ip_address"] = str(seg[2])
            result["contexts"].append(
                {
                    "ip_type": "IP" if ip_type_code == 0 else ("IPV6" if ip_type_code == 1 else "IP"),
                    "state": result["state"],
                    "ip_address": result["ip_address"],
                }
            )
    # ipType 2 may provide dual segments
    if ip_type_code == 2:
        dual_ctx: List[Dict[str, Any]] = []
        for seg_idx, kind in [(2, "IP"), (3, "IPV6")]:
            if len(info) > seg_idx and isinstance(info[seg_idx], list) and len(info[seg_idx]) >= 3:
                seg = info[seg_idx]
                try:
                    st = int(seg[0])
                except Exception:
                    st = None
                dual_ctx.append({"ip_type": kind, "state": st, "ip_address": str(seg[2])})
        if dual_ctx:
            result["contexts"] = dual_ctx
            preferred = next((x for x in dual_ctx if x["state"] == 1 and valid_qpy_value(x["ip_address"])), dual_ctx[0])
            result["state"] = preferred.get("state")
            result["ip_address"] = preferred.get("ip_address", "")
            result["ip_type"] = preferred.get("ip_type", result["ip_type"])
    return result


def probe_repl_info(port: str, baud: int, timeout: int) -> Dict[str, Any]:
    code = (
        "import ujson\n"
        "r={}\n"
        "try:\n"
        " import modem\n"
        " r['modem_model']=modem.getDevModel()\n"
        " r['modem_fw']=modem.getDevFwVersion()\n"
        " r['modem_imei']=modem.getDevImei()\n"
        "except Exception as e:\n"
        " r['modem_error']=repr(e)\n"
        "try:\n"
        " import sim\n"
        " r['sim_status']=sim.getStatus()\n"
        " r['sim_iccid']=sim.getIccid()\n"
        " r['sim_imsi']=sim.getImsi()\n"
        "except Exception as e:\n"
        " r['sim_error']=repr(e)\n"
        "try:\n"
        " import net\n"
        " r['net_state']=net.getState()\n"
        "except Exception as e:\n"
        " r['net_error']=repr(e)\n"
        "try:\n"
        " import dataCall\n"
        " r['datacall_ipv4']=dataCall.getInfo(1,0)\n"
        " r['datacall_ipv6']=dataCall.getInfo(1,1)\n"
        " r['datacall_dual']=dataCall.getInfo(1,2)\n"
        "except Exception as e:\n"
        " r['datacall_error']=repr(e)\n"
        "print('QPY_REPL_JSON_BEGIN')\n"
        "print(ujson.dumps(r))\n"
        "print('QPY_REPL_JSON_END')\n"
    )
    raw = run_repl_lines(
        port,
        baud,
        ["_code=%r" % code, "exec(_code)"],
        timeout=max(10, timeout),
    )
    data = parse_repl_json(raw)
    return {"ok": bool(data), "raw": raw, "data": data}


def build_diagnostics(
    *,
    cpin: str,
    sim_present: Optional[bool],
    reg_source: str,
    reg_stat: Optional[int],
    registered: Optional[bool],
    iccid: str,
    ip_info: Dict[str, Any],
    sections: Dict[str, str],
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    st = {k: section_status(v) for k, v in sections.items()}

    if st.get("AT") not in {"OK", "UNKNOWN"}:
        issues.append(
            {
                "code": "AT_BASELINE_FAIL",
                "severity": "high",
                "possible_causes": [
                    "AT口被占用（监控工具/脚本占用）",
                    "串口号或波特率不正确",
                    "设备处于重启或异常状态",
                ],
                "suggestions": [
                    "关闭占用串口的软件后重试",
                    "确认AT口与波特率（常见115200）",
                    "执行软重启 AT+CFUN=1,1 后再探测",
                ],
            }
        )

    if sim_present is False or "NOT INSERTED" in (cpin or ""):
        issues.append(
            {
                "code": "SIM_NOT_INSERTED",
                "severity": "high",
                "possible_causes": [
                    "SIM卡未插好/接触不良",
                    "卡槽硬件问题",
                ],
                "suggestions": [
                    "重新插卡并重启模组",
                    "更换SIM卡或确认卡座硬件",
                ],
            }
        )

    if sim_present is True and not iccid and st.get("AT+QCCID") == "ERROR" and st.get("AT+CCID") == "ERROR":
        issues.append(
            {
                "code": "ICCID_UNAVAILABLE",
                "severity": "medium",
                "possible_causes": [
                    "当前DTU固件不支持QCCID/CCID AT命令",
                    "AT命令集被裁剪",
                ],
                "suggestions": [
                    "改用对应固件文档支持的SIM信息命令",
                    "如果业务必须获取ICCID，切换支持该命令的固件版本",
                ],
            }
        )

    if registered is False:
        base_causes = [
            "SIM卡欠费/停机/流量不可用",
            "信号弱或天线问题",
            "运营商制式/频段不匹配",
            "网络附着尚未完成",
        ]
        suggestions = [
            "等待30-60秒后重试驻网查询",
            "检查天线与信号质量（AT+CSQ）",
            "确认SIM卡状态（可换卡验证）",
        ]
        if reg_source == "CEREG" and reg_stat in {3, 4}:
            base_causes.append("被网络拒绝注册或未知故障")
            suggestions.append("抓取详细拒绝原因并核查运营商策略")
        issues.append(
            {
                "code": "NOT_REGISTERED",
                "severity": "high",
                "possible_causes": base_causes,
                "suggestions": suggestions,
            }
        )

    ip_addr = str(ip_info.get("ip_address") or "")
    if registered is True and (not ip_addr or ip_addr in {"0.0.0.0", "::"}):
        issues.append(
            {
                "code": "NO_PDP_IP",
                "severity": "medium",
                "possible_causes": [
                    "PDP上下文未激活",
                    "APN未配置或配置错误",
                    "数据业务受限（卡套餐/运营商策略）",
                    "当前固件AT命令集对QIACT/CGPADDR返回受限",
                ],
                "suggestions": [
                    "检查附着状态 AT+CGATT?",
                    "配置并激活PDP（例如 AT+QICSGP / AT+QIACT=1）后重查",
                    "确认SIM卡数据业务可用（你这次换卡就是有效手段）",
                ],
            }
        )

    if st.get("AT+GSN") == "ERROR" and st.get("AT+CGSN=1") == "ERROR" and st.get("AT+CGSN") == "OK":
        issues.append(
            {
                "code": "IMEI_CMD_VARIANT",
                "severity": "low",
                "possible_causes": [
                    "固件仅支持AT+CGSN，不支持AT+GSN或AT+CGSN=1",
                ],
                "suggestions": [
                    "后续固定使用AT+CGSN读取IMEI",
                ],
            }
        )

    return issues


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Probe QuecPython device basic info by AT commands.")
    p.add_argument("--at-port", default="COM7", help="AT port, default COM7.")
    p.add_argument("--auto-port", action="store_true", help="Auto-detect AT port.")
    p.add_argument("--baud", type=int, default=115200, help="AT baudrate.")
    p.add_argument("--wait-ms", type=int, default=650, help="Per-command wait milliseconds.")
    p.add_argument("--timeout", type=int, default=30, help="Execution timeout seconds.")
    p.add_argument("--cid", type=int, default=1, help="Preferred PDP context id for IP query.")
    p.add_argument("--repl-port", default="COM6", help="REPL port for fallback query. Default COM6.")
    p.add_argument("--auto-repl-port", action="store_true", help="Auto-detect REPL port for fallback.")
    p.add_argument("--repl-baud", type=int, default=115200, help="REPL baudrate.")
    p.add_argument("--no-repl-fallback", action="store_true", help="Disable REPL fallback when AT data is incomplete.")
    p.add_argument("--json", action="store_true", help="Output JSON.")
    p.add_argument("--include-raw", action="store_true", help="Include raw command responses.")
    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        at_port, ports = resolve_at_port(args.at_port, args.auto_port, timeout=max(8, args.timeout))
        commands = [
            "AT",
            "ATI",
            "AT+CGMR",
            "AT+GSN",
            "AT+CGSN=1",
            "AT+CGSN",
            "AT+CPIN?",
            "AT+QCCID",
            "AT+CCID",
            "AT+CIMI",
            "AT+CEREG?",
            "AT+CGREG?",
            "AT+CREG?",
            "AT+QIACT?",
            "AT+CGPADDR=%d" % int(args.cid),
        ]
        raw = run_at_batch(
            at_port,
            baud=int(args.baud),
            commands=commands,
            wait_ms=max(100, int(args.wait_ms)),
            timeout=max(10, int(args.timeout)),
        )
        sections = parse_sections(raw)
        if not sections:
            if "ERR:" in raw:
                err_line = ""
                for ln in raw.splitlines():
                    if "ERR:" in ln:
                        err_line = ln.strip()
                        break
                raise RuntimeError("AT batch failed: %s" % (err_line or raw[:200]))
            raise RuntimeError("AT batch returned no command sections.")
        if ("ATI" not in sections) and ("AT+CPIN?" not in sections):
            raise RuntimeError("AT response missing critical sections; possible wrong port or busy port.")

        ati_lines = response_lines(sections.get("ATI", ""), "ATI")
        cgmr_lines = response_lines(sections.get("AT+CGMR", ""), "AT+CGMR")
        gsn_lines = response_lines(sections.get("AT+GSN", ""), "AT+GSN")
        cgsn_lines = response_lines(sections.get("AT+CGSN=1", ""), "AT+CGSN=1")
        cgsn_plain_lines = response_lines(sections.get("AT+CGSN", ""), "AT+CGSN")
        cpin_lines = response_lines(sections.get("AT+CPIN?", ""), "AT+CPIN?")
        qccid_lines = response_lines(sections.get("AT+QCCID", ""), "AT+QCCID")
        ccid_lines = response_lines(sections.get("AT+CCID", ""), "AT+CCID")
        cimi_lines = response_lines(sections.get("AT+CIMI", ""), "AT+CIMI")
        cereg_lines = response_lines(sections.get("AT+CEREG?", ""), "AT+CEREG?")
        cgreg_lines = response_lines(sections.get("AT+CGREG?", ""), "AT+CGREG?")
        creg_lines = response_lines(sections.get("AT+CREG?", ""), "AT+CREG?")
        qiact_lines = response_lines(sections.get("AT+QIACT?", ""), "AT+QIACT?")
        cgpaddr_lines = response_lines(sections.get("AT+CGPADDR=%d" % int(args.cid), ""), "AT+CGPADDR=%d" % int(args.cid))

        model = parse_model_ati(ati_lines)
        firmware = parse_firmware_from_ati(ati_lines) or parse_firmware(cgmr_lines)
        imei = parse_imei(gsn_lines, cgsn_lines, cgsn_plain_lines)
        cpin = parse_cpin(cpin_lines)
        sim_present = sim_inserted(cpin)
        iccid = parse_iccid(qccid_lines) or parse_iccid(ccid_lines)
        imsi = parse_imsi(cimi_lines)

        cereg = parse_reg_status(cereg_lines, "CEREG")
        cgreg = parse_reg_status(cgreg_lines, "CGREG")
        creg = parse_reg_status(creg_lines, "CREG")

        reg_source = ""
        reg_stat: Optional[int] = None
        if "stat" in cereg:
            reg_source = "CEREG"
            reg_stat = int(cereg["stat"])
        elif "stat" in cgreg:
            reg_source = "CGREG"
            reg_stat = int(cgreg["stat"])
        elif "stat" in creg:
            reg_source = "CREG"
            reg_stat = int(creg["stat"])
        registered = is_registered(reg_stat)

        ip_info = parse_qiact(qiact_lines, prefer_cid=int(args.cid))
        if not ip_info:
            ip_info = parse_cgpaddr(cgpaddr_lines, prefer_cid=int(args.cid))

        field_sources: Dict[str, str] = {
            "module_model": "AT:ATI",
            "firmware_version": "AT:ATI/CGMR",
            "imei": "AT:CGSN/GSN",
            "sim_status": "AT:CPIN",
            "iccid": "AT:QCCID/CCID",
            "imsi": "AT:CIMI",
            "registration": "AT:CEREG/CGREG/CREG",
            "ip": "AT:QIACT/CGPADDR",
        }

        repl_result: Dict[str, Any] = {}
        repl_used = False
        need_repl = (not args.no_repl_fallback) and (
            (not valid_qpy_value(model))
            or (not valid_qpy_value(firmware))
            or (not valid_qpy_value(imei))
            or (not valid_qpy_value(iccid))
            or (not valid_qpy_value(imsi))
            or (not valid_qpy_value(ip_info.get("ip_address", "") if isinstance(ip_info, dict) else ""))
        )
        if need_repl:
            try:
                repl_port = resolve_repl_port(
                    explicit=args.repl_port,
                    auto_port=args.auto_repl_port or args.auto_port,
                    at_port=at_port,
                    known_ports=ports,
                    timeout=max(8, args.timeout),
                )
                repl_result = probe_repl_info(repl_port, baud=int(args.repl_baud), timeout=max(10, args.timeout))
                repl_result["repl_port"] = repl_port
                if repl_result.get("ok"):
                    repl_used = True
                    rd = repl_result.get("data", {})

                    if (not valid_qpy_value(model)) and valid_qpy_value(rd.get("modem_model")):
                        model = str(rd.get("modem_model"))
                        field_sources["module_model"] = "REPL:modem.getDevModel"
                    if (not valid_qpy_value(firmware)) and valid_qpy_value(rd.get("modem_fw")):
                        firmware = str(rd.get("modem_fw"))
                        field_sources["firmware_version"] = "REPL:modem.getDevFwVersion"
                    if (not valid_qpy_value(imei)) and valid_qpy_value(rd.get("modem_imei")):
                        imei = str(rd.get("modem_imei"))
                        field_sources["imei"] = "REPL:modem.getDevImei"

                    if (not valid_qpy_value(iccid)) and valid_qpy_value(rd.get("sim_iccid")):
                        iccid = str(rd.get("sim_iccid"))
                        field_sources["iccid"] = "REPL:sim.getIccid"
                    if (not valid_qpy_value(imsi)) and valid_qpy_value(rd.get("sim_imsi")):
                        imsi = str(rd.get("sim_imsi"))
                        field_sources["imsi"] = "REPL:sim.getImsi"

                    if not cpin and valid_qpy_value(rd.get("sim_status")):
                        status_map = {
                            0: "NOT INSERTED",
                            1: "READY",
                        }
                        st_raw = rd.get("sim_status")
                        try:
                            st_num = int(st_raw)
                            cpin = status_map.get(st_num, "SIM_STATUS_%d" % st_num)
                            sim_present = (st_num == 1)
                            field_sources["sim_status"] = "REPL:sim.getStatus"
                        except Exception:
                            pass

                    if (not valid_qpy_value(ip_info.get("ip_address", "") if isinstance(ip_info, dict) else "")):
                        dc_candidates = [
                            rd.get("datacall_ipv4"),
                            rd.get("datacall_dual"),
                            rd.get("datacall_ipv6"),
                        ]
                        for c in dc_candidates:
                            parsed = parse_repl_datacall(c)
                            if parsed and valid_qpy_value(parsed.get("ip_address", "")):
                                ip_info = {
                                    "source": "REPL:dataCall.getInfo",
                                    "cid": parsed.get("cid"),
                                    "state": parsed.get("state"),
                                    "ip_type": parsed.get("ip_type", ""),
                                    "ip_address": parsed.get("ip_address", ""),
                                    "contexts": parsed.get("contexts", []),
                                }
                                field_sources["ip"] = "REPL:dataCall.getInfo"
                                break
            except Exception as repl_err:
                repl_result = {"ok": False, "error": str(repl_err)}

        payload: Dict[str, Any] = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "policy": "NO_COMMERCIAL_VERDICT",
            "detected_at_port": at_port,
            "detected_ports": ports,
            "device": {
                "module_model": model,
                "firmware_version": firmware,
                "imei": imei,
            },
            "sim": {
                "cpin": cpin,
                "sim_inserted": sim_present,
                "iccid": iccid,
                "imsi": imsi,
            },
            "registration": {
                "registered": registered,
                "source": reg_source,
                "stat": reg_stat,
                "cereg": cereg,
                "cgreg": cgreg,
                "creg": creg,
            },
            "data_context": {
                "cid_preferred": int(args.cid),
                "ip_type": ip_info.get("ip_type", ""),
                "ip_address": ip_info.get("ip_address", ""),
                "cid": ip_info.get("cid"),
                "state": ip_info.get("state"),
                "source": ip_info.get("source", ""),
                "contexts": ip_info.get("contexts", []),
            },
            "availability": {
                "imei_available": bool(imei),
                "iccid_available": bool(iccid),
                "imsi_available": bool(imsi),
                "ip_available": bool(payload_ip := (ip_info.get("ip_address", "") if isinstance(ip_info, dict) else "")),
            },
            "field_sources": field_sources,
            "repl_fallback": {
                "attempted": need_repl,
                "used": repl_used,
                "ok": bool(repl_result.get("ok")),
                "repl_port": repl_result.get("repl_port", ""),
                "error": repl_result.get("error", ""),
            },
        }
        payload["diagnostics"] = build_diagnostics(
            cpin=cpin,
            sim_present=sim_present,
            reg_source=reg_source,
            reg_stat=reg_stat,
            registered=registered,
            iccid=iccid,
            ip_info=ip_info if isinstance(ip_info, dict) else {},
            sections=sections,
        )
        if args.include_raw:
            payload["raw"] = {"batch_output": raw, "sections": sections, "repl": repl_result}

        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print("AT Port: %s" % at_port)
            print("Model: %s" % (model or "<unknown>"))
            print("Firmware: %s" % (firmware or "<unknown>"))
            print("IMEI: %s" % (imei or "<unknown>"))
            print("SIM inserted: %s" % sim_present)
            print("CPIN: %s" % (cpin or "<unknown>"))
            print("ICCID: %s" % (iccid or "<unknown>"))
            print("IMSI: %s" % (imsi or "<unknown>"))
            print("Registered: %s (%s stat=%s)" % (registered, reg_source or "N/A", reg_stat))
            print("IP: type=%s, addr=%s, cid=%s, source=%s" % (
                payload["data_context"]["ip_type"] or "<unknown>",
                payload["data_context"]["ip_address"] or "<unknown>",
                str(payload["data_context"]["cid"]),
                payload["data_context"]["source"] or "<unknown>",
            ))
            if args.auto_port and ports:
                print("")
                print("Detected serial ports:")
                for item in ports:
                    print("- %s: %s" % (item.get("port", ""), item.get("name", "")))
        return 0
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except Exception as e:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(e),
                        "policy": "NO_COMMERCIAL_VERDICT",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print("Error: %s" % e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
