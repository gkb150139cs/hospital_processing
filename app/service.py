"""Bulk processing orchestration.

Hospitals are created concurrently (bounded by a semaphore) against the
upstream Hospital Directory API. Once every hospital in the batch has been
created successfully, the batch is activated in a single PATCH call.
Progress is written to the in-memory store as each row completes, so a
polling client can observe progress while processing is in flight.
"""

import asyncio
import logging
import time
import uuid

from .client import HospitalDirectoryClient, HospitalDirectoryError
from .config import Settings
from .models import (
    BatchRecord,
    BatchState,
    BulkProcessResponse,
    HospitalRow,
    RowResult,
    RowStatus,
)
from .store import BatchStore

logger = logging.getLogger(__name__)


class BulkProcessor:
    def __init__(
        self, client: HospitalDirectoryClient, store: BatchStore, settings: Settings
    ):
        self._client = client
        self._store = store
        self._settings = settings

    async def process_batch(self, rows: list[HospitalRow]) -> BulkProcessResponse:
        """Create a new batch and process all rows."""
        batch_id = str(uuid.uuid4())
        record = BatchRecord(
            batch_id=batch_id,
            total_hospitals=len(rows),
            rows=rows,
            results=[RowResult(row=row.row, name=row.name) for row in rows],
        )
        self._store.save(record)
        return await self._run(record, rows)

    async def resume_batch(self, record: BatchRecord) -> BulkProcessResponse:
        """Retry only the rows that previously failed in a batch."""
        failed_row_numbers = {
            result.row for result in record.results if result.status == RowStatus.FAILED
        }
        pending_rows = [row for row in record.rows if row.row in failed_row_numbers]

        record.state = BatchState.PROCESSING
        record.failed_hospitals = 0
        record.processing_time_seconds = None
        for result in record.results:
            if result.status == RowStatus.FAILED:
                result.status = RowStatus.PENDING
                result.error = None

        return await self._run(record, pending_rows)

    async def _run(
        self, record: BatchRecord, rows: list[HospitalRow]
    ) -> BulkProcessResponse:
        started = time.monotonic()
        semaphore = asyncio.Semaphore(self._settings.max_concurrent_requests)
        results_by_row = {result.row: result for result in record.results}

        async def create_one(row: HospitalRow) -> None:
            result = results_by_row[row.row]
            async with semaphore:
                try:
                    hospital = await self._client.create_hospital(
                        name=row.name,
                        address=row.address,
                        phone=row.phone,
                        batch_id=record.batch_id,
                    )
                except HospitalDirectoryError as exc:
                    result.status = RowStatus.FAILED
                    result.error = str(exc)
                    record.failed_hospitals += 1
                    logger.error("Row %d (%s) failed: %s", row.row, row.name, exc)
                else:
                    result.hospital_id = hospital.get("id")
                    result.status = RowStatus.CREATED
                    record.processed_hospitals += 1

        await asyncio.gather(*(create_one(row) for row in rows))

        # Per spec: only activate once ALL hospitals were created successfully.
        all_created = record.failed_hospitals == 0 and all(
            result.status in (RowStatus.CREATED, RowStatus.CREATED_AND_ACTIVATED)
            for result in record.results
        )
        if all_created and not record.batch_activated:
            try:
                await self._client.activate_batch(record.batch_id)
                record.batch_activated = True
            except HospitalDirectoryError as exc:
                logger.error("Batch %s activation failed: %s", record.batch_id, exc)

        if record.batch_activated:
            for result in record.results:
                if result.status == RowStatus.CREATED:
                    result.status = RowStatus.CREATED_AND_ACTIVATED

        record.state = (
            BatchState.COMPLETED
            if record.failed_hospitals == 0
            else BatchState.COMPLETED_WITH_ERRORS
        )
        record.processing_time_seconds = round(time.monotonic() - started, 2)

        return BulkProcessResponse(
            batch_id=record.batch_id,
            total_hospitals=record.total_hospitals,
            processed_hospitals=record.processed_hospitals,
            failed_hospitals=record.failed_hospitals,
            processing_time_seconds=record.processing_time_seconds,
            batch_activated=record.batch_activated,
            hospitals=record.results,
        )
