"""HTTP bearer token auth (v4 §11.2 items 2–3; implemented ahead of acceptance per Mac-side plan).

Rules (§11.2 items 2–3, including narrowed semantics for item 2):
- Token auto-created on first start: `secrets.token_urlsafe(32)`, stored in user config `token`;
  chmod 600 on POSIX (best effort on Windows);
- Request check: `Authorization: Bearer <token>`, hmac.compare_digest constant-time compare;
- Token never in logs, URLs, or response bodies—clients read the token file locally;
- `--allow-insecure` only with loopback bind (non-loopback + flag = refuse start); non-loopback
  starts with auth by default;
- /health tiers (item 3: detailed health needs token): valid Bearer → detail (window list);
  missing/invalid → coarse; /health never 401 (monitors must not fail on missing token);
  401 only on MCP endpoints.

Middleware is pure ASGI: no response wrapping, no BaseHTTPMiddleware—streamable HTTP
and SSE pass through without buffering risk.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
from pathlib import Path
from typing import Any

from starlette.responses import JSONResponse

TOKEN_FILENAME = "token"

_UNAUTHENTICATED_BODY = {
    "ok": False,
    "error": {
        "code": "UNAUTHENTICATED",
        "message": "Missing or invalid Authorization: Bearer token",
        "hint": "Send Authorization: Bearer <token>; token file is in the server user config dir "
        "(server never echoes token, v4 §11.2 item 3)",
    },
}


def load_or_create_token(path: Path) -> str:
    """Read or create token file (§11.2 item 3); POSIX mode 0600 after create.

    Empty file is treated as missing (regenerate). OSError propagates—caller sets strictness:
    cli refuses start without token by default; --allow-insecure downgrades to warning.
    """
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows has no POSIX mode; token still lives in user config dir
    return token


def bearer_matches(header_value: str | None, token: str | None) -> bool:
    """Compare Authorization header to token; missing/malformed/empty → False (no throw)."""
    if not header_value or not token:
        return False
    scheme, _, credential = header_value.partition(" ")
    if scheme.lower() != "bearer" or not credential:
        return False
    return hmac.compare_digest(credential.encode("utf-8"), token.encode("utf-8"))


class BearerAuthMiddleware:
    """Guard non-/health paths: no valid Bearer → 401 (WWW-Authenticate: Bearer, no token echo)."""

    def __init__(self, app: Any, token: str | None = None) -> None:
        self.app = app
        self._token = token

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        if bearer_matches(headers.get("authorization"), self._token):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            _UNAUTHENTICATED_BODY,
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


def unauthenticated_body_json() -> str:
    """Test helper for 401 body: structure without echoing token."""
    return json.dumps(_UNAUTHENTICATED_BODY, ensure_ascii=False)
