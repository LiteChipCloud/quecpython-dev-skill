# Official Docs Workflow

Use this workflow when API behavior is unknown or when you need broad official coverage.

## Source Tiers

1. Site search index (full text):
   `https://developer.quectel.com/doc/quecpython/static/search_index/index.json`
2. Site sitemap (coverage/inventory):
   `https://developer.quectel.com/doc/quecpython/sitemap.xml`
3. API link list (local fallback):
   `references/official-doc-links.md`

## Recommended Steps

1. Find candidate pages by keyword:
   `python scripts/query_qpy_docs_online.py --keyword <k1> --keyword <k2> --section API_reference --lang zh`
2. If scope is unclear, inspect sitemap counts and sections:
   `python scripts/crawl_qpy_site_index.py --lang zh --out review/qpy-sitemap-zh.json`
3. Cross-check API signatures with local stubs:
   `references/stubs-index.md`
4. Cross-check model support with capability data:
   `python scripts/query_module_capability.py --module <MODEL>`
5. For hardware pin questions (PIN/GPIO), run targeted mapping query:
   `python scripts/query_pin_map.py --model <MODEL> --pin <N> --lang zh --top 5`

## Notes

1. `qpy-vscode-extension` can open URL links, but does not provide a dedicated command for official API keyword search.
2. Online docs pages can include model-specific sections; do not assume all models share the same API behavior.
