"""Unit tests for deterministic failure demo helpers."""

import pytest

from experiments.demo_failure import DemoStats, _build_result, get_container_name, parse_args


def test_parse_args_defaults() -> None:
    args = parse_args(
        [
            "--mode",
            "cto",
            "--out",
            "experiments/results/cto_failure.json",
        ]
    )
    assert args.mode == "cto"
    assert args.seed == 42
    assert args.kill_site == 1
    assert args.kill_delay_sec == 5.0
    assert args.restart_delay_sec == 8.0
    assert args.manual_failure is False


def test_get_container_name_for_site_b() -> None:
    assert get_container_name(1) == "cto-site-b"


def test_get_container_name_rejects_unknown_site() -> None:
    with pytest.raises(ValueError, match="Unknown site id"):
        get_container_name(9)


def test_result_json_schema_minimum_fields() -> None:
    args = parse_args(
        [
            "--mode",
            "cto",
            "--seed",
            "42",
            "--kill-site",
            "1",
            "--out",
            "experiments/results/cto_failure.json",
        ]
    )
    stats = DemoStats(total_submitted=2, total_completed=1, total_restarts=0)
    stats.latencies_ms.append(12.3456)
    result = _build_result(args, "cto-site-b", stats, downtime_ms=8000.1234)

    assert result["mode"] == "cto"
    assert result["seed"] == 42
    assert result["killed_site"] == 1
    assert result["killed_container"] == "cto-site-b"
    assert result["total_submitted"] == 2
    assert result["total_completed"] == 1
    assert result["total_restarts"] == 0
    assert result["stall_observed"] is None
    assert result["failure_window_ms"] == 8000.123
    assert result["average_latency_ms"] == 12.346
    assert "notes" in result
