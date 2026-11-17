"""HTTP-level protections: request size limit and security headers.

Both are plain ASGI middleware so they run before FastAPI parses a
multipart body — a size check inside the endpoint would come too late,
because the whole upload is already spooled by then.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from app.i18n import available as available_langs, default_lang, get_lang

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# Per uploaded file. A 5,000-line CSV is about 300 KB; Vercel caps a whole
# request at 4.5 MB anyway.
MAX_UPLOAD_BYTES = 1 * 1024 * 1024
# Three files plus form fields and multipart framing.
MAX_REQUEST_BYTES = 3 * MAX_UPLOAD_BYTES + 64 * 1024

CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'none'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "connect-src 'self'",
    "form-action 'self'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
))

_STATIC_HEADERS = (
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
)


def _header(scope: Scope, name: bytes) -> str:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


def is_https(request_or_scope: Any) -> bool:
    """True when the client reached us over HTTPS, also behind a proxy such
    as Vercel's that terminates TLS and forwards plain HTTP."""
    scope = getattr(request_or_scope, "scope", request_or_scope)
    if scope.get("scheme") == "https":
        return True
    forwarded = _header(scope, b"x-forwarded-proto").split(",")[0].strip().lower()
    return forwarded == "https"


class SecurityHeadersMiddleware:
    """Adds security headers to every response. Match results contain
    supplier and pricing data, so POST responses are never cached."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        https = is_https(scope)
        no_store = scope.get("method") == "POST"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", [])
                           if h[0].lower() not in {k for k, _ in _STATIC_HEADERS}]
                headers.extend(_STATIC_HEADERS)
                if https:
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                if no_store:
                    headers = [h for h in headers if h[0].lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Rejects request bodies above MAX_REQUEST_BYTES with 413, both when
    Content-Length announces it and when a chunked body grows past it."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = _header(scope, b"content-length")
        if declared:
            try:
                too_large = int(declared) > self.max_bytes
            except ValueError:
                too_large = True
            if too_large:
                await self._reject(scope, send)
                return

        received = 0
        exceeded = False
        started = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    raise _TooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                # The framework may turn the aborted body into its own error
                # response (FastAPI answers 400); answer 413 instead.
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await self._reject(scope, send)
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            pass
        if exceeded and not started:
            await self._reject(scope, send)

    @staticmethod
    async def _reject(scope: Scope, send: Send) -> None:
        cookie_lang = ""
        for part in _header(scope, b"cookie").split(";"):
            key, _, value = part.strip().partition("=")
            if key == "lang":
                cookie_lang = value.strip().lower()
        lang = cookie_lang if cookie_lang in available_langs() else default_lang()
        text = get_lang(lang)["ui"]["error_request_too_large"].format(
            max_mb=f"{MAX_UPLOAD_BYTES / 1024 / 1024:g}")
        if scope.get("path", "").startswith("/api/"):
            body, ctype = json.dumps({"error": text}).encode(), b"application/json"
        else:
            body, ctype = text.encode(), b"text/plain; charset=utf-8"
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", ctype),
                                (b"content-length", str(len(body)).encode()),
                                (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})
