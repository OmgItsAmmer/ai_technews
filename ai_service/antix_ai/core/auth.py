"""Service-to-service authentication."""

from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request, status


async def require_service_key(
    request: Request,
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
) -> None:
    expected = request.app.state.ctx.settings.service_key.get_secret_value()
    if not x_service_key or not hmac.compare_digest(x_service_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid service key")
