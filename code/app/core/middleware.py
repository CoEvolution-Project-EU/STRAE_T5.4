import asyncio
import logging
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP request rate limiter.

    State (`ip_requests`) is kept in this process's memory, so the limit is
    only correct when a single instance of the API is running. Running
    multiple replicas behind a load balancer multiplies the effective limit
    by the replica count, since each instance tracks requests independently.
    """

    def __init__(
        self,
        app,
        rate_limit=10,
        rate_limit_window=60,
        protected_routes=["/api/generate", "/api/reports"],
    ):
        super().__init__(app)
        self.rate_limit = rate_limit
        self.rate_limit_window = rate_limit_window
        self.protected_routes = protected_routes
        self.ip_requests = defaultdict(list)
        self._last_cleanup = time.time()
        logger.info(
            "Rate limit middleware initialized: %d requests / %ds",
            rate_limit,
            rate_limit_window,
        )

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        current_time = time.time()

        # Only apply rate limiting to protected routes
        if any(request.url.path.startswith(route) for route in self.protected_routes):
            # Clean up old requests for this IP
            self.ip_requests[client_ip] = [
                t
                for t in self.ip_requests[client_ip]
                if current_time - t < self.rate_limit_window
            ]

            # Periodic cleanup of stale IPs, at most once per rate-limit window,
            # so the dict doesn't grow unbounded with IPs that stopped sending
            # requests. In a production app with multiple replicas, use a
            # shared store (e.g. Redis) instead.
            if current_time - self._last_cleanup > self.rate_limit_window:
                self._cleanup_all_ips(current_time)
                self._last_cleanup = current_time

            # Check if rate limit exceeded
            if len(self.ip_requests[client_ip]) >= self.rate_limit:
                logger.warning(
                    "Rate limit exceeded client=%s path=%s",
                    client_ip,
                    request.url.path,
                )
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please try again later."},
                )

            # Add current request timestamp
            self.ip_requests[client_ip].append(current_time)

        # Process the request
        response = await call_next(request)
        return response

    def _cleanup_all_ips(self, current_time):
        """Remove IPs that haven't made requests in the window"""

        to_remove = []
        for ip, timestamps in self.ip_requests.items():
            # If latest timestamp is older than window, remove IP
            if not timestamps or (
                current_time - timestamps[-1] > self.rate_limit_window
            ):
                to_remove.append(ip)
        for ip in to_remove:
            del self.ip_requests[ip]


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """Caps total in-flight requests to protected routes via an in-process semaphore.

    The semaphore is local to this process, so the cap is only correct when
    a single instance of the API is running. Running multiple replicas
    behind a load balancer multiplies the effective cap by the replica
    count, since each instance enforces its own independent limit.
    """

    def __init__(
        self,
        app,
        max_concurrent_requests=5,
        timeout=5.0,
        protected_routes=["/api/generate", "/api/reports"],
    ):
        super().__init__(app)
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
        self.timeout = timeout
        self.protected_routes = protected_routes
        logger.info(
            "Concurrency limit middleware initialized: %d concurrent requests",
            max_concurrent_requests,
        )

    async def dispatch(self, request, call_next):
        try:
            # Only apply to protected routes
            if any(
                request.url.path.startswith(route) for route in self.protected_routes
            ):
                try:
                    # Try to acquire the semaphore
                    acquired = False
                    try:
                        # Use wait_for instead of timeout context manager for compatibility
                        await asyncio.wait_for(
                            self.semaphore.acquire(), timeout=self.timeout
                        )
                        acquired = True
                        return await call_next(request)
                    finally:
                        if acquired:
                            self.semaphore.release()
                except asyncio.TimeoutError:
                    # Timeout waiting for semaphore
                    logger.warning(
                        "Concurrency limit reached path=%s",
                        request.url.path,
                    )
                    return JSONResponse(
                        status_code=503,
                        content={
                            "detail": "Server is at capacity. Please try again later."
                        },
                    )
            else:
                # For non-protected routes, proceed normally
                return await call_next(request)
        except Exception as e:
            logger.exception("Error in ConcurrencyLimitMiddleware")
            return JSONResponse(
                status_code=500,
                content={"detail": f"Internal server error in middleware: {str(e)}"},
            )


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_content_length=1024 * 1024):  # 1MB default
        super().__init__(app)
        self.max_content_length = max_content_length
        logger.info(
            "Request size limit middleware initialized: %d bytes",
            max_content_length,
        )

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            if int(content_length) > self.max_content_length:
                logger.warning(
                    "Request too large size=%s max=%d",
                    content_length,
                    self.max_content_length,
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"Request too large. Content must be <= {self.max_content_length} bytes"
                    },
                )
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        logger.info("Logging middleware initialized")

    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled exception %s %s",
                request.method,
                request.url.path,
            )
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000

        logger.info(
            "%s %s | %d | %.2fms | client=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request.client.host if request.client else "-",
        )

        return response
