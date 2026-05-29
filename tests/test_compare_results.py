"""Unit tests for experiment result comparison helper."""

import json

from experiments.compare_results import build_comparison, render_table


def test_build_comparison_uses_metric_keys(tmp_path) -> None:
    cto_path = tmp_path / "cto.json"
    basic_path = tmp_path / "basic_to.json"
    cto_path.write_text(
        json.dumps(
            {
                "completed": 1000,
                "avg_ms": 37.875,
                "p95_ms": 62.731,
                "p99_ms": 112.586,
                "max_ms": 121.161,
                "total_restarts": 0,
            }
        ),
        encoding="utf-8",
    )
    basic_path.write_text(
        json.dumps(
            {
                "completed": 1000,
                "avg_ms": 7.942,
                "p95_ms": 14.451,
                "p99_ms": 17.032,
                "max_ms": 24.972,
                "total_restarts": 0,
            }
        ),
        encoding="utf-8",
    )

    rows = build_comparison(str(cto_path), str(basic_path))

    assert rows[0] == {"metric": "completed", "CTO": "1000", "Basic TO": "1000"}
    assert {"metric": "avg_ms", "CTO": "37.875", "Basic TO": "7.942"} in rows
    assert {"metric": "total_restarts", "CTO": "0", "Basic TO": "0"} in rows


def test_render_table_contains_headers() -> None:
    table = render_table(
        [
            {"metric": "avg_ms", "CTO": "37.875", "Basic TO": "7.942"},
            {"metric": "total_restarts", "CTO": "0", "Basic TO": "0"},
        ]
    )

    assert "metric" in table
    assert "CTO" in table
    assert "Basic TO" in table
    assert "avg_ms" in table
