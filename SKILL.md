---
name: fetch-us-investment-ideas
description: Fetch a structured list of possible US stock investment ideas with ticker-level value and quality rationale. Use when you need fresh NASDAQ/NYSE/AMEX candidates for idea generation, watchlist seeding, or downstream research workflows that require machine-readable ticker plus short thesis output.
---

# Fetch US Investment Ideas

## Overview
The helper script performs external data fetch and queue-file writes:
- Fetch Finviz candidates into `<DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/finviz-candidates.json`.
- Optionally validate/apply outer-loop LLM selections from `--selection-json`.
- Append final queue rows to `<DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/screener-results.jsonl`.
- Clean up run-local artifacts after successful append by default (unless `--keep-artifacts`).

If Finviz candidates do not match the user query well enough, use web search in the outer loop and append final rows directly to `screener-results.jsonl`.

When present, apply `<DATA_ROOT>/user_preferences.json` by default:
- US market guardrail (skip/fail if US is excluded)
- sector/industry preference interpretation in the outer-loop LLM

## Invocation Style (Codex + Claude)
- Codex explicit invocation: `$fetch-us-investment-ideas`.
- Claude explicit invocation: invoke the `fetch-us-investment-ideas` skill in natural language.

## Shared Contract Guardrails
- `SCREEN_RUN_ID` is required and must use strict format `YYYY-MM-DD-HHMMSS`.
- Never add suffixes/slugs to run folders (for example, `-low-pe-waste-management` is invalid).
- Append queue rows only to `<DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/screener-results.jsonl`.
- Ensure every queue row includes required fields: `ticker`, `exchange_country` (set `US` for this skill).
- Prefer including `company`, `exchange`, `sector`, `industry`, `market`, `thesis` when available.
- Never include `source`, `generated_at_utc`, `queued_at_utc`, or `source_output` in queue rows.
- Do not repurpose reserved shared primitive paths.

## Skill Path (set once)

```bash
export CHADWIN_SKILLS_DIR="${CHADWIN_SKILLS_DIR:-$HOME/.claude/skills}"
export FETCH_US_INVESTMENT_IDEAS_ROOT="$CHADWIN_SKILLS_DIR/fetch-us-investment-ideas"
export FETCH_US_INVESTMENT_IDEAS_CLI="$FETCH_US_INVESTMENT_IDEAS_ROOT/scripts/fetch_us_investment_ideas.py"
```

For Codex-only environments, set `CHADWIN_SKILLS_DIR="$HOME/.codex/skills"` instead.

## Quick Start
1. Ensure `.venv` is active and install this skill's optional script dependencies from `references/optional-python.txt`.
2. Set a strict run id and create the run folder:

```bash
SCREEN_RUN_ID="$(date -u +%Y-%m-%d-%H%M%S)"
mkdir -p "<DATA_ROOT>/idea-screens/$SCREEN_RUN_ID"
```

3. Fetch candidate universe from Finviz:

```bash
python3 "$FETCH_US_INVESTMENT_IDEAS_CLI" \
  --screen-run-id "$SCREEN_RUN_ID" \
  --output-json "<DATA_ROOT>/idea-screens/$SCREEN_RUN_ID/finviz-candidates.json" \
  --fetch-only
```

4. If Finviz candidates are suitable, apply selection and append `screener-results.jsonl` (prefer stdin to avoid creating `selected-ideas.json`):

```bash
cat <<'JSON' | python3 "$FETCH_US_INVESTMENT_IDEAS_CLI" \
  --screen-run-id "$SCREEN_RUN_ID" \
  --output-json "<DATA_ROOT>/idea-screens/$SCREEN_RUN_ID/finviz-candidates.json" \
  --ideas-log "<DATA_ROOT>/idea-screens/$SCREEN_RUN_ID/screener-results.jsonl" \
  --selection-json -
{"ideas":[{"ticker":"EXAMPLE","thesis":"Concise rationale"}]}
JSON
```

5. Use `--keep-artifacts` only when you intentionally want to retain sidecar files:

```bash
python3 "$FETCH_US_INVESTMENT_IDEAS_CLI" \
  --screen-run-id "$SCREEN_RUN_ID" \
  --output-json "<DATA_ROOT>/idea-screens/$SCREEN_RUN_ID/finviz-candidates.json" \
  --ideas-log "<DATA_ROOT>/idea-screens/$SCREEN_RUN_ID/screener-results.jsonl" \
  --selection-json "<PATH_TO_SELECTION_JSON>" \
  --keep-artifacts
```

6. If Finviz candidates are not suitable, use web search in the outer loop and append final rows directly to `<DATA_ROOT>/idea-screens/$SCREEN_RUN_ID/screener-results.jsonl`.

## Required Queue Row Shape
Each JSONL row in `screener-results.jsonl` should include:

```json
{
  "ticker": "EXAMPLE",
  "exchange_country": "US",
  "company": "Example Inc.",
  "exchange": "NASDAQ",
  "sector": "Technology",
  "industry": "Software - Application",
  "market": "us",
  "thesis": "Concise rationale"
}
```

## Workflow
1. Create `SCREEN_RUN_ID` in strict format `YYYY-MM-DD-HHMMSS`.
2. Run helper script to fetch Finviz candidates (typically with `--fetch-only`).
3. Outer-loop LLM evaluates candidate fit against the user query.
4. If Finviz is sufficient, apply `--selection-json` and append results with helper script.
5. Prefer `--selection-json -` to avoid creating a selection sidecar file.
6. If Finviz is insufficient, use web search in the outer loop and append final rows directly.
7. Confirm `<DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/screener-results.jsonl` is the final output.
8. Validate queue rows: required keys present, forbidden metadata keys absent.
9. Confirm sidecar artifacts were cleaned unless `--keep-artifacts` was requested.

## Key Flags (Helper Script)
- `--screen-run-id`: strict run id (`YYYY-MM-DD-HHMMSS`) for path and payload consistency.
- `--output-json`: write fetched candidate payload JSON.
- `--ideas-log`: write/append target `screener-results.jsonl` path.
- `--selection-json`: optional selected ideas from outer-loop LLM (`{"ideas": [...]}` or list); when present, helper script appends `screener-results.jsonl`.
- `--fetch-only`: fetch candidates only; skip screener append.
- `--keep-artifacts`: keep sidecar artifacts (`finviz-candidates.json`, run-local selection file) after successful append.
- `--limit`: max number of fetched candidates.
- `--idea-limit`: max number of selected ideas appended.
- `--max-pages-per-exchange`: controls scan breadth per exchange.
- `--request-delay`: delay between HTTP requests.
- `--preferences-path`: override preferences path (default `<DATA_ROOT>/user_preferences.json`).
- `--ignore-preferences`: ignore preference-based market guardrails.

## Troubleshooting
- If Finviz payload is empty, raise `--max-pages-per-exchange` or rerun with `--ignore-preferences`.
- If preferences exclude US market, update `<DATA_ROOT>/user_preferences.json` or rerun with `--ignore-preferences`.
- If requests fail intermittently, raise `--request-delay` and retry.
- If run id validation fails, use exactly `YYYY-MM-DD-HHMMSS` with no suffix.
- If append result is empty, verify `ticker` values in `--selection-json` exist in fetched candidates, or use web-search-driven idea selection.
- If you need to inspect candidate payloads after append, rerun with `--keep-artifacts`.
- If script dependencies are missing, install packages listed in `references/optional-python.txt`.
