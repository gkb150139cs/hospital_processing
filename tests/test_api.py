"""Integration tests for the API with the upstream directory mocked via respx."""

import itertools

import httpx

from tests.conftest import csv_upload

VALID_CSV = (
    "name,address,phone\n"
    "General Hospital,123 Main St,555-1234\n"
    "City Clinic,456 Oak Ave,\n"
    "County Medical,789 Pine Rd,555-9876\n"
)


def mock_create_success(mock_directory, start_id=101):
    counter = itertools.count(start_id)

    def responder(request):
        import json

        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": next(counter),
                "name": payload["name"],
                "address": payload["address"],
                "phone": payload.get("phone"),
                "creation_batch_id": payload.get("creation_batch_id"),
                "active": False,
                "created_at": "2026-01-01T00:00:00Z",
            },
        )

    return mock_directory.post("/hospitals/").mock(side_effect=responder)


async def test_health(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_bulk_create_success(client, mock_directory):
    mock_create_success(mock_directory)
    activate_route = mock_directory.patch(url__regex=r"/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(200, json={"activated": 3})
    )

    response = await client.post("/hospitals/bulk", files=csv_upload(VALID_CSV))
    assert response.status_code == 200
    body = response.json()

    assert body["total_hospitals"] == 3
    assert body["processed_hospitals"] == 3
    assert body["failed_hospitals"] == 0
    assert body["batch_activated"] is True
    assert activate_route.called
    assert all(h["status"] == "created_and_activated" for h in body["hospitals"])
    assert body["hospitals"][0]["hospital_id"] == 101


async def test_bulk_partial_failure_skips_activation(client, mock_directory):
    calls = itertools.count()

    def flaky(request):
        n = next(calls)
        if n == 0:
            return httpx.Response(422, json={"detail": "bad hospital"})
        return httpx.Response(200, json={"id": 200 + n, "name": "x", "address": "y"})

    mock_directory.post("/hospitals/").mock(side_effect=flaky)
    activate_route = mock_directory.patch(url__regex=r"/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(200, json={})
    )

    response = await client.post("/hospitals/bulk", files=csv_upload(VALID_CSV))
    assert response.status_code == 200
    body = response.json()

    assert body["failed_hospitals"] == 1
    assert body["processed_hospitals"] == 2
    assert body["batch_activated"] is False
    assert not activate_route.called
    statuses = {h["status"] for h in body["hospitals"]}
    assert statuses == {"failed", "created"}


async def test_bulk_rejects_invalid_rows(client):
    bad_csv = "name,address,phone\n,No Name St,\n"
    response = await client.post("/hospitals/bulk", files=csv_upload(bad_csv))
    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["row"] == 1


async def test_bulk_rejects_oversized_csv(client):
    rows = "".join(f"H{i},Addr {i},\n" for i in range(25))
    response = await client.post(
        "/hospitals/bulk", files=csv_upload(f"name,address,phone\n{rows}")
    )
    assert response.status_code == 400
    assert "maximum allowed" in response.json()["detail"]


async def test_bulk_rejects_non_csv_file(client):
    response = await client.post(
        "/hospitals/bulk", files={"file": ("data.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 400


async def test_validate_endpoint(client):
    csv_content = "name,address,phone\nGood,1 Main St,\n,Bad Row,\n"
    response = await client.post("/hospitals/bulk/validate", files=csv_upload(csv_content))
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert body["total_rows"] == 2
    assert body["valid_rows"] == 1
    assert len(body["errors"]) == 1


async def test_batch_progress_and_results(client, mock_directory):
    mock_create_success(mock_directory)
    mock_directory.patch(url__regex=r"/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(200, json={})
    )

    created = await client.post("/hospitals/bulk", files=csv_upload(VALID_CSV))
    batch_id = created.json()["batch_id"]

    progress = await client.get(f"/batches/{batch_id}")
    assert progress.status_code == 200
    body = progress.json()
    assert body["state"] == "completed"
    assert body["progress_percent"] == 100.0

    results = await client.get(f"/batches/{batch_id}/results")
    assert results.status_code == 200
    assert len(results.json()["hospitals"]) == 3

    listing = await client.get("/batches")
    assert listing.status_code == 200
    assert any(b["batch_id"] == batch_id for b in listing.json())


async def test_batch_not_found(client):
    response = await client.get("/batches/does-not-exist")
    assert response.status_code == 404


async def test_resume_retries_failed_rows(client, mock_directory):
    calls = itertools.count()

    def fail_first(request):
        n = next(calls)
        if n == 0:
            return httpx.Response(400, json={"detail": "boom"})
        return httpx.Response(200, json={"id": 300 + n, "name": "x", "address": "y"})

    mock_directory.post("/hospitals/").mock(side_effect=fail_first)
    activate_route = mock_directory.patch(url__regex=r"/hospitals/batch/.+/activate").mock(
        return_value=httpx.Response(200, json={})
    )

    created = await client.post("/hospitals/bulk", files=csv_upload(VALID_CSV))
    body = created.json()
    assert body["failed_hospitals"] == 1
    assert body["batch_activated"] is False
    batch_id = body["batch_id"]

    resumed = await client.post(f"/batches/{batch_id}/resume")
    assert resumed.status_code == 200
    resumed_body = resumed.json()
    assert resumed_body["failed_hospitals"] == 0
    assert resumed_body["processed_hospitals"] == 3
    assert resumed_body["batch_activated"] is True
    assert activate_route.called

    # A second resume should be rejected: nothing left to retry.
    again = await client.post(f"/batches/{batch_id}/resume")
    assert again.status_code == 409
