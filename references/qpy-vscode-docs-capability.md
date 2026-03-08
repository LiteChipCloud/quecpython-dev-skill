# qpy-vscode-extension Docs Capability

This note summarizes whether `qpy-vscode-extension` has built-in QuecPython official docs lookup.

## Findings

1. It has URL opening capability:
   - `src/packagePanel/htmlPanel.ts` handles `openUrl`.
   - Uses `vscode.env.openExternal(...)` to open links.
2. It fetches and renders GitHub README pages for QuecPython projects/components:
   - `src/packagePanel/html.ts`
   - `src/packagePanel/htmlPanel.ts`
3. It does not expose a dedicated command like:
   - `search official QuecPython API docs by keyword`
   - `jump to official API page from symbol/module name`
4. It does access Quectel developer endpoints for firmware list/download workflows, not API doc retrieval:
   - `src/sidebar/firmwareSidebar.ts`
   - `src/utils/constants.ts` (`moduleList.url`)

## Practical Implication for This Skill

When API behavior is unknown:
1. Use `scripts/query_qpy_docs_online.py` to search official online docs index (full text).
2. Use `scripts/query_official_docs.py` as local fallback for quick link lookup.
2. Then use `references/stubs-index.md` + `assets/stubs/quecpython_stubs/` to cross-check signatures.
3. Use `scripts/query_module_capability.py` to verify model support.

## Suggested Commands

```bash
python scripts/query_qpy_docs_online.py --keyword machine.Pin --keyword GPIO --section API_reference --lang zh --top 10
python scripts/query_official_docs.py --keyword machine --keyword uart --top 10
python scripts/query_official_docs.py --keyword ussl --lang zh --open-first
python scripts/query_official_docs.py --list-categories
```
