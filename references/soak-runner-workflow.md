# Soak Runner Workflow

This workflow orchestrates periodic smoke checks for long-run validation.

## Scope

1. Schedule repeated `device_smoke_test.py` runs.
2. Configure deploy cadence (every iteration / never / interval).
3. Classify failed steps and apply stop thresholds.
4. Export per-iteration artifacts and final summary JSON.

## Commands

1. Two-hour soak with 5-minute interval:
```bash
python scripts/qpy_soak_runner.py --risk-mode safe --duration-hours 2 --interval-seconds 300 --auto-ports --ls-via repl --deploy-via repl --json-report review/soak-2h.json
```

2. 10-iteration short burn-in with periodic deploy checks:
```bash
python scripts/qpy_soak_runner.py --risk-mode standard --duration-seconds 900 --interval-seconds 60 --max-iterations 10 --deploy-mode interval --deploy-interval 3 --auto-ports --ls-via repl --deploy-via repl --json
```

3. Strict failure policy:
```bash
python scripts/qpy_soak_runner.py --risk-mode standard --duration-hours 4 --interval-seconds 120 --auto-ports --ls-via repl --deploy-via repl --max-failures 1 --max-consecutive-failures 1 --abort-on-stage AT --abort-on-stage REPL
```

## Output Artifacts

1. `<work-dir>/iter_XXXX/smoke.json`
2. `<work-dir>/iter_XXXX/smoke.log`
3. `<work-dir>/soak_summary.json` (or `--json-report` target)

## Safety Notes

1. Soak summary is evidence, not a production-release approval verdict.
2. For release decisions, combine soak evidence with manual checklist and hardware-level validation.
3. Keep raw logs for root-cause analysis when failures are intermittent.
4. In `risk-mode safe`, deploy checks are forced off for host stability.
5. `--ls-via qpycom` or `--deploy-via qpycom` should be used only with explicit operator confirmation.
