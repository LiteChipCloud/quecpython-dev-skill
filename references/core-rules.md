# Core Rules

## Device-Side Hard Rules

1. Treat QuecPython runtime as the target, not CPython.
2. Prefer QuecPython modules in device code:
   `ujson`, `utime`, `uos`, `usocket`, `ure`, `_thread`.
3. Avoid unsupported or risky syntax in project baseline:
   f-strings, walrus operator (`:=`), `nonlocal`, type annotations in runtime files.
4. Avoid CPython-only imports in runtime files:
   `typing`, `pathlib`, `threading`, `asyncio`, `subprocess`.
5. Guard all network and I/O calls with:
   timeout, retries/backoff, exception handling, and clear logs.

## Host-Side Boundary

Host scripts (tooling, build, VSCode integration) may use CPython features.
Do not copy host-side imports/patterns directly into `/usr` runtime code.

## Runtime Safety Baseline

1. Keep entry file simple (`_main.py` or project entry).
2. Keep long-running loops interruptible and observable.
3. Log key transitions:
   boot, network ready, connect/reconnect, upload, failure reason.
4. Keep file writes bounded and avoid high-frequency flash writes.
