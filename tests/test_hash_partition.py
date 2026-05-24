"""Tests for hash partitioning — determinism and balanced distribution."""

from src.tm.transaction_manager import site_for_machine


def test_deterministic() -> None:
    assert site_for_machine("M-42") == site_for_machine("M-42")
    assert site_for_machine("M-0") == site_for_machine("M-0")


def test_returns_valid_site_index() -> None:
    for i in range(100):
        idx = site_for_machine(f"M-{i}")
        assert 0 <= idx <= 2


def test_distribution_is_balanced() -> None:
    """Each site should receive ~33% of 3000 machines (within ±15%)."""
    counts = [0, 0, 0]
    for i in range(3000):
        counts[site_for_machine(f"M-{i}")] += 1
    assert all(850 <= c <= 1150 for c in counts)
