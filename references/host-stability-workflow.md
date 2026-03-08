# Host Stability Workflow

This workflow is used when the Windows host shows freeze/reboot/blue-screen symptoms during QuecPython operations.

## Scope

1. Read-only crash evidence collection.
2. Immediate risk reduction policy.
3. Gated recovery path before re-enabling flash/deploy workflows.

## A. Immediate Freeze Actions

1. Stop all high-risk actions:
   - firmware flash,
   - QPYcom `cp/ls` loops,
   - force process kill (`taskkill /F`),
   - long-running soak with deploy enabled.
2. Keep only read-only probes:
   - AT command query,
   - REPL one-shot query,
   - event-log collection.
3. Do not run manual `taskkill /F QPYcom.exe` stress loops or `QPYcom --follow` hang reproduction on unstable hosts.

## B. Collect Evidence (Read-only)

```bash
python scripts/qpy_crash_triage.py --days 2 --json-out review/host_crash_triage.json --json
```

Expected evidence:
1. `Kernel-Power 41` restart timeline.
2. `WER-SystemErrorReporting` bugcheck records and minidump path.
3. application crash correlations (for example `ARPProtection.exe`, `QPYcom.exe`).
4. security/USB filter signals (for example `BzProtect`, `sysdiag`, `hrdevmon`).

## C. Recovery Guardrails

1. Default to smoke safe mode:
```bash
python scripts/device_smoke_test.py --risk-mode safe --auto-ports --json-report review/device-smoke-safe.json
```
2. Default soak safe mode:
```bash
python scripts/qpy_soak_runner.py --risk-mode safe --duration-seconds 600 --interval-seconds 60 --auto-ports --json
```
3. QPYcom actions require explicit acknowledgment:
```bash
python scripts/qpy_device_fs_cli.py --json --port COM6 --allow-qpycom-risk ls --path /usr
```
4. `device_smoke_test.py` force kill requires dual guard (disabled by default):
   - `--kill-qpycom-mode force --allow-force-kill`
   - `QPY_FORCE_KILL_GUARD=I_UNDERSTAND_RISK`

## D. Escalation Criteria

Escalate to OS/driver-level debugging when any condition is true:
1. repeated bugcheck within 24h,
2. bugcheck code remains unchanged across multiple incidents (for example `0x00000139`),
3. host restarts without completing a safe-mode read-only probe.

Recommended escalation:
1. analyze latest minidump with WinDbg,
2. align security software policy/whitelist for serial and flashing tools,
3. verify USB/serial driver stack stability before resuming flash/deploy.

## E. Exit Criteria (Resume Full Ops)

Only resume standard/aggressive mode after all are satisfied:
1. at least one complete safe smoke run passes,
2. no new kernel bugcheck during observation window,
3. chosen firmware/deploy operation has explicit operator confirmation.
