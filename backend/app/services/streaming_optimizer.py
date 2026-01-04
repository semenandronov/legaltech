"""Streaming Optimizer - Phase 6.1 Implementation

This module provides optimizations for WebSocket streaming
including token aggregation, compression, and backpressure handling.

Features:
- Token aggregation in time windows
- Gzip compression support
- Backpressure handling
- Cancel support
- Event type standardization
"""
from typing import Optional, Dict, Any, List, AsyncGenerator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import asyncio
import logging
import gzip
import json
import time

logger = logging.getLogger(__name__)


class StreamEventType(str, Enum):
    """Standardized event types for streaming."""
    # Connection events
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    
    # Progress events
    START = "start"
    PROGRESS = "progress"
    STEP_START = "step_start"
    STEP_COMPLETE = "step_complete"
    
    # Token events
    TOKEN = "token"
    TOKENS_BATCH = "tokens_batch"
    
    # Result events
    RESULT = "result"
    PARTIAL_RESULT = "partial_result"
    
    # Error events
    ERROR = "error"
    WARNING = "warning"
    
    # Control events
    CANCEL = "cancel"
    CANCELLED = "cancelled"
    HEARTBEAT = "heartbeat"


@dataclass
class StreamEvent:
    """A single streaming event."""
    
    event_type: StreamEventType
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.event_type.value,
            "data": self.data,
            "timestamp": self.timestamp.isoformat()
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    def to_compressed(self) -> bytes:
        return gzip.compress(self.to_json().encode('utf-8'))


class TokenAggregator:
    """
    Aggregates tokens in time windows for efficient streaming.
    
    Instead of sending each token individually, collects tokens
    and sends in batches.
    """
    
    def __init__(
        self,
        window_ms: int = 100,  # Aggregation window in milliseconds
        max_tokens: int = 50  # Max tokens before forced flush
    ):
        """
        Initialize token aggregator.
        
        Args:
            window_ms: Time window for aggregation (ms)
            max_tokens: Maximum tokens before flush
        """
        self.window_ms = window_ms
        self.max_tokens = max_tokens
        self._buffer: List[str] = []
        self._last_flush = time.time()
        self._lock = asyncio.Lock()
    
    async def add_token(self, token: str) -> Optional[str]:
        """
        Add a token to the buffer.
        
        Args:
            token: Token to add
            
        Returns:
            Aggregated tokens if flush is triggered, None otherwise
        """
        async with self._lock:
            self._buffer.append(token)
            
            current_time = time.time()
            elapsed_ms = (current_time - self._last_flush) * 1000
            
            # Flush if window expired or max tokens reached
            if elapsed_ms >= self.window_ms or len(self._buffer) >= self.max_tokens:
                return await self._flush()
            
            return None
    
    async def flush(self) -> Optional[str]:
        """Force flush the buffer."""
        async with self._lock:
            return await self._flush()
    
    async def _flush(self) -> Optional[str]:
        """Internal flush method (must be called with lock held)."""
        if not self._buffer:
            return None
        
        aggregated = "".join(self._buffer)
        self._buffer.clear()
        self._last_flush = time.time()
        
        return aggregated


class BackpressureHandler:
    """
    Handles backpressure for streaming connections.
    
    Tracks send queue depth and adjusts sending behavior
    to prevent overwhelming slow clients.
    """
    
    def __init__(
        self,
        max_queue_size: int = 100,
        warning_threshold: float = 0.7
    ):
        """
        Initialize backpressure handler.
        
        Args:
            max_queue_size: Maximum queue size before dropping
            warning_threshold: Threshold for warning (0-1)
        """
        self.max_queue_size = max_queue_size
        self.warning_threshold = warning_threshold
        self._queue_size = 0
        self._dropped_count = 0
    
    def can_send(self) -> bool:
        """Check if we can send more messages."""
        return self._queue_size < self.max_queue_size
    
    def should_warn(self) -> bool:
        """Check if we should warn about backpressure."""
        return self._queue_size >= self.max_queue_size * self.warning_threshold
    
    def record_send(self):
        """Record a message being sent."""
        self._queue_size += 1
    
    def record_ack(self):
        """Record a message acknowledgment."""
        self._queue_size = max(0, self._queue_size - 1)
    
    def record_drop(self):
        """Record a dropped message."""
        self._dropped_count += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get backpressure statistics."""
        return {
            "queue_size": self._queue_size,
            "max_queue_size": self.max_queue_size,
            "dropped_count": self._dropped_count,
            "load_factor": self._queue_size / self.max_queue_size
        }


class StreamingOptimizer:
    """
    Main optimizer for WebSocket streaming.
    
    Combines token aggregation, compression, and backpressure
    handling for optimal streaming performance.
    """
    
    def __init__(
        self,
        aggregation_window_ms: int = 100,
        max_aggregated_tokens: int = 50,
        enable_compression: bool = False,
        max_queue_size: int = 100
    ):
        """
        Initialize streaming optimizer.
        
        Args:
            aggregation_window_ms: Token aggregation window
            max_aggregated_tokens: Max tokens per aggregation
            enable_compression: Whether to use gzip
            max_queue_size: Max queue size for backpressure
        """
        self.aggregator = TokenAggregator(
            window_ms=aggregation_window_ms,
            max_tokens=max_aggregated_tokens
        )
        self.backpressure = BackpressureHandler(max_queue_size=max_queue_size)
        self.enable_compression = enable_compression
        self._cancelled = False
    
    def cancel(self):
        """Signal cancellation."""
        self._cancelled = True
    
    def is_cancelled(self) -> bool:
        """Check if cancelled."""
        return self._cancelled
    
    async def process_token(self, token: str) -> Optional[StreamEvent]:
        """
        Process a token through the optimizer.
        
        Args:
            token: Token to process
            
        Returns:
            StreamEvent if ready to send, None otherwise
        """
        if self._cancelled:
            return None
        
        aggregated = await self.aggregator.add_token(token)
        if aggregated:
            return StreamEvent(
                event_type=StreamEventType.TOKENS_BATCH,
                data={"tokens": aggregated}
            )
        return None
    
    async def flush_tokens(self) -> Optional[StreamEvent]:
        """Flush any remaining tokens."""
        aggregated = await self.aggregator.flush()
        if aggregated:
            return StreamEvent(
                event_type=StreamEventType.TOKENS_BATCH,
                data={"tokens": aggregated}
            )
        return None
    
    def create_event(
        self,
        event_type: StreamEventType,
        data: Dict[str, Any]
    ) -> StreamEvent:
        """Create a stream event."""
        return StreamEvent(event_type=event_type, data=data)
    
    def should_send(self) -> bool:
        """Check if we should send (considering backpressure)."""
        return self.backpressure.can_send() and not self._cancelled
    
    def prepare_message(self, event: StreamEvent) -> Any:
        """
        Prepare message for sending.
        
        Args:
            event: Event to prepare
            
        Returns:
            Prepared message (compressed if enabled)
        """
        if self.enable_compression:
            return event.to_compressed()
        return event.to_dict()


async def create_streaming_generator(
    source_generator: AsyncGenerator,
    optimizer: StreamingOptimizer,
    heartbeat_interval: float = 30.0
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Create an optimized streaming generator.
    
    Wraps a source generator with optimization including
    token aggregation and heartbeats.
    
    Args:
        source_generator: Source async generator
        optimizer: Streaming optimizer
        heartbeat_interval: Interval for heartbeats (seconds)
        
    Yields:
        Optimized stream events
    """
    last_heartbeat = time.time()
    
    try:
        async for item in source_generator:
            if optimizer.is_cancelled():
                break
            
            # Check if heartbeat needed
            if time.time() - last_heartbeat > heartbeat_interval:
                yield optimizer.create_event(
                    StreamEventType.HEARTBEAT,
                    {"timestamp": datetime.utcnow().isoformat()}
                ).to_dict()
                last_heartbeat = time.time()
            
            # Process item
            if isinstance(item, str):
                # Token
                event = await optimizer.process_token(item)
                if event and optimizer.should_send():
                    yield optimizer.prepare_message(event)
            elif isinstance(item, dict):
                # Structured event
                event = optimizer.create_event(
                    StreamEventType.PROGRESS,
                    item
                )
                if optimizer.should_send():
                    yield optimizer.prepare_message(event)
        
        # Flush remaining tokens
        final_event = await optimizer.flush_tokens()
        if final_event:
            yield optimizer.prepare_message(final_event)
            
    except asyncio.CancelledError:
        logger.info("Streaming cancelled")
        yield optimizer.create_event(
            StreamEventType.CANCELLED,
            {"reason": "client_cancelled"}
        ).to_dict()


def get_streaming_optimizer(
    aggregation_window_ms: int = 100,
    enable_compression: bool = False
) -> StreamingOptimizer:
    """
    Factory function for streaming optimizer.
    
    Args:
        aggregation_window_ms: Aggregation window
        enable_compression: Enable compression
        
    Returns:
        StreamingOptimizer instance
    """
    return StreamingOptimizer(
        aggregation_window_ms=aggregation_window_ms,
        enable_compression=enable_compression
    )

