"""CloudFront origin guard: reject requests that did not come through the CDN.

Pure ASGI so it runs before every other middleware: a rejected request never
consumes a throttle hit, reads the kill switch or touches the session store.
"""

import hmac
import json
import logging

from starlette.types import ASGIApp, Receive, Scope, Send

_log = logging.getLogger("phoebe.api")

HEADER = b"x-phoebe-origin"
HEALTH = "/api/health"
_BODY = json.dumps({"detail": "forbidden"}).encode()


class OriginGuard:
    def __init__(self, app: ASGIApp, secret: str) -> None:
        self.app = app
        self._secret = secret.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == HEALTH:
            await self.app(scope, receive, send)
            return
        given = b""
        for name, value in scope["headers"]:
            if name == HEADER:
                given = value
                break
        if hmac.compare_digest(given, self._secret):
            await self.app(scope, receive, send)
            return
        # Metadata only: the path (no query string) and status, never headers.
        _log.warning("origin guard rejected path=%s status=403", scope["path"][:200])
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_BODY)).encode()),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _BODY})
