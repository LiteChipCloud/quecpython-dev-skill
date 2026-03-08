# Device FS CLI Workflow

This workflow provides CLI-level `/usr` file-system operations on QuecPython devices.

## Scope

1. List files (`ls`) and tree-like directory snapshot (`tree`).
2. Create/remove directory or file (`mkdir`, `rmdir`, `rm`).
3. Upload file (`push`) and trigger script execution (`run`).

## Commands

1. List `/usr` (REPL default, safer):
```bash
python scripts/qpy_device_fs_cli.py --json --port COM6 ls --path /usr --ls-via repl
```

1.1 List `/usr` via QPYcom (only when explicitly needed):
```bash
python scripts/qpy_device_fs_cli.py --json --port COM6 --allow-qpycom-risk ls --path /usr --ls-via qpycom
```

2. Upload and run (REPL default):
```bash
python scripts/qpy_device_fs_cli.py --json --port COM6 push --local code/_main.py --remote-dir /usr --push-via repl
python scripts/qpy_device_fs_cli.py --json --port COM6 run --path /usr/_main.py
```

2.1 Upload via QPYcom (only when explicitly needed):
```bash
python scripts/qpy_device_fs_cli.py --json --port COM6 --allow-qpycom-risk push --local code/_main.py --remote-dir /usr --push-via qpycom
```

3. Directory operations:
```bash
python scripts/qpy_device_fs_cli.py --json --port COM6 mkdir --path /usr/tmp
python scripts/qpy_device_fs_cli.py --json --port COM6 rmdir --path /usr/tmp
```

4. Remove file:
```bash
python scripts/qpy_device_fs_cli.py --json --port COM6 rm --path /usr/old_script.py
```

5. Auto-port mode:
```bash
python scripts/qpy_device_fs_cli.py --json --auto-port ls --path /usr --ls-via repl
```

## Safety Notes

1. Destructive operations are restricted to `/usr` by default.
2. Use `--allow-any-path` only for controlled diagnostics.
3. `run` only confirms dispatch success; script runtime exceptions must be read from returned raw output.
4. Script output is operational evidence only and must not be treated as commercial-release approval.
5. `ls` defaults to `--ls-via repl`, and `push` defaults to `--push-via repl`.
6. Only QPYcom backend operations are gated by `--allow-qpycom-risk`.
7. REPL backend includes transient port-busy retry; keep operations single-threaded to avoid self-contention.
