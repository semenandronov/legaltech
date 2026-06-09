"""Tests for WebSocket manager safe broadcast behavior."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

from app.services.websocket_manager import WebSocketManager, _is_benign_ws_error


def test_is_benign_ws_error_detects_closed_socket_messages():
    assert _is_benign_ws_error(RuntimeError("Cannot call send once a close message has been sent."))
    assert _is_benign_ws_error(RuntimeError("Unexpected ASGI message 'websocket.send', after sending 'websocket.close'."))


@pytest.mark.asyncio
async def test_broadcast_skips_disconnected_sockets_and_cleans_up():
    manager = WebSocketManager()
    review_id = "review-1"

    open_ws = MagicMock()
    open_ws.client_state = WebSocketState.CONNECTED
    open_ws.send_json = AsyncMock()

    closed_ws = MagicMock()
    closed_ws.client_state = WebSocketState.DISCONNECTED
    closed_ws.send_json = AsyncMock()

    manager.active_connections[review_id] = {
        "open": open_ws,
        "closed": closed_ws,
    }
    manager.user_mapping[review_id] = {
        "open": "user-open",
        "closed": "user-closed",
    }

    await manager.broadcast_to_review(review_id, {"type": "cell_updated", "cell_id": "c1"})

    open_ws.send_json.assert_awaited_once()
    closed_ws.send_json.assert_not_awaited()
    assert manager.get_connection_count(review_id) == 1
    assert "closed" not in manager.active_connections[review_id]


@pytest.mark.asyncio
async def test_broadcast_snapshot_does_not_fail_when_peer_removed_midflight():
    manager = WebSocketManager()
    review_id = "review-2"

    ws = MagicMock()
    ws.client_state = WebSocketState.CONNECTED
    ws.send_json = AsyncMock(side_effect=RuntimeError("Unexpected ASGI message after websocket.close"))

    manager.active_connections[review_id] = {"conn-1": ws}
    manager.user_mapping[review_id] = {"conn-1": "user-1"}

    await manager.broadcast_to_review(review_id, {"type": "ping"})

    assert manager.get_connection_count(review_id) == 0


@pytest.mark.asyncio
async def test_connect_registers_under_lock():
    manager = WebSocketManager()
    ws = MagicMock()
    ws.accept = AsyncMock()

    connection_id = await manager.connect(ws, "review-3", "user-3")

    assert connection_id
    assert manager.get_connection_count("review-3") == 1
    ws.accept.assert_awaited_once()
