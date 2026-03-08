# Firmware Lifecycle Workflow

This workflow covers:
1. Model support check (QuecPython firmware available or not)
2. Latest version resolution
3. Official package download
4. Optional flashing via `QuecPythonDownload.exe`
5. Post-flash version re-check (pre/post compare)
6. Optional post-flash smoke acceptance

## Data Source

Official resource API endpoint used by qpy-vscode:
`https://developer.quectel.com/wp-admin/admin-ajax.php`

Core request shape:
- `action=get_download_list`
- `category=15`
- `keywords=<model-or-platform>`
- pagination fields (`page`, `page_num`)

## Commands

1. Check support + latest:
```bash
python scripts/qpy_firmware_manager.py --model EG800AK --latest-only
```

2. Download latest stable package:
```bash
python scripts/qpy_firmware_manager.py --model EG800AK --stable-only --download-dir review/downloads
```

3. Flash explicitly (high risk, do only with confirmed port/model match):
```bash
python scripts/qpy_firmware_manager.py --model EG800AK --stable-only --download-dir review/downloads --flash --flash-port COM7 --flash-baud 115200
```

4. Evidence-oriented flash (strict pre-check + post-smoke):
```bash
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --download-dir review/downloads --flash --flash-port COM7 --at-port COM7 --post-smoke --post-smoke-risk-mode safe --json
```

5. Flash + explicit post-version wait window:
```bash
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --download-dir review/downloads --flash --flash-port COM7 --at-port COM7 --post-version-wait-seconds 120 --json
```

6. Enumerate all versions with per-version capability descriptions:
```bash
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --enumerate-capabilities --json
```

7. Match required capabilities before selecting flash target:
```bash
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --enumerate-capabilities --require-feature USSL --require-feature USBNET --require-feature WIFICSCAN --json
```

8. Enforce required capabilities during flash (block and list candidates on mismatch):
```bash
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --download-dir review/downloads --select-version V0004 --require-feature USSL --require-feature USBNET --strict-feature-check --flash --flash-port COM7 --at-port COM7 --json
```

9. Optional auto-pick latest compatible version (only when explicitly enabled):
```bash
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --download-dir review/downloads --select-version V0001 --require-feature USSL --require-feature USBNET --strict-feature-check --choose-best-compatible --flash --flash-port COM7 --at-port COM7 --json
```

## Safety Rules

1. Never auto-flash by default.
2. Use strict pre-flash `AT+CGMR` model verification (disable only for emergency diagnostics).
3. Always verify module model, firmware package title, and serial port before flashing.
4. Keep AT/REPL logs as evidence when flashing fails.
5. Prefer `--stable-only` unless beta validation is explicitly required.
6. Run post-flash smoke and keep JSON report for release evidence.
7. Script output is evidence only and must not be treated as a commercial-release approval verdict.
8. Use `version_compare` fields from output to keep pre/post firmware evidence:
   - `pre_revision`, `post_revision`
   - `pre_cgmr`, `post_cgmr`
10. In `--strict-feature-check` mode, mismatch will return `selection_required=true` and `candidate_versions` instead of a hard error; user must pick a version explicitly via `--select-version`.
11. If `--choose-best-compatible` is enabled together with strict check, script auto-switches to the newest compatible version and records `auto_selected_candidate` in output.
12. Before flashing, review `version_capability_matrix` and confirm required features are covered; if uncertainty remains, request user confirmation instead of auto-assuming compatibility.
13. Keep post-flash smoke in `--post-smoke-risk-mode safe` unless host stability has been verified.
