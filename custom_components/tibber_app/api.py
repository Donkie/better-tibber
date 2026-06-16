"""Async client for the Tibber app GraphQL API.

A small ``aiohttp`` client plus a GraphQL-over-WebSocket helper for the live
subscriptions (Pulse meter and home battery).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from .const import GQL_URL, LOGIN_URL, USER_AGENT, WS_URL

_LOGGER = logging.getLogger(__name__)

# graphql-transport-ws message types
_WS_CONNECTION_INIT = "connection_init"
_WS_CONNECTION_ACK = "connection_ack"
_WS_SUBSCRIBE = "subscribe"
_WS_NEXT = "next"
_WS_ERROR = "error"
_WS_COMPLETE = "complete"
_WS_PING = "ping"
_WS_PONG = "pong"


def _is_auth_error(errors: list[dict[str, Any]]) -> bool:
    """True if a GraphQL error list signals an expired/invalid token."""
    for err in errors:
        if (err.get("extensions") or {}).get("code") == "UNAUTHENTICATED":
            return True
        if "not authenticated" in (err.get("message") or "").lower():
            return True
    return False


def _is_transient_error(errors: list[dict[str, Any]]) -> bool:
    """True if a GraphQL error list signals a transient upstream failure.

    The backend trips its own circuit breaker under load and returns this as a
    GraphQL error (HTTP 200) rather than a 5xx, so it needs the same backoff.
    """
    return any(
        "breaker is open" in (err.get("message") or "").lower() for err in errors
    )


class TibberAuthError(Exception):
    """Raised when login fails or the token is rejected."""


class TibberApiError(Exception):
    """Raised when the API returns a non-recoverable error."""


class TibberAppClient:
    """Minimal authenticated client for app.tibber.com.

    The token is obtained via email/password login and re-fetched automatically
    (a fresh login) when it expires or is rejected.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        token: str | None = None,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = token
        self._login_lock = asyncio.Lock()

    @property
    def token(self) -> str | None:
        """Return the current bearer token, if any."""
        return self._token

    async def login(self) -> str:
        """Authenticate and return a fresh bearer token."""
        async with self._login_lock:
            try:
                async with self._session.post(
                    LOGIN_URL,
                    json={"email": self._email, "password": self._password},
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status in (401, 403):
                        raise TibberAuthError("Invalid email or password")
                    resp.raise_for_status()
                    data = await resp.json()
            except aiohttp.ClientResponseError as err:
                raise TibberAuthError(f"Login failed: {err.status}") from err
            except aiohttp.ClientError as err:
                raise TibberApiError(f"Login request failed: {err}") from err

            token = data.get("token")
            if not token:
                raise TibberAuthError("Login response did not contain a token")
            self._token = token
            return token

    async def async_get_token(self) -> str:
        """Return a cached token, logging in if we don't have one yet."""
        if self._token:
            return self._token
        return await self.login()

    async def gql(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        retries: int = 4,
    ) -> dict[str, Any]:
        """Execute a GraphQL request, returning the parsed ``data`` payload.

        Handles 401 (re-login once), 429 rate limiting (hard backoff) and transient
        5xx errors with exponential backoff.
        """
        body: dict[str, Any] = {"query": query}
        if variables is not None:
            body["variables"] = variables

        token = await self.async_get_token()
        relogged = False

        for attempt in range(retries):
            try:
                async with self._session.post(
                    GQL_URL,
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {token}",
                        "User-Agent": USER_AGENT,
                    },
                ) as resp:
                    if resp.status == 401 and not relogged:
                        relogged = True
                        token = await self.login()
                        continue
                    if resp.status == 429:
                        if attempt < retries - 1:
                            await asyncio.sleep(8 * (attempt + 1))
                            continue
                        raise TibberApiError("HTTP 429 rate limited")
                    if resp.status in (500, 502, 503) and attempt < retries - 1:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    resp.raise_for_status()
                    payload = await resp.json()
            except aiohttp.ClientResponseError as err:
                if err.status == 401:
                    raise TibberAuthError("Token rejected") from err
                raise TibberApiError(f"HTTP {err.status}") from err
            except aiohttp.ClientError as err:
                if attempt < retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                raise TibberApiError(f"Request failed: {err}") from err

            errors = payload.get("errors")
            if errors:
                # Token expiry comes back as HTTP 200 + an UNAUTHENTICATED GraphQL
                # error (not a 401), so it must be handled here: re-login once and
                # retry, then surface as an auth error so HA can trigger reauth.
                if _is_auth_error(errors):
                    if not relogged:
                        relogged = True
                        token = await self.login()
                        continue
                    raise TibberAuthError("Token rejected after re-login")
                if _is_transient_error(errors) and attempt < retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    continue
                msg = "; ".join(e.get("message", "?") for e in errors)
                raise TibberApiError(f"GraphQL error: {msg}")
            return payload.get("data", {})

        raise TibberApiError("max retries exceeded")

    async def subscribe(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        stop: asyncio.Event | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield ``data`` payloads from a GraphQL subscription over WebSocket.

        Uses the graphql-transport-ws protocol with the bearer token sent in the
        ``connection_init`` payload. The caller is responsible for reconnecting if
        the iterator ends (the socket dropped); polling remains the source of truth.
        """
        token = await self.async_get_token()
        async with self._session.ws_connect(
            WS_URL,
            protocols=("graphql-transport-ws",),
            headers={"User-Agent": USER_AGENT},
            heartbeat=30,
        ) as ws:
            await ws.send_json(
                {"type": _WS_CONNECTION_INIT, "payload": {"token": token}}
            )
            await self._await_ack(ws)

            await ws.send_json(
                {
                    "id": "1",
                    "type": _WS_SUBSCRIBE,
                    "payload": {"query": query, "variables": variables or {}},
                }
            )

            async for msg in ws:
                if stop is not None and stop.is_set():
                    await ws.send_json({"id": "1", "type": _WS_COMPLETE})
                    return
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        return
                    continue
                data = msg.json()
                mtype = data.get("type")
                if mtype == _WS_PING:
                    await ws.send_json({"type": _WS_PONG})
                elif mtype == _WS_NEXT:
                    payload = data.get("payload", {})
                    if payload.get("data"):
                        yield payload["data"]
                elif mtype == _WS_ERROR:
                    _LOGGER.warning("Subscription error: %s", data.get("payload"))
                    return
                elif mtype == _WS_COMPLETE:
                    return

    @staticmethod
    async def _await_ack(ws: aiohttp.ClientWebSocketResponse) -> None:
        """Wait for the connection_ack frame after connection_init."""
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            if msg.json().get("type") == _WS_CONNECTION_ACK:
                return
        raise TibberApiError("WebSocket closed before connection_ack")
