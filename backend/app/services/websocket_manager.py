"""WebSocket Manager for managing WebSocket connections"""
from typing import Dict, Set
from fastapi import WebSocket
from starlette.websockets import WebSocketState
import logging
import asyncio
import uuid

logger = logging.getLogger(__name__)


def _is_websocket_connected(websocket: WebSocket) -> bool:
    return websocket.client_state == WebSocketState.CONNECTED


def _is_benign_ws_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if any(
        phrase in msg
        for phrase in (
            "after websocket.close",
            "websocket is not connected",
            "close message has been sent",
            "connection closed",
        )
    ):
        return True
    code = getattr(exc, "code", None)
    if code in ("EPIPE", "ECONNRESET"):
        return True
    return isinstance(exc, RuntimeError) and "websocket" in msg


class WebSocketManager:
    """Manager for WebSocket connections"""

    def __init__(self):
        """Initialize WebSocket manager"""
        # {review_id: {websocket_id: WebSocket}}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        # {review_id: {websocket_id: user_id}}
        self.user_mapping: Dict[str, Dict[str, str]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, review_id: str, user_id: str) -> str:
        """Connect a WebSocket and return connection ID"""
        await websocket.accept()

        connection_id = str(uuid.uuid4())

        async with self._lock:
            if review_id not in self.active_connections:
                self.active_connections[review_id] = {}
                self.user_mapping[review_id] = {}

            self.active_connections[review_id][connection_id] = websocket
            self.user_mapping[review_id][connection_id] = user_id

        logger.info(
            "WebSocket connected: %s for review %s, user %s",
            connection_id,
            review_id,
            user_id,
        )
        return connection_id

    def disconnect(self, review_id: str, connection_id: str) -> None:
        """Disconnect a WebSocket"""
        self._disconnect_unlocked(review_id, connection_id)

    def _disconnect_unlocked(self, review_id: str, connection_id: str) -> None:
        if review_id not in self.active_connections:
            return

        self.active_connections[review_id].pop(connection_id, None)
        self.user_mapping[review_id].pop(connection_id, None)

        if not self.active_connections[review_id]:
            del self.active_connections[review_id]
            del self.user_mapping[review_id]

        logger.info("WebSocket disconnected: %s from review %s", connection_id, review_id)

    async def _safe_send_json(self, websocket: WebSocket, message: dict) -> bool:
        if not _is_websocket_connected(websocket):
            return False
        try:
            await websocket.send_json(message)
            return True
        except Exception as exc:
            if _is_benign_ws_error(exc):
                logger.debug("WebSocket send skipped (connection closed): %s", exc)
            else:
                logger.warning("Error sending WebSocket message: %s", exc)
            return False

    async def send_personal_message(self, message: dict, websocket: WebSocket) -> None:
        """Send a message to a specific WebSocket"""
        await self._safe_send_json(websocket, message)

    async def broadcast_to_review(
        self,
        review_id: str,
        message: dict,
        exclude_connection_id: str = None,
    ) -> None:
        """Broadcast a message to all connections in a review"""
        async with self._lock:
            connections = list(self.active_connections.get(review_id, {}).items())

        if not connections:
            return

        disconnected: list[str] = []
        for connection_id, websocket in connections:
            if connection_id == exclude_connection_id:
                continue

            ok = await self._safe_send_json(websocket, message)
            if not ok:
                disconnected.append(connection_id)

        if disconnected:
            async with self._lock:
                for connection_id in disconnected:
                    self._disconnect_unlocked(review_id, connection_id)

    async def broadcast_presence_update(
        self,
        review_id: str,
        presence_data: dict,
        exclude_connection_id: str = None,
    ) -> None:
        """Broadcast presence update to all connections in a review"""
        message = {
            "type": "presence_update",
            "review_id": review_id,
            **presence_data,
        }
        await self.broadcast_to_review(review_id, message, exclude_connection_id)

    async def broadcast_cell_update(
        self,
        review_id: str,
        cell_data: dict,
        exclude_connection_id: str = None,
    ) -> None:
        """Broadcast cell update to all connections in a review"""
        message = {
            "type": "cell_updated",
            "review_id": review_id,
            **cell_data,
        }
        await self.broadcast_to_review(review_id, message, exclude_connection_id)

    async def broadcast_cell_lock(
        self,
        review_id: str,
        lock_data: dict,
        exclude_connection_id: str = None,
    ) -> None:
        """Broadcast cell lock update to all connections in a review"""
        message = {
            "type": "cell_locked",
            "review_id": review_id,
            **lock_data,
        }
        await self.broadcast_to_review(review_id, message, exclude_connection_id)

    def get_connected_user_ids(self, review_id: str) -> Set[str]:
        """Get set of user IDs currently connected to a review"""
        if review_id not in self.user_mapping:
            return set()
        return set(self.user_mapping[review_id].values())

    def get_connection_count(self, review_id: str) -> int:
        """Get number of active connections for a review"""
        if review_id not in self.active_connections:
            return 0
        return len(self.active_connections[review_id])


# Global WebSocket manager instance
websocket_manager = WebSocketManager()
