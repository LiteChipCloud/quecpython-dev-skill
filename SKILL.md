---
name: quecpython-dev
description: QuecPython device development and operations skill. Use when tasks involve writing or reviewing QuecPython code, enforcing device-side compatibility rules, querying module capabilities, flashing firmware, downloading scripts to /usr, serial/REPL debugging, file-system operations, or log capture workflows based on qpy-vscode-extension.
---

# QuecPython Dev

## Scope

Use this skill to produce deployable QuecPython solutions, not generic CPython snippets.
Apply it for both:
1. Device-side coding tasks (`_main.py`, `/usr` runtime, network/peripheral modules).
2. Device operations tasks (flash, file download, run script, serial debug, log collection).

## Quick Workflow

1. Identify task mode:
   Coding mode: feature implementation, refactor, bugfix, compatibility review.
   Operations mode: flash, deploy to `/usr`, serial/REPL debug, log triage.
2. Capture required context before coding or commands:
   Module model, firmware version, COM port, baudrate, target path (`/usr/...`), network environment.
3. Run capability and compatibility checks:
   `scripts/query_module_capability.py` for model/feature/resource constraints.
   `scripts/check_quecpython_compat.py` for CPython-incompatible patterns.
4. Build from templates where possible:
   `assets/templates/` for network bootstrap, MQTT uplink, UART-Modbus skeleton.
5. For device operations, follow the procedural checklist:
   `references/device-ops-workflow.md`.

## Rules First

Read `references/core-rules.md` first.
Hard constraints:
1. Keep device-side code QuecPython-compatible.
2. Prefer `ujson`, `utime`, `uos`, `usocket`, `_thread` for runtime code.
3. Avoid unsupported syntax/features in project baseline (f-strings, walrus, nonlocal, type annotations in device code).
4. Add timeout, retry/backoff, and exception boundaries for network and I/O paths.
5. Do not mix host tooling code rules with device runtime rules.

## References Map

Load only the file needed for the current task:
1. `references/core-rules.md`: mandatory baseline and code compatibility boundary.
2. `references/coding-spec.md`: architecture and coding standards.
3. `references/api-index.md`: API source index and where to read next.
4. `references/event-contract.md`: event topics/payload conventions.
5. `references/module-capability.md`: model/resource matrix and query usage.
6. `references/device-ops-workflow.md`: flashing, download, serial debug, log capture.
7. `references/stubs-index.md`: how to use local QuecPython stubs safely and efficiently.
8. `references/third-party-attribution.md`: upstream source and license notes for redistributed stubs.
9. `references/qpy-vscode-docs-capability.md`: what qpy-vscode can/cannot do for official doc lookup.
10. `references/official-docs-workflow.md`: comprehensive online docs search/crawl workflow.
11. `references/firmware-lifecycle-workflow.md`: model support, latest firmware query, download, flash workflow.
12. `references/pinmap-query-workflow.md`: PIN/GPIO mapping query workflow and confidence rules.
13. `references/commercial-readiness.md`: mandatory quality gates for commercial delivery.
14. `references/project-manager-workflow.md`: official project/component discovery, release query, clone and submodule workflow.
15. `references/device-fs-cli-workflow.md`: `/usr` tree/mkdir/rm/rmdir/run/push command workflow.
16. `references/soak-runner-workflow.md`: long-run periodic smoke orchestration and threshold policy.
17. `references/device-info-probe-workflow.md`: one-shot device basic info probe (model/fw/IMEI/SIM/ICCID/IMSI/registration/IP).
18. `references/host-stability-workflow.md`: Windows host crash triage and risk-control workflow.

When API behavior is uncertain:
1. Open `references/stubs-index.md`.
2. Read only relevant `.pyi` files under `assets/stubs/quecpython_stubs/`.
3. Cross-check model support using `scripts/query_module_capability.py`.

## Scripts

1. Compatibility check:
```bash
python scripts/check_quecpython_compat.py code/
# or python scripts/check_quecpython_compat.py usr_mirror/
```
Run the checker on device runtime paths only; do not point it to host tooling folders such as `scripts/`.
2. Capability query:
```bash
python scripts/query_module_capability.py --module EC200U_CNLA
python scripts/query_module_capability.py --feature USSL --feature FOTA
```
3. Optional doc cleanup for imported markdown sets:
```bash
python scripts/normalize_qpy_docs.py --src <input-dir> --out <clean-dir>
```
4. Windows DTU smoke test (AT + REPL + deploy/import/cleanup):
```bash
python scripts/device_smoke_test.py --risk-mode safe --auto-ports --print-port-map --repl-baud 115200 --ls-via repl --deploy-via repl
# force kill is blocked unless both flags are set explicitly:
# --kill-qpycom-mode force --allow-force-kill
# and environment guard:
# QPY_FORCE_KILL_GUARD=I_UNDERSTAND_RISK
# in standard mode, QPYcom probe is disabled unless:
# --enable-qpycom-check
# qpycom backend only when explicitly selected:
# --ls-via qpycom / --deploy-via qpycom
```
5. Enhanced smoke with runtime log capture + report export:
```bash
python scripts/device_smoke_test.py --risk-mode standard --auto-ports --repl-baud 115200 --ls-via repl --deploy-via repl --follow-seconds 10 --log-file review/device-smoke.log --json-report review/device-smoke.json
```
6. Official docs lookup by keyword:
```bash
python scripts/query_official_docs.py --keyword machine --keyword uart --top 10
python scripts/query_official_docs.py --keyword ussl --open-first
```
7. Advanced official docs search via online search index:
```bash
python scripts/query_qpy_docs_online.py --keyword machine.Pin --keyword GPIO --section API_reference --lang zh --top 10
python scripts/query_qpy_docs_online.py --keyword MQTT --section Application_guide --lang zh
```
8. Site-wide docs inventory from official sitemap:
```bash
python scripts/crawl_qpy_site_index.py --lang zh --section API_reference --out review/qpy-sitemap-zh-api.json
```
9. Firmware lifecycle manager (support + latest + download + optional flash):
```bash
python scripts/qpy_firmware_manager.py --model EG800AK --latest-only
python scripts/qpy_firmware_manager.py --model EG800AK --stable-only --download-dir review/downloads
# flash only when explicitly confirmed
python scripts/qpy_firmware_manager.py --model EG800AK --stable-only --download-dir review/downloads --flash --flash-port COM7 --flash-baud 115200
# evidence-oriented flash flow: strict model check + post-flash smoke
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --download-dir review/downloads --flash --flash-port COM7 --at-port COM7 --post-smoke --post-smoke-risk-mode safe --json
# include post-flash pre/post version compare with re-enumeration wait window
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --download-dir review/downloads --flash --flash-port COM7 --at-port COM7 --post-version-wait-seconds 120 --json
# enumerate all versions and per-version capability description
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --enumerate-capabilities --json
# auto-match firmware capabilities against explicit requirements
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --enumerate-capabilities --require-feature USSL --require-feature USBNET --require-feature WIFICSCAN --json
# block auto-flash and return candidate versions when required capabilities are missing
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --download-dir review/downloads --select-version V0004 --require-feature USSL --require-feature USBNET --strict-feature-check --flash --flash-port COM7 --at-port COM7 --json
# explicitly allow auto-switch to newest compatible version
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --download-dir review/downloads --select-version V0001 --require-feature USSL --require-feature USBNET --strict-feature-check --choose-best-compatible --flash --flash-port COM7 --at-port COM7 --json
```
10. Pin/GPIO mapping clue query:
```bash
python scripts/query_pin_map.py --model EC800KCNLC --pin 20 --lang zh --top 5
python scripts/query_pin_map.py --model EC800KCNLC --gpio 28 --lang zh --top 5
python scripts/query_pin_map.py --model EC800KCNLC --pin 20 --lang zh --strict-model --top 5
```
11. Official project/component manager:
```bash
python scripts/qpy_project_manager.py --json discover --kind all --limit 20
python scripts/qpy_project_manager.py --json releases --repo QuecPython/solution-xiaozhiAI --top 10
python scripts/qpy_project_manager.py --json clone --repo QuecPython/solution-xiaozhiAI --dest review/projects --ref v1.0.0
```
12. Device file-system CLI (`/usr` focused):
```bash
python scripts/qpy_device_fs_cli.py --json --port COM6 ls --path /usr --ls-via repl
python scripts/qpy_device_fs_cli.py --json --port COM6 push --local code/_main.py --remote-dir /usr --push-via repl
python scripts/qpy_device_fs_cli.py --json --port COM6 run --path /usr/_main.py
python scripts/qpy_device_fs_cli.py --json --port COM6 mkdir --path /usr/tmp
# optional qpycom backend (explicit risk acknowledgment required):
python scripts/qpy_device_fs_cli.py --json --port COM6 --allow-qpycom-risk ls --path /usr --ls-via qpycom
python scripts/qpy_device_fs_cli.py --json --port COM6 --allow-qpycom-risk push --local code/_main.py --remote-dir /usr --push-via qpycom
```
13. Soak runner (periodic smoke orchestration):
```bash
python scripts/qpy_soak_runner.py --risk-mode safe --duration-hours 2 --interval-seconds 300 --auto-ports --ls-via repl --deploy-via repl --json-report review/soak-2h.json
python scripts/qpy_soak_runner.py --risk-mode standard --duration-seconds 900 --interval-seconds 60 --max-iterations 10 --deploy-mode interval --deploy-interval 3 --auto-ports --ls-via repl --deploy-via repl --json
```
14. Device basic info probe (AT summary):
```bash
python scripts/qpy_device_info_probe.py --auto-port --auto-repl-port --json
python scripts/qpy_device_info_probe.py --at-port COM7 --repl-port COM6 --json --include-raw
```
15. Host crash triage (read-only):
```bash
python scripts/qpy_crash_triage.py --days 2 --json-out review/host_crash_triage.json --json
```

## Assets

1. Templates:
   `assets/templates/net_bootstrap_template.py`
   `assets/templates/mqtt_uplink_template.py`
   `assets/templates/uart_modbus_template.py`
2. Stubs:
   `assets/stubs/quecpython_stubs/` copied from qpy-vscode-extension for API shape grounding.

## Output Contract

When this skill is used for implementation:
1. Return device-ready code and list any host-side prerequisites separately.
2. Include explicit run/deploy steps (`/usr` target path, entry script).
3. Include a compatibility check result or state why it was skipped.
4. Never output a commercial-release verdict from script output alone; provide evidence and required manual checks.
