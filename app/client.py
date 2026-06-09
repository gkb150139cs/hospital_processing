"""Async HTTP client for the upstream Hospital Directory API."""

import asyncio
import logging
from typing import Any, Optional

import httpx

from .config import Settings

logger = logging.getLogger(__name__)

# Transient statuses worth retrying (Render free tier cold starts often 502/503).
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class HospitalDirectoryError(Exception):
    """Raised when an upstream call fails after exhausting retries."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class HospitalDirectoryClient:
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings):
        self._http = http_client
        self._settings = settings

    async def _request_with_retry(
        self, method: str, path: str, json: Optional[dict[str, Any]] = None
    ) -> httpx.Response:
        last_error: Optional[Exception] = None
        for attempt in range(self._settings.max_retries + 1):
            if attempt > 0:
                delay = self._settings.retry_backoff_base_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "Retrying %s %s (attempt %d) after %.1fs", method, path, attempt + 1, delay
                )
                await asyncio.sleep(delay)
            try:
                response = await self._http.request(method, path, json=json)
            except httpx.HTTPError as exc:
                last_error = exc
                continue

            if response.status_code in RETRYABLE_STATUS_CODES:
                last_error = HospitalDirectoryError(
                    f"Upstream returned {response.status_code}",
                    status_code=response.status_code,
                )
                continue
            return response

        raise HospitalDirectoryError(
            f"{method} {path} failed after {self._settings.max_retries + 1} attempts: {last_error}"
        )

    async def create_hospital(
        self, name: str, address: str, phone: Optional[str], batch_id: str
    ) -> dict[str, Any]:
        payload = {
            "name": name,
            "address": address,
            "phone": phone,
            "creation_batch_id": batch_id,
        }
        response = await self._request_with_retry("POST", "/hospitals/", json=payload)
        if response.status_code not in (200, 201):
            raise HospitalDirectoryError(
                f"Failed to create hospital '{name}': "
                f"HTTP {response.status_code} {response.text[:200]}",
                status_code=response.status_code,
            )
        return response.json()

    async def activate_batch(self, batch_id: str) -> dict[str, Any]:
        response = await self._request_with_retry(
            "PATCH", f"/hospitals/batch/{batch_id}/activate"
        )
        if response.status_code != 200:
            raise HospitalDirectoryError(
                f"Failed to activate batch {batch_id}: "
                f"HTTP {response.status_code} {response.text[:200]}",
                status_code=response.status_code,
            )
        return response.json()

    async def get_hospitals_by_batch(self, batch_id: str) -> list[dict[str, Any]]:
        response = await self._request_with_retry("GET", f"/hospitals/batch/{batch_id}")
        if response.status_code != 200:
            raise HospitalDirectoryError(
                f"Failed to fetch batch {batch_id}: HTTP {response.status_code}",
                status_code=response.status_code,
            )
        return response.json()
