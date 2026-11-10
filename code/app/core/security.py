"""Bearer token authentication for the API, using the orchestrator's Keycloak.

Access tokens are validated locally: the signature against the realm's
public keys (JWKS), and the `iss`, `exp` and `typ` claims. The audience is
only checked when `KEYCLOAK_AUDIENCE` is set, as Keycloak does not add the
service to `aud` without an audience mapper on the calling client.
"""

import logging
from functools import lru_cache
from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

logger = logging.getLogger(__name__)

# Keycloak signs access tokens with the realm's RS256 key by default.
ALGORITHMS = ["RS256"]

# `typ` claim of Keycloak access tokens. ID tokens have `ID` and refresh
# tokens `Refresh`, and must not be accepted as access tokens.
ACCESS_TOKEN_TYPE = "Bearer"

# How long the realm's key set is cached. A token signed with an unknown key
# (e.g. after a key rotation) refetches it regardless.
JWKS_CACHE_SECONDS = 300

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="bearerAuth",
    description=(
        "Keycloak access token of the `coevolution` realm, from "
        "`POST /realms/coevolution/protocol/openid-connect/token`."
    ),
)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def issuer() -> str:
    """Return the expected `iss` claim, the URL of the Keycloak realm."""

    return f"{settings.KEYCLOAK_BASE_URL.rstrip('/')}/realms/{settings.KEYCLOAK_REALM}"


@lru_cache
def get_jwks_client() -> jwt.PyJWKClient:
    """Return the cached client that fetches the realm's public keys."""

    return jwt.PyJWKClient(
        f"{issuer()}/protocol/openid-connect/certs",
        cache_jwk_set=True,
        lifespan=JWKS_CACHE_SECONDS,
        timeout=10,
    )


def decode_token(token: str) -> dict[str, Any]:
    """Validate an access token and return its claims.

    Raises:
        HTTPException: 401 if the token is invalid, 503 if the public keys
            could not be fetched from Keycloak.
    """

    try:
        key = get_jwks_client().get_signing_key_from_jwt(token).key
    except jwt.PyJWKClientConnectionError:
        logger.error("Could not fetch the Keycloak public keys", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )
    except jwt.PyJWTError as e:
        logger.warning("Rejected access token: %s", e)
        raise _unauthorized("Invalid access token")

    audience = settings.KEYCLOAK_AUDIENCE
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            issuer=issuer(),
            audience=audience,
            options={
                "require": ["exp", "iat", "iss", "sub"],
                # Without an audience, PyJWT would reject any token that has
                # an `aud` claim, which Keycloak tokens usually have.
                "verify_aud": audience is not None,
            },
        )
    except jwt.PyJWTError as e:
        logger.warning("Rejected access token: %s", e)
        raise _unauthorized("Invalid access token")

    if claims.get("typ") != ACCESS_TOKEN_TYPE:
        logger.warning("Rejected token of type %r", claims.get("typ"))
        raise _unauthorized("Invalid access token")

    return claims


def require_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict[str, Any]:
    """Require a valid Keycloak access token and return its claims.

    Returns an empty dict without checking anything when `AUTH_ENABLED` is
    false.

    This is a sync dependency on purpose: fetching the public keys blocks, so
    FastAPI runs it in its thread pool instead of the event loop.

    Raises:
        HTTPException: 401 if the token is missing or invalid, 503 if
            Keycloak's public keys could not be fetched.
    """

    if not settings.AUTH_ENABLED:
        return {}

    if credentials is None:
        raise _unauthorized("Not authenticated")

    claims = decode_token(credentials.credentials)

    logger.info(
        "Authenticated %s %s: sub=%s, username=%s, client=%s",
        request.method,
        request.url.path,
        claims.get("sub"),
        claims.get("preferred_username"),
        claims.get("azp"),
    )

    return claims
