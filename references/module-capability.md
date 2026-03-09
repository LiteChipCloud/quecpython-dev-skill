# Module Capability

## Data Files

Primary data source expected by the script:
1. `data/modules_sheet03.normalized.json` (preferred in this skill repo)
2. `assets/data/modules_sheet03.normalized.json` (fallback)
3. Workspace fallbacks (auto-discovered), for example:
   - `quectel-modules/quecpython/docs/spec/data/modules_sheet03.normalized.json`
   - `docs/spec/data/modules_sheet03.normalized.json`

If your file is in a custom location, pass `--data <path>` explicitly.

## What You Can Query

1. Module availability by model name.
2. Feature support flags (`USSL`, `FOTA`, `SMS`, `Voicecall`, etc.).
3. Resource constraints (`RAM`, `FLASH`, runtime memory, file system).

## Script Usage

1. Show one model:
```bash
python scripts/query_module_capability.py --module EC200U_CNLA
```

2. Find modules by required features:
```bash
python scripts/query_module_capability.py --feature USSL --feature FOTA
```

3. Filter by runtime and file system budget:
```bash
python scripts/query_module_capability.py --min-runtime-kb 600 --min-fs-kb 300
```
