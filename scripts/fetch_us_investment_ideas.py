#!/usr/bin/env python3
"""Fetch US market candidates and append LLM-selected ideas to screener-results.jsonl."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

APP_DATA_DIR_NAME = "Chadwin"
DATA_ROOT_ENV_VAR = "CHADWIN_DATA_DIR"
APP_ROOT_ENV_VAR = "CHADWIN_APP_ROOT"
REPO_MARKER_RELATIVE_PATH = Path(".agents") / "skills"
DEFAULT_PREFERENCES_SUBPATH = Path("user_preferences.md")
DEFAULT_IDEA_SCREENS_SUBPATH = Path("idea-screens")
SCREENER_RESULTS_FILENAME = "screener-results.jsonl"
CANDIDATES_FILENAME = "finviz-candidates.json"
RUN_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}$")

FINVIZ_BASE_URL = "https://finviz.com/screener.ashx"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)

EXCHANGES = {
    "NASDAQ": "exch_nasd",
    "NYSE": "exch_nyse",
    "AMEX": "exch_amex",
}

# Keep this broad; the outer-loop LLM performs final selection.
BASE_FILTERS = [
    "geo_usa",
    "ind_stocksonly",
    "cap_midover",
    "sh_price_o5",
    "sh_avgvol_o200",
]

VIEWS = (111, 121, 161)
ROWS_PER_PAGE = 20


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _detect_repo_root(start: Path | None = None) -> Path:
    configured = os.getenv(APP_ROOT_ENV_VAR, "").strip()
    if configured:
        configured_path = Path(configured).expanduser()
        if not configured_path.is_absolute():
            configured_path = (Path.cwd() / configured_path).resolve()
        if configured_path.exists():
            return configured_path

    candidate = (start or Path.cwd()).resolve()
    if candidate.is_file():
        candidate = candidate.parent

    for parent in [candidate, *candidate.parents]:
        if (parent / REPO_MARKER_RELATIVE_PATH).exists():
            return parent
    return Path.cwd().resolve()


def _default_data_root() -> Path:
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return Path(appdata) / APP_DATA_DIR_NAME
        return Path.home() / "AppData" / "Roaming" / APP_DATA_DIR_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DATA_DIR_NAME

    xdg_data_home = os.getenv("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / APP_DATA_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DATA_DIR_NAME


def _resolve_data_root() -> Path:
    configured = os.getenv(DATA_ROOT_ENV_VAR, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_absolute():
            return path
        return (Path.cwd() / path).resolve()
    return _default_data_root()


def default_base_dir() -> Path:
    return _detect_repo_root(Path(__file__).resolve())


def resolve_idea_screens_root() -> Path:
    return _resolve_data_root() / DEFAULT_IDEA_SCREENS_SUBPATH


def _resolve_path(base_dir: Path, value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def repo_scoped_path(path: Path, base_dir: Path) -> str:
    base = base_dir.resolve()
    resolved_candidate = path.resolve()
    try:
        relative = resolved_candidate.relative_to(base)
    except ValueError:
        return str(path)

    relative_text = relative.as_posix()
    if not relative_text or relative_text == ".":
        return base.name
    return f"{base.name}/{relative_text}"


def resolve_preferences_path(
    *,
    base_dir: Path,
    preferences_path: str | Path | None,
) -> Path:
    if preferences_path is None:
        return _resolve_data_root() / DEFAULT_PREFERENCES_SUBPATH
    return _resolve_path(base_dir, preferences_path)


def load_user_preferences(
    *,
    base_dir: Path,
    preferences_path: str | Path | None,
) -> str:
    path = resolve_preferences_path(base_dir=base_dir, preferences_path=preferences_path)
    if not path.exists():
        return ""

    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _request(url: str, delay_seconds: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="ignore")
    if delay_seconds > 0:
        time.sleep(delay_seconds)
    return body


def _build_url(view: int, exchange_filter: str, start_row: int) -> str:
    filters = ",".join([exchange_filter, *BASE_FILTERS])
    params = urllib.parse.urlencode(
        {
            "v": str(view),
            "ft": "4",
            "o": "-marketcap",
            "f": filters,
            "r": str(start_row),
        }
    )
    return f"{FINVIZ_BASE_URL}?{params}"


def _parse_table_rows(html: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    table = None
    for candidate in soup.find_all("table"):
        headers = [th.get_text(" ", strip=True) for th in candidate.find_all("th")]
        if "No." in headers and "Ticker" in headers:
            table = candidate
            break

    if table is None:
        return []

    headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
    parsed: list[dict[str, str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) != len(headers):
            continue
        if not cells[0].get_text(strip=True).isdigit():
            continue
        values = [cell.get_text(" ", strip=True) for cell in cells]
        parsed.append(dict(zip(headers, values)))
    return parsed


def fetch_view_rows(
    *,
    view: int,
    exchange_filter: str,
    start_row: int,
    delay_seconds: float,
) -> list[dict[str, str]]:
    url = _build_url(view=view, exchange_filter=exchange_filter, start_row=start_row)
    return _parse_table_rows(_request(url=url, delay_seconds=delay_seconds))


def merge_exchange_rows(
    *,
    exchange_name: str,
    exchange_filter: str,
    max_pages: int,
    delay_seconds: float,
) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for page in range(max_pages):
        start_row = 1 + (page * ROWS_PER_PAGE)
        page_rows: dict[int, list[dict[str, str]]] = {}
        for view in VIEWS:
            page_rows[view] = fetch_view_rows(
                view=view,
                exchange_filter=exchange_filter,
                start_row=start_row,
                delay_seconds=delay_seconds,
            )

        min_count = min(len(rows) for rows in page_rows.values())
        if min_count == 0:
            break

        for view_rows in page_rows.values():
            for row in view_rows:
                ticker = _clean_text(row.get("Ticker")).upper()
                if not ticker:
                    continue
                slot = merged.setdefault(ticker, {"Ticker": ticker, "Exchange": exchange_name})
                slot.update(row)

        if min_count < ROWS_PER_PAGE:
            break

    return list(merged.values())


def parse_percent(value: str | None) -> float | None:
    if value is None or value in {"", "-"}:
        return None
    try:
        return float(value.replace("%", "").replace(",", ""))
    except ValueError:
        return None


def parse_float(value: str | None) -> float | None:
    if value is None or value in {"", "-"}:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def parse_market_cap(value: str | None) -> float | None:
    if value is None or value in {"", "-"}:
        return None
    cleaned = value.replace(",", "").upper()
    scale = 1.0
    if cleaned.endswith("T"):
        scale = 1_000_000_000_000.0
        cleaned = cleaned[:-1]
    elif cleaned.endswith("B"):
        scale = 1_000_000_000.0
        cleaned = cleaned[:-1]
    elif cleaned.endswith("M"):
        scale = 1_000_000.0
        cleaned = cleaned[:-1]
    elif cleaned.endswith("K"):
        scale = 1_000.0
        cleaned = cleaned[:-1]
    try:
        return float(cleaned) * scale
    except ValueError:
        return None


def build_candidate(row: dict[str, str]) -> dict[str, Any] | None:
    ticker = _clean_text(row.get("Ticker")).upper()
    if not ticker:
        return None

    market_cap = parse_market_cap(row.get("Market Cap"))

    return {
        "ticker": ticker,
        "company": _clean_text(row.get("Company")),
        "exchange": _clean_text(row.get("Exchange")),
        "sector": _clean_text(row.get("Sector")),
        "industry": _clean_text(row.get("Industry")),
        "market": "us",
        "exchange_country": "US",
        "metrics": {
            "market_cap_usd": round(market_cap) if market_cap is not None else None,
            "pe": parse_float(row.get("P/E")),
            "forward_pe": parse_float(row.get("Fwd P/E")),
            "price_to_book": parse_float(row.get("P/B")),
            "roe_pct": parse_percent(row.get("ROE")),
            "roic_pct": parse_percent(row.get("ROIC")),
            "operating_margin_pct": parse_percent(row.get("Oper M")),
            "profit_margin_pct": parse_percent(row.get("Profit M")),
            "debt_to_equity": parse_float(row.get("Debt/Eq")),
            "eps_next_5y_pct": parse_percent(row.get("EPS Next 5Y")),
        },
    }


def collect_candidates(
    raw_rows: list[dict[str, str]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()

    for row in raw_rows:
        candidate = build_candidate(row)
        if not candidate:
            continue

        ticker = candidate["ticker"]
        if ticker in seen_tickers:
            continue

        seen_tickers.add(ticker)
        candidates.append(candidate)
        if len(candidates) >= limit:
            break

    return candidates


def _new_screen_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")


def _ensure_valid_screen_run_id(run_id: str, *, context: str) -> None:
    if not RUN_ID_RE.match(run_id):
        raise ValueError(
            f"Invalid {context}: '{run_id}'. Expected format YYYY-MM-DD-HHMMSS."
        )


def _extract_screen_run_id_from_path(path: Path) -> str | None:
    parts = path.parts
    marker = DEFAULT_IDEA_SCREENS_SUBPATH.name
    for index, part in enumerate(parts):
        if part != marker:
            continue
        if index + 1 < len(parts):
            return parts[index + 1]
    return None


def _looks_like_directory_path(path: Path, expected_filename: str) -> bool:
    return path.suffix == "" and path.name != expected_filename


def _resolve_output_json_path(args: argparse.Namespace, *, base_dir: Path) -> tuple[Path, str]:
    if args.output_json:
        output_path = _resolve_path(base_dir, args.output_json)
    elif args.ideas_log:
        legacy_path = _resolve_path(base_dir, args.ideas_log)
        if _looks_like_directory_path(legacy_path, SCREENER_RESULTS_FILENAME):
            output_path = legacy_path / CANDIDATES_FILENAME
        elif legacy_path.name == SCREENER_RESULTS_FILENAME:
            output_path = legacy_path.parent / CANDIDATES_FILENAME
        else:
            output_path = legacy_path.parent / CANDIDATES_FILENAME
    else:
        run_id = args.screen_run_id or _new_screen_run_id()
        output_path = resolve_idea_screens_root() / run_id / CANDIDATES_FILENAME

    if _looks_like_directory_path(output_path, CANDIDATES_FILENAME):
        output_path = output_path / CANDIDATES_FILENAME

    run_id_from_path = _extract_screen_run_id_from_path(output_path)

    requested_run_id = _clean_text(args.screen_run_id)
    if requested_run_id:
        _ensure_valid_screen_run_id(requested_run_id, context="--screen-run-id")

    if run_id_from_path:
        _ensure_valid_screen_run_id(run_id_from_path, context=f"path {output_path}")
        if requested_run_id and requested_run_id != run_id_from_path:
            raise ValueError(
                "--screen-run-id does not match the run folder in --output-json/--ideas-log."
            )

    resolved_run_id = requested_run_id or run_id_from_path or _new_screen_run_id()
    _ensure_valid_screen_run_id(resolved_run_id, context="screen run id")

    return output_path, resolved_run_id


def _resolve_screener_results_path(
    args: argparse.Namespace,
    *,
    base_dir: Path,
    output_json_path: Path,
    screen_run_id: str,
) -> Path:
    if args.ideas_log:
        path = _resolve_path(base_dir, args.ideas_log)
        if _looks_like_directory_path(path, SCREENER_RESULTS_FILENAME):
            path = path / SCREENER_RESULTS_FILENAME
        elif path.name == CANDIDATES_FILENAME:
            path = path.parent / SCREENER_RESULTS_FILENAME
    else:
        path = output_json_path.parent / SCREENER_RESULTS_FILENAME

    run_id_from_path = _extract_screen_run_id_from_path(path)
    if run_id_from_path:
        _ensure_valid_screen_run_id(run_id_from_path, context=f"path {path}")
        if run_id_from_path != screen_run_id:
            raise ValueError(
                "Resolved screener-results path run folder does not match screen run id."
            )
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch a broad US universe snapshot from Finviz and append LLM-selected "
            "ideas to screener-results.jsonl."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=150,
        help="Maximum number of candidates to write.",
    )
    parser.add_argument(
        "--idea-limit",
        type=int,
        default=25,
        help="Maximum number of selected ideas to append to screener-results.jsonl.",
    )
    parser.add_argument(
        "--max-pages-per-exchange",
        type=int,
        default=4,
        help="How many screener pages to scan for each US exchange.",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.2,
        help="Delay between HTTP requests to reduce rate-limit risk.",
    )
    parser.add_argument(
        "--base-dir",
        default=str(default_base_dir()),
        help="Repository root used for resolving relative paths (default: auto-detected).",
    )
    parser.add_argument(
        "--preferences-path",
        help="Override preferences path (default: <DATA_ROOT>/user_preferences.md).",
    )
    parser.add_argument(
        "--ignore-preferences",
        action="store_true",
        help="Ignore markdown preference context (deterministic guardrails are disabled).",
    )
    parser.add_argument(
        "--screen-run-id",
        help="Screen run id in strict format YYYY-MM-DD-HHMMSS.",
    )
    parser.add_argument(
        "--output-json",
        help=(
            "Output path for fetched candidate payload JSON "
            "(default: <DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/finviz-candidates.json)."
        ),
    )
    parser.add_argument(
        "--ideas-log",
        help=(
            "Output path for screener queue JSONL "
            "(default: <DATA_ROOT>/idea-screens/<SCREEN_RUN_ID>/screener-results.jsonl)."
        ),
    )
    parser.add_argument(
        "--selection-json",
        help=(
            "Path to LLM-selected ideas JSON (or '-' for stdin). "
            "Accepted shape: {'ideas':[{'ticker','thesis',...}]}."
        ),
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch candidates and write finviz-candidates.json; do not write screener-results.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help=(
            "Keep run artifacts after append. By default, run-local finviz candidates "
            "and selection files are cleaned up after successful screener append."
        ),
    )
    args = parser.parse_args()

    if args.limit <= 0:
        parser.error("--limit must be greater than 0.")
    if args.idea_limit <= 0:
        parser.error("--idea-limit must be greater than 0.")
    if args.max_pages_per_exchange <= 0:
        parser.error("--max-pages-per-exchange must be greater than 0.")
    if args.request_delay < 0:
        parser.error("--request-delay cannot be negative.")

    if args.screen_run_id:
        try:
            _ensure_valid_screen_run_id(args.screen_run_id, context="--screen-run-id")
        except ValueError as exc:
            parser.error(str(exc))

    if args.fetch_only and args.selection_json:
        parser.error("--fetch-only cannot be combined with --selection-json.")

    return args


def build_payload(
    *,
    candidates: list[dict[str, Any]],
    args: argparse.Namespace,
    preferences_applied: bool,
    preferences_path: str | None,
    output_json_path: Path,
    screen_run_id: str,
) -> dict[str, Any]:
    return {
        "fetched_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "screen_run_id": screen_run_id,
        "output_json": str(output_json_path),
        "universe": {
            "country": "USA",
            "exchanges": list(EXCHANGES.keys()),
        },
        "filters": {
            "base_filters": list(BASE_FILTERS),
            "max_pages_per_exchange": args.max_pages_per_exchange,
            "order": "-marketcap",
        },
        "preferences": {
            "applied": preferences_applied,
            "path": preferences_path,
        },
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if not lines:
        return stripped

    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _read_selection_payload(
    selection_json: str,
    *,
    base_dir: Path,
) -> list[dict[str, Any]]:
    if selection_json == "-":
        raw = sys.stdin.read()
    else:
        selection_path = _resolve_selection_json_path(selection_json, base_dir=base_dir)
        if selection_path is None:
            raise ValueError("selection path resolved to None")
        raw = selection_path.read_text(encoding="utf-8")

    payload_text = _strip_markdown_fence(raw)
    payload = json.loads(payload_text)

    if isinstance(payload, dict):
        ideas = payload.get("ideas")
        if not isinstance(ideas, list):
            raise ValueError("selection payload object must include an 'ideas' list")
        return [item for item in ideas if isinstance(item, dict)]

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    raise ValueError("selection payload must be a JSON object or array")


def _resolve_selection_json_path(
    selection_json: str,
    *,
    base_dir: Path,
) -> Path | None:
    if selection_json == "-":
        return None
    return _resolve_path(base_dir, selection_json)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _cleanup_artifacts(
    *,
    output_json_path: Path,
    selection_json_path: Path | None,
    screener_results_path: Path,
    keep_artifacts: bool,
) -> list[str]:
    if keep_artifacts:
        return []

    cleaned: list[str] = []
    run_dir = screener_results_path.resolve().parent

    candidate_path = output_json_path.resolve()
    if candidate_path.exists() and _is_within(candidate_path, run_dir):
        candidate_path.unlink()
        cleaned.append(str(candidate_path))

    if selection_json_path is not None:
        selection_path = selection_json_path.resolve()
        if (
            selection_path.exists()
            and _is_within(selection_path, run_dir)
            and selection_path != screener_results_path.resolve()
            and selection_path != candidate_path
        ):
            selection_path.unlink()
            cleaned.append(str(selection_path))

    return cleaned


def _normalize_selected_ideas(
    *,
    selected_payload: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    idea_limit: int,
) -> list[dict[str, Any]]:
    candidates_by_ticker: dict[str, dict[str, Any]] = {
        _clean_text(candidate.get("ticker")).upper(): candidate for candidate in candidates
    }

    normalized: list[dict[str, Any]] = []
    seen_tickers: set[str] = set()

    for item in selected_payload:
        ticker = _clean_text(item.get("ticker")).upper()
        if not ticker or ticker in seen_tickers:
            continue

        candidate = candidates_by_ticker.get(ticker)
        if candidate is None:
            continue

        thesis = _clean_text(item.get("thesis"))
        if not thesis:
            continue

        entry = {
            "ticker": ticker,
            "company": _clean_text(item.get("company")) or _clean_text(candidate.get("company")),
            "exchange": _clean_text(item.get("exchange")) or _clean_text(candidate.get("exchange")),
            "sector": _clean_text(item.get("sector")) or _clean_text(candidate.get("sector")),
            "industry": _clean_text(item.get("industry")) or _clean_text(candidate.get("industry")),
            "market": "us",
            "exchange_country": "US",
            "thesis": thesis,
        }

        normalized.append(entry)
        seen_tickers.add(ticker)
        if len(normalized) >= idea_limit:
            break

    return normalized


def _read_existing_tickers(path: Path) -> set[str]:
    if not path.exists():
        return set()

    tickers: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        ticker = _clean_text(payload.get("ticker")).upper()
        if ticker:
            tickers.add(ticker)
    return tickers


def _append_jsonl_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.touch()

    needs_leading_newline = False
    if path.stat().st_size > 0:
        with path.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            needs_leading_newline = handle.read(1) != b"\n"

    with path.open("a", encoding="utf-8") as handle:
        if needs_leading_newline:
            handle.write("\n")
        for line in lines:
            handle.write(line)
            handle.write("\n")


def append_selected_ideas(*, path: Path, selected_ideas: list[dict[str, Any]]) -> int:
    existing_tickers = _read_existing_tickers(path)
    lines_to_append: list[str] = []

    for idea in selected_ideas:
        ticker = _clean_text(idea.get("ticker")).upper()
        if not ticker or ticker in existing_tickers:
            continue

        entry = {
            "ticker": ticker,
            "company": _clean_text(idea.get("company")),
            "exchange": _clean_text(idea.get("exchange")),
            "sector": _clean_text(idea.get("sector")),
            "industry": _clean_text(idea.get("industry")),
            "market": "us",
            "exchange_country": "US",
            "thesis": _clean_text(idea.get("thesis")),
        }

        lines_to_append.append(json.dumps(entry, ensure_ascii=True))
        existing_tickers.add(ticker)

    if lines_to_append:
        _append_jsonl_lines(path, lines_to_append)

    return len(lines_to_append)


def main() -> int:
    args = parse_args()
    base_dir = Path(args.base_dir).resolve()

    preferences_applied = not args.ignore_preferences
    resolved_preferences_path = resolve_preferences_path(
        base_dir=base_dir,
        preferences_path=args.preferences_path,
    )
    preferences_text = (
        load_user_preferences(base_dir=base_dir, preferences_path=args.preferences_path)
        if preferences_applied
        else ""
    )
    preferences_context_present = bool(preferences_text.strip())

    raw_rows: list[dict[str, str]] = []
    for exchange_name, exchange_filter in EXCHANGES.items():
        raw_rows.extend(
            merge_exchange_rows(
                exchange_name=exchange_name,
                exchange_filter=exchange_filter,
                max_pages=args.max_pages_per_exchange,
                delay_seconds=args.request_delay,
            )
        )

    candidates = collect_candidates(
        raw_rows,
        limit=args.limit,
    )

    try:
        output_json_path, screen_run_id = _resolve_output_json_path(args, base_dir=base_dir)
        screener_results_path = _resolve_screener_results_path(
            args,
            base_dir=base_dir,
            output_json_path=output_json_path,
            screen_run_id=screen_run_id,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    payload = build_payload(
        candidates=candidates,
        args=args,
        preferences_applied=preferences_applied,
        preferences_path=(
            repo_scoped_path(resolved_preferences_path, base_dir=base_dir)
            if preferences_applied and preferences_context_present
            else None
        ),
        output_json_path=output_json_path,
        screen_run_id=screen_run_id,
    )

    output_json_path.parent.mkdir(parents=True, exist_ok=True)
    output_json_path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.fetch_only or not args.selection_json:
        print(
            json.dumps(
                {
                    "output_json": str(output_json_path),
                    "ideas_log": str(screener_results_path),
                    "screen_run_id": screen_run_id,
                    "candidate_count": len(candidates),
                    "fetch_only": bool(args.fetch_only),
                    "selection_applied": False,
                },
                ensure_ascii=True,
            )
        )
        return 0

    selection_json_path = _resolve_selection_json_path(
        args.selection_json,
        base_dir=base_dir,
    )

    try:
        selected_payload = _read_selection_payload(
            args.selection_json,
            base_dir=base_dir,
        )
    except Exception as exc:
        raise SystemExit(f"Failed to read --selection-json: {exc}") from exc

    normalized_selected = _normalize_selected_ideas(
        selected_payload=selected_payload,
        candidates=candidates,
        idea_limit=args.idea_limit,
    )
    if not normalized_selected:
        raise SystemExit(
            "No valid selected ideas after normalization. "
            "Ensure selection JSON uses candidate tickers and includes non-empty thesis values."
        )

    appended_count = append_selected_ideas(
        path=screener_results_path,
        selected_ideas=normalized_selected,
    )
    cleaned_artifacts = _cleanup_artifacts(
        output_json_path=output_json_path,
        selection_json_path=selection_json_path,
        screener_results_path=screener_results_path,
        keep_artifacts=bool(args.keep_artifacts),
    )

    print(
        json.dumps(
            {
                "output_json": str(output_json_path),
                "ideas_log": str(screener_results_path),
                "screen_run_id": screen_run_id,
                "candidate_count": len(candidates),
                "selected_count": len(normalized_selected),
                "appended_count": appended_count,
                "fetch_only": False,
                "artifacts_cleaned": cleaned_artifacts,
                "keep_artifacts": bool(args.keep_artifacts),
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
