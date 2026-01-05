"""WebSocket Manager for managing WebSocket connections"""
from typing import Dict, Set, List
from fastapi import WebSocket
import logging
import asyncio

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manager for WebSocket connections"""
    
    def __init__(self):
        """Initialize WebSocket manager"""
        # {review_id: {websocket_id: WebSocket}}
        self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
        # {review_id: {websocket_id: user_id}}
        self.user_mapping: Dict[str, Dict[str, str]] = {}
    
    async def connect(self, websocket: WebSocket, review_id: str, user_id: str) -> str:
        """Connect a WebSocket and return connection ID"""
        await websocket.accept()
        
        # Generate connection ID
        import uuid
        connection_id = str(uuid.uuid4())
        
        if review_id not in self.active_connections:
            self.active_connections[review_id] = {}
            self.user_mapping[review_id] = {}
        
        self.active_connections[review_id][connection_id] = websocket
        self.user_mapping[review_id][connection_id] = user_id
        
        logger.info(f"WebSocket connected: {connection_id} for review {review_id}, user {user_id}")
        return connection_id
    
    def disconnect(self, review_id: str, connection_id: str) -> None:
        """Disconnect a WebSocket"""
        if review_id in self.active_connections:
            self.active_connections[review_id].pop(connection_id, None)
            self.user_mapping[review_id].pop(connection_id, None)
            
            # Clean up empty reviews
            if not self.active_connections[review_id]:
                del self.active_connections[review_id]
                del self.user_mapping[review_id]
        
        logger.info(f"WebSocket disconnected: {connection_id} from review {review_id}")
    
    async def send_personal_message(self, message: dict, websocket: WebSocket) -> None:
        """Send a message to a specific WebSocket"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}", exc_info=True)
    
    async def broadcast_to_review(self, review_id: str, message: dict, exclude_connection_id: str = None) -> None:
        """Broadcast a message to all connections in a review"""
        if review_id not in self.active_connections:
            return
        
        disconnected = []
        for connection_id, websocket in self.active_connections[review_id].items():
            if connection_id == exclude_connection_id:
                continue
            
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Error broadcasting to connection {connection_id}: {e}")
                disconnected.append(connection_id)
        
        # Clean up disconnected connections
        for connection_id in disconnected:
            self.disconnect(review_id, connection_id)
    
    async def broadcast_presence_update(self, review_id: str, presence_data: dict, exclude_connection_id: str = None) -> None:
        """Broadcast presence update to all connections in a review"""
        message = {
            "type": "presence_update",
            "review_id": review_id,
            **presence_data
        }
        await self.broadcast_to_review(review_id, message, exclude_connection_id)
    
    async def broadcast_cell_update(self, review_id: str, cell_data: dict, exclude_connection_id: str = None) -> None:
        """Broadcast cell update to all connections in a review"""
        message = {
            "type": "cell_updated",
            "review_id": review_id,
            **cell_data
        }
        await self.broadcast_to_review(review_id, message, exclude_connection_id)
    
    async def broadcast_cell_lock(self, review_id: str, lock_data: dict, exclude_connection_id: str = None) -> None:
        """Broadcast cell lock update to all connections in a review"""
        message = {
            "type": "cell_locked",
            "review_id": review_id,
            **lock_data
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

