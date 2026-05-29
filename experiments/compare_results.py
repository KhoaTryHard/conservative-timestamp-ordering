"""Compare CTO and Basic TO experiment result JSON files.

Usage:
    python -m experiments.compare_results experiments/results/cto.json \
      experiments/results/basic_to.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_METRIC_KEYS = [
    "completed",
    "avg_ms",
    "p95_ms",
    "p99_ms",
    "max_ms",
    "total_restarts",
]


def load_result(path: str) -> dict[str, Any]:
    """Load one experiment result JSON file."""
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _label_from_path(path: str) -> str:
    """Infer a compact scheduler label from a result file name."""
    stem = Path(path).stem.lower()
    if "basic" in stem:
        return "Basic TO"
    if "cto" in stem:
        return "CTO"
    return Path(path).stem


def _format_value(value: Any) -> str:
    """Format a metric value for terminal table output."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def build_comparison(left_path: str, right_path: str) -> list[dict[str, str]]:
    """Return comparison rows for two result JSON files."""
    left = load_result(left_path)
    right = load_result(right_path)
    left_label = _label_from_path(left_path)
    right_label = _label_from_path(right_path)

    rows: list[dict[str, str]] = []
    for key in _METRIC_KEYS:
        rows.append(
            {
                "metric": key,
                left_label: _format_value(left.get(key)),
                right_label: _format_value(right.get(key)),
            }
        )
    return rows


def render_table(rows: list[dict[str, str]]) -> str:
    """Render comparison rows as a plain ASCII table."""
    if not rows:
        return ""

    headers = list(rows[0].keys())
    widths = {
        header: max(len(header), *(len(row.get(header, "")) for row in rows)) for header in headers
    }
    header_line = " | ".join(header.ljust(widths[header]) for header in headers)
    separator = "-+-".join("-" * widths[header] for header in headers)
    body = [
        " | ".join(row.get(header, "").ljust(widths[header]) for header in headers) for row in rows
    ]
    return "\n".join([header_line, separator, *body])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Compare CTO and Basic TO result JSON")
    parser.add_argument("cto_json", help="Path to CTO result JSON")
    parser.add_argument("basic_to_json", help="Path to Basic TO result JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint."""
    args = parse_args(argv)
    rows = build_comparison(args.cto_json, args.basic_to_json)
    print(render_table(rows))
    print()
    print("Notes:")
    print("- avg_ms is the Average Transaction Latency used for the project metric.")
    print("- total_restarts should be read together with latency to explain the trade-off.")


if __name__ == "__main__":
    main()
