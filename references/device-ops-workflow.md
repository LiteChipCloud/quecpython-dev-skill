# Device Ops Workflow

This file defines the operational workflow for flash, deployment, serial debug, and log collection.

## Source Mapping

Derived from:
1. `qpy-vscode-extension-master/src/sidebar/firmwareDownload.ts`
2. `qpy-vscode-extension-master/src/api/fileDownload.ts`
3. `qpy-vscode-extension-master/src/api/commands.ts`
4. `qpy-vscode-extension-master/src/serial/commandLine.ts`
5. `qpy-vscode-extension-master/src/api/userInterface.ts`
6. `qpy-vscode-extension-master/scripts/q_init_fs.txt`

## A. Flash Workflow

1. Identify module model and download port.
2. Select local firmware or fetch online firmware package.
3. Resolve actual flash target file (`.pac`, `.bin`, or model-specific package).
4. Run flash tool and monitor progress.
5. Capture success/failure with evidence logs.

Command template (tool-driven, Windows):
1. Select download port and firmware package.
2. Run flash executable through toolchain wrapper:
```text
QuecPythonDownload.exe -d <COMx> -b 115200 -f <firmware_file>
```
3. Expected output contains progress percentage and exit code `0` on success.
4. On failure, record:
   port id, firmware path, module model, last 20 progress lines.

## B. Deploy Workflow (/usr)

1. Connect serial port (correct baudrate and line terminator).
2. Download target script/files to `/usr` (or `/usr/<subdir>`).
3. Run entry script (`_main.py` or designated module file).
4. Confirm runtime output and startup markers.

Command templates:
1. Download file to `/usr`:
```text
QPYcom.exe -d <COMx> -b <baudrate> -f cp <local_file> :/usr/<target_name>
```
2. Download file to custom directory:
```text
QPYcom.exe -d <COMx> -b <baudrate> -f cp <local_file> :/usr/<subdir>/<target_name>
```
3. Run script from REPL:
```python
import example
example.exec('usr/_main.py')
```

## C. File System Workflow

1. Initialize/read module file tree from `/usr`.
2. Create directory as needed.
3. Remove stale files/dirs carefully.
4. Refresh and verify final tree state.

Command templates (REPL):
```python
import ql_fs
ql_fs.mkdirs('/usr/test')
```
```python
import uos
uos.remove('/usr/old.py')
uos.rmdir('/usr/old_dir')
```

## D. Debug + Log Workflow

1. Keep serial output attached during flash/deploy/run.
2. For persistent evidence, enable log-to-file channel when needed.
3. Correlate failures by stage:
   connect, flash, download, execute, runtime.

Log capture template:
1. Enable output channel/file logging in tool settings when needed.
2. Keep timestamps in logs.
3. Store evidence blocks by stage:
   `CONNECT`, `FLASH`, `DOWNLOAD`, `EXECUTE`, `RUNTIME`.

## E. Troubleshooting Checklist

1. Port not visible:
   check driver, cable, module mode, download port id.
2. Flash fails:
   check firmware package type and module match.
3. Download fails:
   check active serial session and target `/usr` path.
4. Script not running:
   verify entry file, import path, and runtime exceptions.

Minimum triage payload:
1. Module model + firmware version.
2. Port path + baudrate.
3. Executed command line.
4. Last visible error line and stage label.

## F. Fast Smoke Test (Windows)

Use bundled script for one-shot validation before complex operations:

```bash
python scripts/device_smoke_test.py --risk-mode safe --auto-ports --print-port-map --repl-baud 115200
```

What it checks:
1. AT link (`AT`/`ATI`/`AT+CSQ`).
2. REPL link and prompt response.
3. `/usr` list via REPL (default) or `QPYcom` (explicitly selected).
4. Optional deploy/import/cleanup probe file on `/usr` (REPL default).
5. Optional continuous REPL log capture (`--follow-seconds`) with timestamped output.
6. Optional report export: `--log-file` (text), `--json-report` (structured data).
7. Built-in failure classification hints:
   port-in-use, access failure, tool missing, timeout, BOM encoding, import path.

Recommended command:

```bash
python scripts/device_smoke_test.py --risk-mode safe --auto-ports --repl-baud 115200 --ls-via repl --deploy-via repl --follow-seconds 10 --log-file review/device-smoke.log --json-report review/device-smoke.json
```

For standard mode, QPYcom backend is disabled by default and can be enabled explicitly:

```bash
python scripts/device_smoke_test.py --risk-mode standard --auto-ports --ls-via repl --deploy-via repl --json-report review/device-smoke-standard.json
python scripts/device_smoke_test.py --risk-mode standard --enable-qpycom-check --auto-ports --ls-via qpycom --deploy-via qpycom --skip-deploy --json-report review/device-smoke-standard-qpycom.json
```

## G. Firmware Manager

For official firmware lifecycle operations, use:

```bash
python scripts/qpy_firmware_manager.py --model EG800AK --latest-only
python scripts/qpy_firmware_manager.py --model EG800AK --stable-only --download-dir review/downloads
```

Flash only after explicit confirmation:

```bash
python scripts/qpy_firmware_manager.py --model EG800AK --stable-only --download-dir review/downloads --flash --flash-port COM7 --flash-baud 115200 --post-smoke --post-smoke-risk-mode safe
```

## H. Host Stability Guardrails

1. Keep `device_smoke_test.py` in `--risk-mode safe` unless host stability is confirmed.
2. `qpy_device_fs_cli.py` only `qpycom` backend operations require `--allow-qpycom-risk` explicit acknowledgment.
3. If host freeze/restart appears, pause flash/deploy and run:

```bash
python scripts/qpy_crash_triage.py --days 2 --json-out review/host_crash_triage.json --json
```
