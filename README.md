# QuecPython Dev Skill

`quecpython-dev` is a Codex/agent skill for QuecPython device development and operations.

It focuses on:
- Device-side QuecPython coding constraints and compatibility checks
- Firmware lifecycle and module capability queries
- Device deployment/debug workflows (serial/REPL, `/usr` file operations, smoke/soak tests)
- Official documentation discovery and indexing helpers

## Layout

- `SKILL.md`: trigger description and usage contract
- `scripts/`: executable utilities for compatibility checks, docs query, firmware and device operations
- `references/`: workflow docs and operating rules
- `assets/templates/`: starter templates for common patterns
- `assets/stubs/`: QuecPython API stubs for API-shape grounding

## Quick Start

1. Install/clone this skill into your Codex skills directory.
2. Read `SKILL.md` first.
3. Run script help before using a workflow:

```bash
python scripts/check_quecpython_compat.py --help
python scripts/query_module_capability.py --help
python scripts/device_smoke_test.py --help
```

## Notes

- This repository intentionally excludes local/private workspace paths.
- Device operations are hardware-dependent and require explicit port/model context.
- For third-party attribution details, see `references/third-party-attribution.md`.
