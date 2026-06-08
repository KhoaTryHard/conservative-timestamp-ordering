"""Unit tests for ClockSync — monotonicity and site_id tiebreak."""

from src.common.clock_sync import ClockSync


def test_next_is_monotonic() -> None:
    clock = ClockSync(site_id=0)
    t1 = clock.next()
    t2 = clock.next()
    assert t1 < t2


def test_observe_advances_counter() -> None:
    clock = ClockSync(site_id=0)
    from src.common.messages import Timestamp

    clock.observe(Timestamp(counter=999, site_id=1))
    t = clock.next()
    assert t.counter > 999


def test_tiebreak_by_site_id() -> None:
    from src.common.messages import Timestamp

    t0 = Timestamp(counter=5, site_id=0)
    t1 = Timestamp(counter=5, site_id=1)
    assert t0 < t1


def test_peek_does_not_advance() -> None:
    clock = ClockSync(site_id=0)
    p1 = clock.peek()
    p2 = clock.peek()
    assert p1.counter == p2.counter
