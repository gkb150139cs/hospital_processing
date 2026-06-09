"""Unit tests for the upstream client's retry behavior."""

import httpx
import pytest
import respx

from app.client import HospitalDirectoryClient, HospitalDirectoryError
from app.config import Settings

SETTINGS = Settings(
    hospital_api_base_url="https://upstream.test",
    max_retries=2,
    retry_backoff_base_seconds=0.0,
)


@pytest.fixture
def upstream():
    with respx.mock(base_url=SETTINGS.hospital_api_base_url) as mock:
        yield mock


@pytest.fixture
async def client():
    async with httpx.AsyncClient(base_url=SETTINGS.hospital_api_base_url) as http:
        yield HospitalDirectoryClient(http, SETTINGS)


async def test_retries_transient_errors_then_succeeds(upstream, client):
    route = upstream.post("/hospitals/").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(502),
            httpx.Response(200, json={"id": 1, "name": "A", "address": "B"}),
        ]
    )
    hospital = await client.create_hospital("A", "B", None, "batch-1")
    assert hospital["id"] == 1
    assert route.call_count == 3


async def test_gives_up_after_max_retries(upstream, client):
    upstream.post("/hospitals/").mock(return_value=httpx.Response(503))
    with pytest.raises(HospitalDirectoryError, match="failed after 3 attempts"):
        await client.create_hospital("A", "B", None, "batch-1")


async def test_does_not_retry_client_errors(upstream, client):
    route = upstream.post("/hospitals/").mock(
        return_value=httpx.Response(422, json={"detail": "bad"})
    )
    with pytest.raises(HospitalDirectoryError, match="422"):
        await client.create_hospital("A", "B", None, "batch-1")
    assert route.call_count == 1


async def test_retries_network_errors(upstream, client):
    route = upstream.patch("/hospitals/batch/b1/activate").mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"activated": 1}),
        ]
    )
    result = await client.activate_batch("b1")
    assert result == {"activated": 1}
    assert route.call_count == 2
