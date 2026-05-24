"""Wire-level message schemas shared by TM, Scheduler, DP, and FastAPI routers."""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OpType(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    DUMMY = "DUMMY"
    COMMIT = "COMMIT"


class Timestamp(BaseModel):
    """Logical timestamp = (counter, site_id) with lexicographic total order.

    Reference: Ozsu & Valduriez 2020, Section 5.2.2.2, p. 203 (counter logic + site tiebreak).
    """

    counter: int
    site_id: int

    def as_tuple(self) -> tuple[int, int]:
        return (self.counter, self.site_id)

    def __lt__(self, other: "Timestamp") -> bool:
        return self.as_tuple() < other.as_tuple()

    def __le__(self, other: "Timestamp") -> bool:
        return self.as_tuple() <= other.as_tuple()


class Operation(BaseModel):
    """Single R/W/COMMIT op routed from a TM to a Scheduler."""

    type: OpType
    item: Optional[int] = Field(default=None, description="StepID for READ/WRITE")
    value: Optional[str] = Field(default=None, description="New Status for WRITE")
    ts: Timestamp
    tm_id: int
    tx_id: str
    op_seq: int = 0


class DummyMessage(BaseModel):
    """Heartbeat from an idle TM advertising minimum-future timestamp.

    Reference: Ozsu & Valduriez 2020, Section 5.2.2.2, p. 202.
    """

    type: Literal["DUMMY"] = "DUMMY"
    ts: Timestamp
    tm_id: int


class OpResult(BaseModel):
    ok: bool
    value: Optional[str] = None
    error: Optional[str] = None
