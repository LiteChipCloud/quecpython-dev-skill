# Commercial Evidence Gates

This file defines evidence gates, not an automatic approval mechanism.
No script in this skill is allowed to output a final commercial-release verdict.

## Gate A: Traceability

1. Every output includes source URL(s) or local evidence file path.
2. Firmware operations produce JSON report artifacts.
3. Device operations produce smoke logs and result status.

## Gate B: Flash Safety

1. Flash must be explicit (`--flash`) and operator-confirmed.
2. Run strict pre-flash identity verification:
   - `AT+CGMR` model must match selected firmware record.
3. Keep rollback and prior version path documented.

## Gate C: Post-Flash Acceptance

1. Execute smoke validation after successful flash.
2. Verify AT, REPL, and `/usr` access at minimum.
3. Archive result JSON/log for release evidence.

## Gate D: Pin Mapping Safety

1. Doc query result is a clue, not final truth.
2. Cross-check module hardware design spec before PCB/schematic decisions.
3. Record validation result with test bench evidence.

## Gate E: Soak Evidence

1. Keep periodic smoke evidence for long-run behavior (`qpy_soak_runner.py` + per-iteration smoke logs).
2. Define stop thresholds before execution (total failures, consecutive failures, stage-based abort).
3. Treat soak report as supporting evidence, not standalone release approval.

## Gate F: Host Stability

1. Collect host crash evidence when freeze/reboot occurs (`qpy_crash_triage.py` JSON report).
2. During instability window, enforce safe-mode-only operations:
   - `device_smoke_test.py --risk-mode safe`
   - `qpy_soak_runner.py --risk-mode safe`
   - no flash unless manually reconfirmed.
3. Do not resume standard/aggressive mode until no new kernel bugcheck is observed in the selected window.

## Recommended Command Pattern

```bash
python scripts/qpy_firmware_manager.py --model EC800K --stable-only --download-dir review/downloads --flash --flash-port COM7 --at-port COM7 --post-smoke --json
```

## Output Policy

1. Allowed: evidence, logs, API facts, risk notes.
2. Forbidden: direct claims such as "commercially approved/release-ready" based on script output only.
