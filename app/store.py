"""In-memory storage for batch processing state.

A simple dict keyed by batch ID is sufficient for this assignment (the spec
explicitly allows in-memory persistence). All mutation happens on the event
loop, so no locking is required.
"""

from typing import Optional

from .models import BatchRecord


class BatchStore:
    def __init__(self) -> None:
        self._batches: dict[str, BatchRecord] = {}

    def save(self, record: BatchRecord) -> None:
        self._batches[record.batch_id] = record

    def get(self, batch_id: str) -> Optional[BatchRecord]:
        return self._batches.get(batch_id)

    def list_all(self) -> list[BatchRecord]:
        return sorted(
            self._batches.values(), key=lambda record: record.created_at, reverse=True
        )

    def clear(self) -> None:
        self._batches.clear()
