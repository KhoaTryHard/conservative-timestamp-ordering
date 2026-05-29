"""Tests for hash partitioning — determinism and balanced distribution."""

import json
import subprocess
import sys

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


def test_deterministic_across_processes() -> None:
    """Stable partitioning must not depend on Python's per-process hash seed."""
    machine_ids = ["M-0", "M-42", "M-99", "M-1000"]
    expected = {machine_id: site_for_machine(machine_id) for machine_id in machine_ids}
    code = """
import json
from src.tm.transaction_manager import site_for_machine
machine_ids = ["M-0", "M-42", "M-99", "M-1000"]
print(json.dumps({machine_id: site_for_machine(machine_id) for machine_id in machine_ids}))
"""

    for _ in range(5):
        output = subprocess.check_output([sys.executable, "-c", code], text=True)
        actual = json.loads(output)
        assert actual == expected
