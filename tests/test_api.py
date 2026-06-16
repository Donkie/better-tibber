"""Tests for TibberAppClient (api.py).

Covers the login flow, gql() retry/error paths, GraphQL auth error handling, and
WebSocket subscribe() protocol handling — the paths most likely to break on a
Tibber API change.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.tibber_app.api import (
    TibberApiError,
    TibberAppClient,
    TibberAuthError,
    _is_auth_error,
    _is_transient_error,
)
from custom_components.tibber_app.const import GQL_URL, LOGIN_URL

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_SLEEP = "custom_components.tibber_app.api.asyncio.sleep"


def _client(
    token: str | None = "tok",
) -> tuple[TibberAppClient, aiohttp.ClientSession]:
    session = MagicMock(spec=aiohttp.ClientSession)
    return TibberAppClient(session, "u@test.com", "pass", token=token), session


# ---------------------------------------------------------------------------
# _is_auth_error (pure unit tests, no I/O)
# ---------------------------------------------------------------------------


class TestIsAuthError:
    def test_unauthenticated_extension_code(self):
        assert _is_auth_error(
            [{"extensions": {"code": "UNAUTHENTICATED"}, "message": "foo"}]
        )

    def test_not_authenticated_message(self):
        assert _is_auth_error([{"message": "User is not authenticated"}])

    def test_not_authenticated_case_insensitive(self):
        assert _is_auth_error([{"message": "NOT AUTHENTICATED"}])

    def test_unrelated_error_returns_false(self):
        assert not _is_auth_error([{"message": "Field not found"}])

    def test_empty_list_returns_false(self):
        assert not _is_auth_error([])

    def test_first_error_auth_among_multiple(self):
        errors = [
            {"extensions": {"code": "UNAUTHENTICATED"}, "message": "x"},
            {"message": "something else"},
        ]
        assert _is_auth_error(errors)

    def test_missing_extensions_does_not_raise(self):
        assert not _is_auth_error([{"message": "ok"}])


class TestIsTransientError:
    def test_breaker_is_open(self):
        assert _is_transient_error([{"message": "Breaker is open"}])

    def test_case_insensitive(self):
        assert _is_transient_error([{"message": "BREAKER IS OPEN"}])

    def test_unrelated_error_returns_false(self):
        assert not _is_transient_error([{"message": "Field not found"}])

    def test_empty_list_returns_false(self):
        assert not _is_transient_error([])


# ---------------------------------------------------------------------------
# login()
# ---------------------------------------------------------------------------


class TestLogin:
    async def test_success_stores_and_returns_token(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass")
            with aioresponses() as m:
                m.post(LOGIN_URL, payload={"token": "fresh_tok"})
                token = await client.login()

        assert token == "fresh_tok"
        assert client.token == "fresh_tok"

    async def test_401_raises_auth_error(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "wrong")
            with aioresponses() as m:
                m.post(LOGIN_URL, status=401)
                with pytest.raises(TibberAuthError):
                    await client.login()

    async def test_403_raises_auth_error(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "wrong")
            with aioresponses() as m:
                m.post(LOGIN_URL, status=403)
                with pytest.raises(TibberAuthError):
                    await client.login()

    async def test_missing_token_in_response_raises_auth_error(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass")
            with aioresponses() as m:
                m.post(LOGIN_URL, payload={"token": None})
                with pytest.raises(TibberAuthError, match="token"):
                    await client.login()

    async def test_network_error_raises_api_error(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass")
            with aioresponses() as m:
                m.post(LOGIN_URL, exception=aiohttp.ClientConnectionError("down"))
                with pytest.raises(TibberApiError):
                    await client.login()


# ---------------------------------------------------------------------------
# gql() — happy path
# ---------------------------------------------------------------------------


class TestGqlSuccess:
    async def test_returns_data_payload(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="tok")
            with aioresponses() as m:
                m.post(GQL_URL, payload={"data": {"me": {"id": "abc"}}})
                result = await client.gql("{ me { id } }")

        assert result == {"me": {"id": "abc"}}

    async def test_sends_bearer_token(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="mytoken")
            with aioresponses() as m:
                m.post(GQL_URL, payload={"data": {}})
                await client.gql("{ me { id } }")
                request = list(m.requests.values())[0][0]

        assert request.kwargs["headers"]["Authorization"] == "Bearer mytoken"

    async def test_sends_variables(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="tok")
            with aioresponses() as m:
                m.post(GQL_URL, payload={"data": {}})
                await client.gql("query($id: ID!) { home(id: $id) }", {"id": "h1"})
                request = list(m.requests.values())[0][0]

        body = request.kwargs["json"]
        assert body["variables"] == {"id": "h1"}


# ---------------------------------------------------------------------------
# gql() — HTTP error handling
# ---------------------------------------------------------------------------


class TestGqlHttpErrors:
    async def test_http_401_relogins_once_and_succeeds(self):
        """A 401 triggers one silent re-login; next request succeeds."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="old")
            with aioresponses() as m:
                m.post(GQL_URL, status=401)
                m.post(LOGIN_URL, payload={"token": "new_tok"})
                m.post(GQL_URL, payload={"data": {"ok": True}})
                result = await client.gql("{ ok }")

        assert result == {"ok": True}
        assert client.token == "new_tok"

    async def test_http_401_second_time_raises_auth_error(self):
        """If re-login produces a token that also 401s, raise TibberAuthError."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="old")
            with aioresponses() as m:
                m.post(GQL_URL, status=401)
                m.post(LOGIN_URL, payload={"token": "new_tok"})
                m.post(GQL_URL, status=401)
                with pytest.raises(TibberAuthError):
                    await client.gql("{ ok }")

    async def test_http_429_retries_then_raises(self):
        """429 is retried up to (retries - 1) times, then raises TibberApiError."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="tok")
            with (
                patch(_SLEEP, new=AsyncMock()),
                aioresponses() as m,
            ):
                # Four 429s to exhaust retries=4
                for _ in range(4):
                    m.post(GQL_URL, status=429)
                with pytest.raises(TibberApiError, match="429"):
                    await client.gql("{ ok }")

    async def test_http_429_retries_then_succeeds(self):
        """429 is retried; if a later attempt succeeds, data is returned."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="tok")
            with (
                patch(_SLEEP, new=AsyncMock()),
                aioresponses() as m,
            ):
                m.post(GQL_URL, status=429)
                m.post(GQL_URL, payload={"data": {"ok": True}})
                result = await client.gql("{ ok }")

        assert result == {"ok": True}

    async def test_http_503_retries_then_succeeds(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="tok")
            with (
                patch(_SLEEP, new=AsyncMock()),
                aioresponses() as m,
            ):
                m.post(GQL_URL, status=503)
                m.post(GQL_URL, payload={"data": {"ok": True}})
                result = await client.gql("{ ok }")

        assert result == {"ok": True}

    async def test_network_error_retries_then_raises(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="tok")
            with (
                patch(_SLEEP, new=AsyncMock()),
                aioresponses() as m,
            ):
                for _ in range(4):
                    m.post(
                        GQL_URL,
                        exception=aiohttp.ClientConnectionError("down"),
                    )
                with pytest.raises(TibberApiError, match="Request failed"):
                    await client.gql("{ ok }")


# ---------------------------------------------------------------------------
# gql() — GraphQL-level errors (HTTP 200 + errors array)
# ---------------------------------------------------------------------------


class TestGqlGraphQLErrors:
    async def test_unauthenticated_code_relogins_once(self):
        """UNAUTHENTICATED in GraphQL errors triggers one re-login + retry."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="expired")
            with aioresponses() as m:
                m.post(
                    GQL_URL,
                    payload={
                        "errors": [
                            {"extensions": {"code": "UNAUTHENTICATED"}, "message": "x"}
                        ]
                    },
                )
                m.post(LOGIN_URL, payload={"token": "fresh"})
                m.post(GQL_URL, payload={"data": {"ok": True}})
                result = await client.gql("{ ok }")

        assert result == {"ok": True}
        assert client.token == "fresh"

    async def test_unauthenticated_after_relogin_raises_auth_error(self):
        """Two UNAUTHENTICATED responses in a row raise TibberAuthError."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="expired")
            with aioresponses() as m:
                m.post(
                    GQL_URL,
                    payload={
                        "errors": [
                            {"extensions": {"code": "UNAUTHENTICATED"}, "message": "x"}
                        ]
                    },
                )
                m.post(LOGIN_URL, payload={"token": "fresh"})
                m.post(
                    GQL_URL,
                    payload={
                        "errors": [
                            {"extensions": {"code": "UNAUTHENTICATED"}, "message": "x"}
                        ]
                    },
                )
                with pytest.raises(TibberAuthError, match="re-login"):
                    await client.gql("{ ok }")

    async def test_not_authenticated_message_triggers_relogin(self):
        """'not authenticated' message text also triggers the re-login path."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="expired")
            with aioresponses() as m:
                m.post(
                    GQL_URL,
                    payload={"errors": [{"message": "User is not authenticated"}]},
                )
                m.post(LOGIN_URL, payload={"token": "fresh"})
                m.post(GQL_URL, payload={"data": {"ok": True}})
                result = await client.gql("{ ok }")

        assert result == {"ok": True}

    async def test_breaker_open_retries_then_succeeds(self):
        """A 'Breaker is open' GraphQL error is retried with backoff."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="tok")
            with (
                patch(_SLEEP, new=AsyncMock()),
                aioresponses() as m,
            ):
                m.post(
                    GQL_URL,
                    payload={"errors": [{"message": "Breaker is open"}]},
                )
                m.post(GQL_URL, payload={"data": {"ok": True}})
                result = await client.gql("{ ok }")

        assert result == {"ok": True}

    async def test_breaker_open_retries_then_raises(self):
        """'Breaker is open' is retried up to (retries - 1) times, then raises."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="tok")
            with (
                patch(_SLEEP, new=AsyncMock()),
                aioresponses() as m,
            ):
                for _ in range(4):
                    m.post(
                        GQL_URL,
                        payload={"errors": [{"message": "Breaker is open"}]},
                    )
                with pytest.raises(TibberApiError, match="Breaker is open"):
                    await client.gql("{ ok }")

    async def test_non_auth_graphql_error_raises_api_error(self):
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token="tok")
            with aioresponses() as m:
                m.post(
                    GQL_URL,
                    payload={"errors": [{"message": "Field 'foo' not found"}]},
                )
                with pytest.raises(TibberApiError, match="foo"):
                    await client.gql("{ foo }")

    async def test_no_token_triggers_login_before_request(self):
        """If no token is cached, login is called before the first GQL request."""
        async with aiohttp.ClientSession() as session:
            client = TibberAppClient(session, "u@test.com", "pass", token=None)
            with aioresponses() as m:
                m.post(LOGIN_URL, payload={"token": "first_tok"})
                m.post(GQL_URL, payload={"data": {"ok": True}})
                result = await client.gql("{ ok }")

        assert result == {"ok": True}
        assert client.token == "first_tok"


# ---------------------------------------------------------------------------
# subscribe() — WebSocket protocol
# ---------------------------------------------------------------------------


def _ws_text(data: dict) -> MagicMock:
    """Fake aiohttp WSMessage of type TEXT."""
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.TEXT
    msg.json.return_value = data
    return msg


def _ws_close() -> MagicMock:
    msg = MagicMock()
    msg.type = aiohttp.WSMsgType.CLOSED
    return msg


class _FakeWS:
    """Minimal fake aiohttp ClientWebSocketResponse for subscribe() tests."""

    def __init__(self, messages: list[MagicMock]) -> None:
        self._messages = messages
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TestSubscribe:
    def _make_ws(self, *body_messages: MagicMock) -> _FakeWS:
        """Build a fake WS that sends an ACK then the given body messages."""
        ack = _ws_text({"type": "connection_ack"})
        return _FakeWS([ack, *body_messages])

    def _patched_client(self, ws: _FakeWS) -> TibberAppClient:
        client = TibberAppClient.__new__(TibberAppClient)
        client._email = "u@test.com"
        client._password = "pass"
        client._token = "tok"
        client._login_lock = asyncio.Lock()
        session = MagicMock()
        session.ws_connect = MagicMock(return_value=ws)
        client._session = session
        return client

    async def test_yields_next_payloads(self):
        ws = self._make_ws(
            _ws_text({"type": "next", "payload": {"data": {"power": 100}}}),
            _ws_text({"type": "next", "payload": {"data": {"power": 200}}}),
            _ws_close(),
        )
        client = self._patched_client(ws)

        results = []
        async for data in client.subscribe("subscription { liveMeasurement }"):
            results.append(data)

        assert results == [{"power": 100}, {"power": 200}]

    async def test_ping_receives_pong(self):
        ws = self._make_ws(
            _ws_text({"type": "ping"}),
            _ws_close(),
        )
        client = self._patched_client(ws)

        async for _ in client.subscribe("subscription { liveMeasurement }"):
            pass

        pong_sent = any(m.get("type") == "pong" for m in ws.sent)
        assert pong_sent

    async def test_complete_stops_iteration(self):
        ws = self._make_ws(
            _ws_text({"type": "next", "payload": {"data": {"power": 1}}}),
            _ws_text({"type": "complete"}),
            # this would be yielded if complete didn't stop iteration
            _ws_text({"type": "next", "payload": {"data": {"power": 999}}}),
        )
        client = self._patched_client(ws)

        results = []
        async for data in client.subscribe("subscription { liveMeasurement }"):
            results.append(data)

        assert len(results) == 1
        assert results[0]["power"] == 1

    async def test_error_stops_iteration(self):
        ws = self._make_ws(
            _ws_text({"type": "error", "payload": [{"message": "bad"}]}),
            _ws_text({"type": "next", "payload": {"data": {"power": 1}}}),
        )
        client = self._patched_client(ws)

        results = []
        async for data in client.subscribe("subscription { liveMeasurement }"):
            results.append(data)

        assert results == []

    async def test_stop_event_sends_complete(self):
        stop = asyncio.Event()

        async def _gen():
            async for data in client.subscribe(
                "subscription { liveMeasurement }", stop=stop
            ):
                yield data
                stop.set()

        ws = self._make_ws(
            _ws_text({"type": "next", "payload": {"data": {"power": 42}}}),
            _ws_text({"type": "next", "payload": {"data": {"power": 99}}}),
        )
        client = self._patched_client(ws)

        results = [d async for d in _gen()]

        assert results == [{"power": 42}]
        complete_sent = any(
            m.get("type") == "complete" and m.get("id") == "1" for m in ws.sent
        )
        assert complete_sent

    async def test_connection_init_sends_token(self):
        ws = self._make_ws(_ws_close())
        client = self._patched_client(ws)

        async for _ in client.subscribe("subscription { liveMeasurement }"):
            pass

        init = ws.sent[0]
        assert init["type"] == "connection_init"
        assert init["payload"]["token"] == "tok"

    async def test_closed_frame_stops_iteration(self):
        ws = self._make_ws(_ws_close())
        client = self._patched_client(ws)

        results = []
        async for data in client.subscribe("subscription { liveMeasurement }"):
            results.append(data)

        assert results == []
