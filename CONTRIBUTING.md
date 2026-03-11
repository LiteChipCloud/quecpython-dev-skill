# Contributing

## Scope

This project accepts contributions for:
1. QuecPython compatibility rules and checks
2. Device operations workflow scripts
3. Documentation quality and reproducibility
4. Security and sanitization hardening

## Development Flow

1. Fork and create a feature branch from `main`.
2. Keep changes scoped to one concern (code, docs, or workflow).
3. Run local checks before PR:
   - `python -m compileall -q scripts`
4. Update docs when behavior or CLI flags change.
5. Open PR with:
   - problem statement
   - change summary
   - risk/rollback notes

## Pull Request Criteria

1. CI must pass.
2. No secrets, internal paths, or private endpoints.
3. Changes must preserve compatibility constraints in `SKILL.md`.
4. If third-party assets are added, include attribution updates.

## Commit Convention

Recommended prefixes:
1. `feat:` new capability
2. `fix:` bug fix
3. `docs:` documentation update
4. `chore:` maintenance
5. `refactor:` non-behavioral refactor
