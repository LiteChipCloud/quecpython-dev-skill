# Module Capability Seed Data

This folder contains a minimal seed dataset for `query_module_capability.py`.

## Purpose

The installed `quecpython-dev` skill was missing the expected
`modules_sheet03.normalized.json` file, which made the module query script unusable.

This seed dataset is intentionally small and focuses on the modules currently
relevant to LCC's QuecPython / DTU / embedded-agent analysis:

- `EC800KCNLC`
- `EG800K-CN`
- `EC800GCNLD`
- `EC800MCNLE`
- `EC800MCNGB`
- `EC600MCNTE`
- `EC600N-CN`
- `EC200UCNLA`
- `EC200UEUAA`

## Source Policy

Each row is curated from public Quectel official sources only:

1. QuecPython Getting Started supported-module page
2. QuecDevZone module overview pages
3. QuecPython official solution quick-start pages
4. Quectel official product/spec pages when the solution page did not expose the needed feature line

## Scope Boundary

This is a bootstrap dataset, not a full mirror of Quectel's internal module matrix.

What it is good for:

- checking whether a target module is within the current QuecPython support set
- checking whether a module is associated with specific official solution tracks
- checking a small set of feature flags such as `DFOTA`, `WiFiScan`, `GNSS`,
  `Bluetooth`, `AnalogAudio`, `CameraLCMAudio`

What it is not good for:

- claiming complete coverage of all Quectel modules
- claiming precise runtime memory / file-system budget when no official public
  source was captured for that field
- replacing final hardware bring-up validation

## Notes on Empty Fields

The script expects columns such as `RAM`, `FLASH`, `运行内存`, `文件系统`.
If the current public source set did not expose a trustworthy value, the field
is left empty instead of inventing data.
