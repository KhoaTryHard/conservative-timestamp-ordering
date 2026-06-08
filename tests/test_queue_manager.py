"""Unit tests for QueueManager — enqueue, all_non_empty, pop_min ordering."""

from src.common.messages import Operation, OpType, Timestamp
from src.scheduler.queue_manager import QueueManager


def _op(tm_id: int, counter: int, site_id: int = 0, step_id: int = 1) -> Operation:
    return Operation(
        type=OpType.WRITE,
        item=step_id,
        value="IN_PROGRESS",
        ts=Timestamp(counter=counter, site_id=site_id),
        tm_id=tm_id,
        tx_id=f"tx-{tm_id}-{counter}",
    )


def test_all_non_empty_false_when_one_queue_empty() -> None:
    qm = QueueManager(known_tm_ids=[0, 1, 2])
    qm.enqueue(_op(tm_id=0, counter=1))
    qm.enqueue(_op(tm_id=1, counter=2))
    # TM 2 has nothing
    assert qm.all_non_empty() is False


def test_all_non_empty_true_when_all_queues_filled() -> None:
    qm = QueueManager(known_tm_ids=[0, 1, 2])
    for tm_id in range(3):
        qm.enqueue(_op(tm_id=tm_id, counter=10 + tm_id))
    assert qm.all_non_empty() is True


def test_pop_min_returns_globally_minimum_ts() -> None:
    qm = QueueManager(known_tm_ids=[0, 1, 2])
    qm.enqueue(_op(tm_id=0, counter=5))
    qm.enqueue(_op(tm_id=1, counter=3))
    qm.enqueue(_op(tm_id=2, counter=7))
    op = qm.pop_min()
    assert op is not None
    assert op.ts.counter == 3  # min across heads


def test_pop_min_returns_none_when_not_all_queues_filled() -> None:
    qm = QueueManager(known_tm_ids=[0, 1])
    qm.enqueue(_op(tm_id=0, counter=1))
    # TM 1 empty
    assert qm.pop_min() is None
