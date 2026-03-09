# Project Manager Workflow

This workflow maps qpy-vscode package-panel capabilities into CLI form.

## Scope

1. Discover official QuecPython solution/component repositories.
2. Query repository releases.
3. Clone project by release/branch with submodules.
4. Add/remove/list components as git submodules.
5. Maintain local "My Projects" registry JSON for traceability.

## Official Sources

1. GitHub Search API:
   `https://api.github.com/search/repositories?q=org:QuecPython+topic:solution`
2. GitHub Releases API:
   `https://api.github.com/repos/QuecPython/<repo>/releases`

## Commands

1. Discover projects and components:
```bash
python scripts/qpy_project_manager.py --json discover --kind all --limit 20
```

2. Query releases:
```bash
python scripts/qpy_project_manager.py --json releases --repo QuecPython/solution-xiaozhiAI --top 10
```

3. Clone by tag/branch:
```bash
python scripts/qpy_project_manager.py --json clone --repo QuecPython/solution-xiaozhiAI --dest review/projects --ref v1.0.0
```

4. Add component submodule:
```bash
python scripts/qpy_project_manager.py --json add-submodule --workspace ./my_qpy_project --repo QuecPython/component-lcd
```

5. Remove/list submodules:
```bash
python scripts/qpy_project_manager.py --json list-submodules --workspace ./my_qpy_project
python scripts/qpy_project_manager.py --json remove-submodule --workspace ./my_qpy_project --path component-lcd
```

6. Query local registry:
```bash
python scripts/qpy_project_manager.py --json registry-list
```

## Safety Notes

1. Keep `--force` disabled unless target clone folder is confirmed disposable.
2. Validate selected tag/release in GitHub page before production adoption.
3. Registry JSON is evidence metadata only; it is not a release-approval signal.
