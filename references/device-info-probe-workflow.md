# Device Info Probe Workflow

This workflow provides a one-shot AT-based summary for connected QuecPython-capable modules.

## Scope

1. Module model and firmware revision.
2. IMEI.
3. SIM status, ICCID, IMSI.
4. Registration status.
5. PDP IP type and IP address.

## Command

1. Auto-detect AT port:
```bash
python scripts/qpy_device_info_probe.py --auto-port --auto-repl-port --json
```

2. Explicit AT port with raw evidence:
```bash
python scripts/qpy_device_info_probe.py --at-port COM7 --repl-port COM6 --json --include-raw
```

## Output Contract

Main output fields:
1. `device.module_model`
2. `device.firmware_version`
3. `device.imei`
4. `sim.cpin`, `sim.sim_inserted`, `sim.iccid`, `sim.imsi`
5. `registration.registered` and registration source/stat
6. `data_context.ip_type`, `data_context.ip_address`
7. `diagnostics[]` with possible causes and actionable suggestions when fields fail/empty.
8. `field_sources` and `repl_fallback` to show whether values come from AT or REPL.

## Notes

1. Some DTU/firmware combinations may return `ERROR` for `AT+QCCID`, `AT+GSN`, `AT+QIACT?`; script keeps these as empty fields rather than fabricating values.
2. When AT command set is incomplete, script will automatically fallback to REPL APIs (`modem`, `sim`, `dataCall`) unless `--no-repl-fallback` is specified.
3. Use `--include-raw` for audit evidence and troubleshooting.
4. Script output is evidence only and must not be treated as a commercial-release approval verdict.
5. If a flash operation finishes but only download port remains (for example `ASR Serial Download Device`), perform hardware reset/power-cycle and re-run probe.
