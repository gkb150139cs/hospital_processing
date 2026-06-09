import httpx
import pytest
import respx

from app.config import get_settings
from app.main import app

BASE_URL = get_settings().hospital_api_base_url


@pytest.fixture
async def client():
    """ASGI test client running against the app with its lifespan."""
    async with httpx.ASGITransport(app=app) as transport:
        # Lifespan startup/shutdown
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as test_client:
                yield test_client


@pytest.fixture
def mock_directory():
    """respx mock for the upstream Hospital Directory API."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as mock:
        yield mock


def csv_upload(content: str, filename: str = "hospitals.csv"):
    return {"file": (filename, content.encode(), "text/csv")}
