---
name: fetch-us-investment-ideas
description: Fetch a structured list of possible US stock investment ideas with ticker-level value and quality rationale. Use when you need fresh NASDAQ/NYSE/AMEX candidates for idea generation, watchlist seeding, or downstream research workflows that require machine-readable ticker plus short thesis output.
---

# Fetch US Investment Ideas

## Overview
This skill is LLM-driven. Do not force all idea generation through one deterministic screen.

Use one of these paths per run:
- LLM web-research path (default when user asks for flexibility): use native browsing/search, then append results directly to `screener-results.jsonl`.
- Finviz helper path (optional): run `scripts/fetch_us_investment_ideas.py` when a deterministic value/quality seed list is useful.
- Optional local filing-seeded path: if filing snapshot JSONL files already exist under `<DATA_ROOT>/daily-sec-filings/*/*.jsonl` from an external process, use them as a seed universe before thesis selection.

Each completed run appends newly discovered companies to a per-screen queue file at `<DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/screener-results.jsonl` so downstream skills can choose among distinct screen lists.

When present, apply `<DATA_ROOT>/user_preferences.json` by default:
- US market guardrail (skip/fail if US is excluded)
- sector/industry include/exclude filtering

## Invocation Style (Codex + Claude)
- Codex explicit invocation: `$fetch-us-investment-ideas`.
- Claude explicit invocation: invoke the `fetch-us-investment-ideas` skill in natural language.

## Shared Contract Guardrails
- Use one run folder per screen: `<DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/`.
- Append queue rows only to `<DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/screener-results.jsonl`.
- Ensure every queue row includes required fields: `ticker`, `exchange_country` (set `US` for this skill).
- Prefer including recommended queue fields when available: `company`, `exchange`, `sector`, `industry`, `thesis`.
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
2. Set a run id and create the screen run folder:

```bash
SCREEN_RUN_ID="$(date -u +%Y-%m-%d-%H%M%S)"
mkdir -p "<DATA_ROOT>/idea-screens/$SCREEN_RUN_ID"
```

3. Choose path:
- LLM web-research path: gather ideas with native web tools and append queue rows directly to `screener-results.jsonl`.
- Finviz helper path:

```bash
python3 "$FETCH_US_INVESTMENT_IDEAS_CLI" \
  --limit 25 \
  --ideas-log <DATA_ROOT>/idea-screens/$SCREEN_RUN_ID/screener-results.jsonl
```

4. Verify `<DATA_ROOT>/idea-screens/$SCREEN_RUN_ID/screener-results.jsonl` exists and rows include `ticker`, `exchange_country`, and `thesis`.
5. Present filtered subsets in chat output.

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
  "thesis": "Concise rationale"
}
```

Downstream consumers should read row-level `ticker` and `thesis`.

## Workflow
1. Decide path first:
- If user asked for broad/flexible sourcing, use LLM web research directly.
- If user asked for deterministic screening, use the Finviz helper script.
- If user asked for filing-date- or filing-form-driven ideas and local filing snapshots already exist, seed from those files.
2. Keep exchange scope to NASDAQ/NYSE/AMEX unless explicitly asked to broaden.
3. Apply preferences unless user overrides.
4. Append ideas directly to `<DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/screener-results.jsonl`.
5. Verify non-empty queue rows, with `ticker`, `exchange_country`, and `thesis` per entry.
6. Confirm queue append in `<DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/screener-results.jsonl` and verify each row includes `ticker` + `exchange_country`.

## Key Flags (Finviz helper script)
- `--limit`: max number of returned ideas.
- `--max-pages-per-exchange`: controls scan breadth per exchange.
- `--min-market-cap-b`: minimum market cap in billions USD.
- `--max-pe`: valuation cap (trailing P/E).
- `--min-roe`, `--min-roic`, `--min-operating-margin`, `--min-profit-margin`, `--max-debt-to-equity`: quality gates.
- `--ideas-log`: override screener results path (file or directory; defaults to `<DATA_ROOT>/idea-screens/**/screener-results.jsonl`).
- `--base-dir`: override repo root used for queue log resolution.
- `--preferences-path`: override preferences path (default `<DATA_ROOT>/user_preferences.json`).
- `--ignore-preferences`: ignore preference-based market/sector filters.

## Troubleshooting
- If Finviz output is empty, loosen thresholds (for example raise `--max-pe` or lower `--min-roic`).
- If preferences exclude US market, update `<DATA_ROOT>/user_preferences.json` or rerun with `--ignore-preferences`.
- If requests fail intermittently, raise `--request-delay` and retry.
- If script dependencies are missing, install the packages listed in `references/optional-python.txt`.
