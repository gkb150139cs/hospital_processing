# Hospital Bulk Processing System

A FastAPI service that accepts CSV uploads of hospitals, creates each hospital in the
[Hospital Directory API](https://hospital-directory.onrender.com/docs) under a unique
batch ID, and activates the whole batch once **every** hospital has been created
successfully.

## Architecture

```
┌──────────┐  CSV upload   ┌─────────────────────────────┐   POST /hospitals/        ┌────────────────────┐
│  Client  │ ────────────► │  Bulk Processing API (this) │ ────────────────────────► │ Hospital Directory │
│          │ ◄──────────── │  - CSV validation           │   (concurrent, retried)   │ API (upstream)     │
└──────────┘   results     │  - batch orchestration      │                           └────────────────────┘
                           │  - in-memory batch store    │   PATCH /hospitals/batch/
                           └─────────────────────────────┘   {batch_id}/activate
```

| Module | Responsibility |
|---|---|
| `app/main.py` | FastAPI app, routes, dependency wiring |
| `app/csv_parser.py` | CSV parsing + file-level and row-level validation |
| `app/client.py` | Async upstream client with retries and exponential backoff |
| `app/service.py` | Batch orchestration: concurrent creation, activation, resume |
| `app/store.py` | In-memory batch store (allowed by the spec) |
| `app/models.py` | Pydantic schemas and batch state machine |
| `app/config.py` | Environment-driven settings |

### Design decisions

- **Concurrency with a bound:** hospital creations run concurrently via `asyncio.gather`
  limited by a semaphore (default 5) — fast without hammering the upstream API.
- **Retries with exponential backoff:** transient upstream failures (429/5xx, network
  errors — common with Render cold starts) are retried up to 3 times. Client errors
  (4xx) are not retried.
- **All-or-nothing activation:** per the spec, the batch is activated only when every
  hospital was created. CSVs containing invalid rows are rejected up front (422) so a
  batch never starts doomed; the `/hospitals/bulk/validate` endpoint lets clients
  pre-check files.
- **Resumability:** if some rows fail at runtime (e.g. upstream outage), the batch is
  kept with per-row status and `POST /batches/{batch_id}/resume` retries only the
  failed rows, then activates the batch when everything has succeeded.
- **Live progress:** batch state is updated as each row completes, so
  `GET /batches/{batch_id}` can be polled while an upload is being processed.

## API

Interactive docs: `http://localhost:8000/docs`

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Health check |
| `POST` | `/hospitals/bulk` | Upload CSV and process the batch (multipart `file`) |
| `POST` | `/hospitals/bulk/validate` | Validate a CSV without processing it |
| `GET` | `/batches` | List all batches processed by this instance |
| `GET` | `/batches/{batch_id}` | Poll batch progress/status |
| `GET` | `/batches/{batch_id}/results` | Full per-hospital results for a batch |
| `POST` | `/batches/{batch_id}/resume` | Retry the failed hospitals of a batch |

### CSV format

```csv
name,address,phone
General Hospital,123 Main St,555-1234
City Clinic,456 Oak Ave,
```

- Header `name,address,phone` (phone optional per row, column required in header)
- Maximum **20** hospitals per file (configurable)
- UTF-8 (BOM tolerated)

### Example

```bash
curl -X POST http://localhost:8000/hospitals/bulk \
  -F "file=@samples/hospitals.csv"
```

```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "total_hospitals": 5,
  "processed_hospitals": 5,
  "failed_hospitals": 0,
  "processing_time_seconds": 1.42,
  "batch_activated": true,
  "hospitals": [
    {
      "row": 1,
      "hospital_id": 101,
      "name": "General Hospital",
      "status": "created_and_activated",
      "error": null
    }
  ]
}
```

## Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### With Docker

```bash
docker compose up --build
# service available at http://localhost:8000
```

## Configuration

All settings can be overridden via environment variables (or a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `HOSPITAL_API_BASE_URL` | `https://hospital-directory.onrender.com` | Upstream API base URL |
| `MAX_CSV_ROWS` | `20` | Maximum hospitals per CSV |
| `MAX_CONCURRENT_REQUESTS` | `5` | Concurrent upstream creation calls |
| `REQUEST_TIMEOUT_SECONDS` | `30` | Upstream request timeout |
| `MAX_RETRIES` | `3` | Retries for transient upstream failures |
| `RETRY_BACKOFF_BASE_SECONDS` | `0.5` | Exponential backoff base delay |

## Testing

The test suite mocks the upstream API with [respx](https://lundberg.github.io/respx/) —
no network access needed.

```bash
pip install -r requirements-dev.txt
pytest -v
```

Coverage includes: CSV parsing edge cases (BOM, missing/unknown columns, row limits,
row-level errors), the full bulk happy path, partial failures skipping activation,
resume flow, progress/results endpoints, and client retry/backoff behavior.

## Deployment (Render)

1. Push this repo to GitHub.
2. Create a **Web Service** on [Render](https://render.com), pointing at the repo.
3. Select **Docker** as the runtime — the included `Dockerfile` is used automatically.
4. No additional configuration required (defaults target the deployed directory API).
