import asyncio
import logging
from datetime import timedelta

import httpx

from app.config import settings
from app.utils import utc_now_datetime

logger = logging.getLogger(__name__)


class OrchestratorAuth:
    def __init__(self):
        self._token = None
        self._expires_at = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        async with self._lock:
            if self._is_token_valid():
                return self._token

            await self._authenticate()

            return self._token

    def _is_token_valid(self) -> bool:
        return (
            self._token is not None
            and self._expires_at is not None
            and utc_now_datetime() < self._expires_at
        )

    async def _authenticate(self):
        logger.info("Authenticating with orchestrator")

        async with httpx.AsyncClient(base_url=settings.KEYCLOAK_BASE_URL) as client:
            response = await client.post(
                (f"/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"),
                headers={"Content-Type": ("application/x-www-form-urlencoded")},
                data={
                    "grant_type": "password",
                    "client_id": settings.KEYCLOAK_CLIENT_ID,
                    "username": settings.ORCHESTRATOR_USERNAME,
                    "password": settings.ORCHESTRATOR_PASSWORD,
                },
            )

            response.raise_for_status()

            payload = response.json()

            self._token = payload["access_token"]

            expires_in = payload.get("expires_in", 3600)
            if "expires_in" not in payload:
                logger.warning("Keycloak did not return expires_in, using default 3600")

            self._expires_at = utc_now_datetime() + timedelta(seconds=expires_in - 60)

            logger.info("Authentication successful")
