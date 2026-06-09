import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status

from .client import HospitalDirectoryClient
from .config import Settings, get_settings
from .csv_parser import CsvFormatError, parse_hospitals_csv
from .models import (
    BatchProgressResponse,
    BatchRecord,
    BatchState,
    BulkProcessResponse,
    CsvValidationResponse,
)
from .service import BulkProcessor
from .store import BatchStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    http_client = httpx.AsyncClient(
        base_url=settings.hospital_api_base_url,
        timeout=settings.request_timeout_seconds,
    )
    app.state.settings = settings
    app.state.store = BatchStore()
    app.state.processor = BulkProcessor(
        client=HospitalDirectoryClient(http_client, settings),
        store=app.state.store,
        settings=settings,
    )
    try:
        yield
    finally:
        await http_client.aclose()


app = FastAPI(
    title="Hospital Bulk Processing API",
    description=(
        "Bulk processing system that accepts CSV uploads of hospitals, creates "
        "them in the Hospital Directory API under a unique batch ID, and "
        "activates the batch once every hospital has been created."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


def get_store(request: Request) -> BatchStore:
    return request.app.state.store


def get_processor(request: Request) -> BulkProcessor:
    return request.app.state.processor


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


async def read_csv_upload(file: UploadFile) -> bytes:
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only .csv files are accepted",
        )
    return await file.read()


@app.get("/", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "hospital-bulk-processing"}


@app.post(
    "/hospitals/bulk",
    response_model=BulkProcessResponse,
    tags=["bulk"],
    summary="Bulk create hospitals from a CSV file",
)
async def bulk_create_hospitals(
    file: UploadFile = File(..., description="CSV with header: name,address,phone"),
    processor: BulkProcessor = Depends(get_processor),
    settings: Settings = Depends(get_app_settings),
) -> BulkProcessResponse:
    content = await read_csv_upload(file)
    try:
        rows, row_errors = parse_hospitals_csv(content, max_rows=settings.max_csv_rows)
    except CsvFormatError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if row_errors:
        # All-or-nothing: a batch is only activated when every hospital is
        # created, so reject files containing invalid rows up front.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "CSV contains invalid rows; fix them and re-upload",
                "errors": [error.model_dump() for error in row_errors],
            },
        )

    return await processor.process_batch(rows)


@app.post(
    "/hospitals/bulk/validate",
    response_model=CsvValidationResponse,
    tags=["bulk"],
    summary="Validate a CSV file without processing it",
)
async def validate_csv(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_app_settings),
) -> CsvValidationResponse:
    content = await read_csv_upload(file)
    try:
        rows, row_errors = parse_hospitals_csv(content, max_rows=settings.max_csv_rows)
    except CsvFormatError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return CsvValidationResponse(
        valid=not row_errors,
        total_rows=len(rows) + len(row_errors),
        valid_rows=len(rows),
        errors=row_errors,
    )


@app.get(
    "/batches",
    response_model=list[BatchProgressResponse],
    tags=["batches"],
    summary="List all batches processed by this service",
)
async def list_batches(store: BatchStore = Depends(get_store)) -> list[BatchProgressResponse]:
    return [_to_progress(record) for record in store.list_all()]


@app.get(
    "/batches/{batch_id}",
    response_model=BatchProgressResponse,
    tags=["batches"],
    summary="Poll progress/status of a batch",
)
async def get_batch_progress(
    batch_id: str, store: BatchStore = Depends(get_store)
) -> BatchProgressResponse:
    record = _get_record_or_404(store, batch_id)
    return _to_progress(record)


@app.get(
    "/batches/{batch_id}/results",
    response_model=BulkProcessResponse,
    tags=["batches"],
    summary="Get full per-hospital results for a batch",
)
async def get_batch_results(
    batch_id: str, store: BatchStore = Depends(get_store)
) -> BulkProcessResponse:
    record = _get_record_or_404(store, batch_id)
    return BulkProcessResponse(
        batch_id=record.batch_id,
        total_hospitals=record.total_hospitals,
        processed_hospitals=record.processed_hospitals,
        failed_hospitals=record.failed_hospitals,
        processing_time_seconds=record.processing_time_seconds or 0.0,
        batch_activated=record.batch_activated,
        hospitals=record.results,
    )


@app.post(
    "/batches/{batch_id}/resume",
    response_model=BulkProcessResponse,
    tags=["batches"],
    summary="Retry the failed hospitals of a previously processed batch",
)
async def resume_batch(
    batch_id: str,
    store: BatchStore = Depends(get_store),
    processor: BulkProcessor = Depends(get_processor),
) -> BulkProcessResponse:
    record = _get_record_or_404(store, batch_id)
    if record.state == BatchState.PROCESSING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Batch is still processing",
        )
    if record.failed_hospitals == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Batch has no failed hospitals to resume",
        )
    return await processor.resume_batch(record)


def _get_record_or_404(store: BatchStore, batch_id: str) -> BatchRecord:
    record = store.get(batch_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch {batch_id} not found",
        )
    return record


def _to_progress(record: BatchRecord) -> BatchProgressResponse:
    completed = record.processed_hospitals + record.failed_hospitals
    percent = (completed / record.total_hospitals * 100) if record.total_hospitals else 0.0
    return BatchProgressResponse(
        batch_id=record.batch_id,
        state=record.state,
        total_hospitals=record.total_hospitals,
        processed_hospitals=record.processed_hospitals,
        failed_hospitals=record.failed_hospitals,
        progress_percent=round(percent, 1),
        batch_activated=record.batch_activated,
        created_at=record.created_at,
        processing_time_seconds=record.processing_time_seconds,
    )
