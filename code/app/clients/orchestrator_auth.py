import asyncio
import logging
from datetime import timedelta

import httpx

from app.core.config import settings
from app.utils.utils import utc_now_datetime

logger = logging.getLogger(__name__)


class OrchestratorAuth:
    def __init__(self):
        """Simple Keycloak token manager for orchestrator API calls.

        Manages an access token and expiry time with an asyncio lock to
        prevent concurrent refreshes.
        """

        self._token = None
        self._expires_at = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return a valid access token, refreshing if necessary.

        Uses an internal lock to ensure only one refresh occurs concurrently.
        """

        async with self._lock:
            if self._is_token_valid():
                return self._token

            await self._authenticate()

            return self._token

    def _is_token_valid(self) -> bool:
        """Return True if there is a non-expired token available."""

        return (
            self._token is not None
            and self._expires_at is not None
            and utc_now_datetime() < self._expires_at
        )

    async def _authenticate(self):
        """Authenticate with Keycloak and cache the access token.

        Exchanges username/password for a token and computes an expiry time.
        """

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
