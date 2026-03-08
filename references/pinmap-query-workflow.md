# PIN/GPIO Query Workflow

## Goal

Answer questions like:
1. `PIN20` corresponds to which `GPIO`?
2. `GPIO28` corresponds to which exposed pin label?

## Commands

```bash
# Pin -> GPIO
python scripts/query_pin_map.py --model EC800KCNLC --pin 20 --lang zh --top 5

# GPIO -> Pin
python scripts/query_pin_map.py --model EC800KCNLC --gpio 28 --lang zh --top 5

# Strict model mode (commercial-evidence preferred)
python scripts/query_pin_map.py --model EC800KCNLC --pin 20 --lang zh --strict-model --top 5
```

## Interpretation Rules

1. Use rows with higher score first:
   - `score=3`: exact numeric pin cell match or exact GPIO token.
   - `score=2`: row contains `Pxx`/`PINxx`.
2. Prefer results where `model_mentioned_in_page=true`.
3. If model is not explicitly mentioned, treat result as *board-level clue* and confirm with module hardware design spec.
4. With `--strict-model`, only rows that satisfy both are kept:
   - `model_mentioned_in_page=true`
   - `model_matched_table_class=true`

## Risk Control Rule

Do not ship hardware pin mapping decisions based on a single page clue.
Minimum requirement:
1. one official page result from this query;
2. one hardware design specification cross-check (PDF/manual);
3. one device-side electrical validation record.
4. do not output "commercially approved" conclusions directly from this query.
