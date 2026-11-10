import time
from types import SimpleNamespace

import jwt
import pytest
from app.clients.storage_client import get_storage_client
from app.core import security
from app.core.config import settings
from app.main import app
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from tests.utils import (
    MODEL_UUID,
    MODEL_VERSION,
    create_new_mock_storage,
    get_generation_metadata,
    get_signing_event,
)

REALM_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)

SIGN_URL = "/api/sign"
SIGN_BODY = get_signing_event(f"reports/{MODEL_UUID}/{MODEL_VERSION}/risk_report.json")


class FakeJWKSClient:
    """Stands in for the realm's JWKS endpoint, serving REALM_KEY."""

    def __init__(self, error: Exception | None = None):
        self.error = error

    def get_signing_key_from_jwt(self, token: str):
        if self.error:
            raise self.error
        return SimpleNamespace(key=REALM_KEY.public_key())


def make_token(key=REALM_KEY, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": security.issuer(),
        "sub": "user-id",
        "aud": "account",
        "typ": "Bearer",
        "azp": "coevolution-orchestrator",
        "iat": now,
        "exp": now + 300,
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="RS256")


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "KEYCLOAK_AUDIENCE", None)
    monkeypatch.setattr(security, "get_jwks_client", lambda: FakeJWKSClient())
    storage = create_new_mock_storage()
    app.dependency_overrides[get_storage_client] = lambda: storage
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.anyio
async def test_valid_token_is_accepted(client):
    response = await client.post(SIGN_URL, json=SIGN_BODY, headers=bearer(make_token()))

    assert response.status_code == 201


@pytest.mark.parametrize(
    "url, body",
    [
        (SIGN_URL, SIGN_BODY),
        ("/api/generate", get_generation_metadata(MODEL_UUID, MODEL_VERSION)),
    ],
)
@pytest.mark.anyio
async def test_missing_token_is_rejected(client, url, body):
    response = await client.post(url, json=body)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token",
    [
        make_token(exp=int(time.time()) - 10),
        make_token(iss="https://other.example/realms/coevolution"),
        make_token(key=OTHER_KEY),
        make_token(typ="ID"),
        "not-a-jwt",
    ],
    ids=["expired", "wrong-issuer", "wrong-key", "id-token", "malformed"],
)
@pytest.mark.anyio
async def test_invalid_token_is_rejected(client, token):
    response = await client.post(SIGN_URL, json=SIGN_BODY, headers=bearer(token))

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid access token"}


@pytest.mark.parametrize("aud, expected_status", [("strae", 201), ("account", 401)])
@pytest.mark.anyio
async def test_audience_is_checked_when_configured(
    client, monkeypatch, aud, expected_status
):
    monkeypatch.setattr(settings, "KEYCLOAK_AUDIENCE", "strae")

    response = await client.post(
        SIGN_URL, json=SIGN_BODY, headers=bearer(make_token(aud=aud))
    )

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    "error, expected_status",
    [
        (jwt.PyJWKClientConnectionError("down"), 503),
        (jwt.PyJWKClientError("unknown kid"), 401),
    ],
)
@pytest.mark.anyio
async def test_key_lookup_failure(client, monkeypatch, error, expected_status):
    monkeypatch.setattr(security, "get_jwks_client", lambda: FakeJWKSClient(error))

    response = await client.post(SIGN_URL, json=SIGN_BODY, headers=bearer(make_token()))

    assert response.status_code == expected_status


@pytest.mark.anyio
async def test_auth_disabled_accepts_requests_without_token(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", False)

    response = await client.post(SIGN_URL, json=SIGN_BODY)

    assert response.status_code == 201


@pytest.mark.parametrize("url", ["/api/status", "/api/validation/unknown/v1.0"])
@pytest.mark.anyio
async def test_read_endpoints_are_public(client, url):
    response = await client.get(url)

    assert response.status_code != 401
