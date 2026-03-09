# Stubs Index

This skill bundles QuecPython stubs from qpy-vscode-extension:
`../assets/stubs/quecpython_stubs/`

Use them as API-shape references, not as runtime code.

## How to Use

1. Do not load all stubs by default.
2. Open only module-specific files required by current task.
3. Verify model support with `scripts/query_module_capability.py`.
4. Keep final runtime code aligned with project compatibility rules.

## High-Frequency Stub Files

1. `machine.pyi` (UART/I2C/SPI/GPIO/Timer/WDT)
2. `request.pyi` (HTTP client)
3. `umqtt.pyi` (MQTT APIs)
4. `dataCall.pyi` / `net.pyi` (cellular network)
5. `ql_fs.pyi` / `uos.pyi` (file system)
6. `checkNet.pyi` (network readiness helper)

## Notes

1. Some stubs include host-specific helper files (for extension setup); these are not device runtime references.
2. Stubs define signatures and names; behavior details still depend on firmware/model.
