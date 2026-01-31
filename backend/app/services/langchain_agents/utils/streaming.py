"""
Утилиты для streaming в LangGraph.

Поддерживаемые режимы streaming:
- "values": Полное состояние после каждого узла
- "updates": Только изменения состояния (дельты)
- "messages": Только сообщения (для API mode)
- "tokens": Streaming токенов через astream_events (для real-time UX)

Примеры использования:
```python
from app.services.langchain_agents.utils.streaming import (
    StreamMode,
    stream_graph_with_mode,
    stream_tokens,
)

# Streaming с разными режимами
async for event in stream_graph_with_mode(graph, state, config, mode=StreamMode.UPDATES):
    yield format_sse_event(event)

# Streaming токенов
async for token in stream_tokens(graph, state, config):
    yield format_sse_event({"type": "token", "content": token})
```
"""
from typing import (
    AsyncGenerator, 
    Dict, 
    Any, 
    List, 
    Optional, 
    Union,
    Literal,
)
from enum import Enum
from langchain_core.messages import BaseMessage, AIMessage
from dataclasses import dataclass
import logging
import json

logger = logging.getLogger(__name__)


class StreamMode(str, Enum):
    """Режимы streaming."""
    VALUES = "values"       # Полное состояние
    UPDATES = "updates"     # Только изменения
    MESSAGES = "messages"   # Только сообщения
    DEBUG = "debug"         # Подробный вывод для отладки


@dataclass
class StreamEvent:
    """Событие streaming."""
    type: str
    node: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    token: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь."""
        result = {"type": self.type}
        if self.node:
            result["node"] = self.node
        if self.data:
            result["data"] = self.data
        if self.message:
            result["message"] = self.message
        if self.token:
            result["token"] = self.token
        return result
    
    def to_sse(self) -> str:
        """Преобразовать в SSE формат."""
        return f"data: {json.dumps(self.to_dict())}\n\n"


async def stream_graph_with_mode(
    graph,
    initial_state: Dict[str, Any],
    config: Dict[str, Any],
    mode: StreamMode = StreamMode.UPDATES
) -> AsyncGenerator[StreamEvent, None]:
    """
    Streaming графа с указанным режимом.
    
    Args:
        graph: Скомпилированный LangGraph
        initial_state: Начальное состояние
        config: Конфигурация (thread_id, etc.)
        mode: Режим streaming
    
    Yields:
        StreamEvent объекты
    """
    logger.info(f"[Streaming] Starting stream with mode: {mode}")
    
    # Определяем stream_mode для LangGraph
    langgraph_mode = "updates" if mode in [StreamMode.UPDATES, StreamMode.MESSAGES] else "values"
    
    try:
        async for chunk in graph.astream(initial_state, config=config, stream_mode=langgraph_mode):
            if not isinstance(chunk, dict):
                continue
            
            for node_name, node_data in chunk.items():
                if not isinstance(node_data, dict):
                    continue
                
                if mode == StreamMode.VALUES:
                    # Отправляем полное состояние узла
                    yield StreamEvent(
                        type="state",
                        node=node_name,
                        data=_serialize_state(node_data)
                    )
                
                elif mode == StreamMode.UPDATES:
                    # Отправляем только значимые изменения
                    for event in _extract_updates(node_name, node_data):
                        yield event
                
                elif mode == StreamMode.MESSAGES:
                    # Отправляем только сообщения
                    messages = node_data.get("messages", [])
                    for msg in messages:
                        if isinstance(msg, BaseMessage) and msg.content:
                            yield StreamEvent(
                                type="message",
                                node=node_name,
                                message=msg.content
                            )
                
                elif mode == StreamMode.DEBUG:
                    # Подробный вывод для отладки
                    yield StreamEvent(
                        type="debug",
                        node=node_name,
                        data={
                            "keys": list(node_data.keys()),
                            "state": _serialize_state(node_data)
                        }
                    )
        
        yield StreamEvent(type="complete")
        
    except Exception as e:
        logger.error(f"[Streaming] Error: {e}", exc_info=True)
        yield StreamEvent(type="error", data={"error": str(e)})


async def stream_tokens(
    graph,
    initial_state: Dict[str, Any],
    config: Dict[str, Any],
    include_events: List[str] = None
) -> AsyncGenerator[StreamEvent, None]:
    """
    Streaming токенов через astream_events.
    
    Используется для real-time UX, когда нужно показывать
    токены по мере их генерации LLM.
    
    Фильтрует события:
    - on_llm_stream: токены по мере генерации
    - on_llm_end: завершение генерации
    
    Args:
        graph: Скомпилированный LangGraph
        initial_state: Начальное состояние
        config: Конфигурация
        include_events: Список событий для включения (по умолчанию только токены)
    
    Yields:
        StreamEvent объекты с токенами
    """
    if include_events is None:
        include_events = ["on_llm_stream", "on_llm_end"]
    
    logger.info("[Streaming] Starting token stream via astream_events")
    
    try:
        # Используем astream_events с фильтрацией для токенов
        async for event in graph.astream_events(
            initial_state, 
            config=config, 
            version="v2",
            include_names=["generate_response"]  # Только события из узла генерации ответа
        ):
            event_type = event.get("event")
            
            # Обрабатываем streaming токенов от LLM
            if event_type == "on_llm_stream":
                # Извлекаем токен из события
                chunk = event.get("data", {}).get("chunk")
                if chunk:
                    # chunk может быть AIMessageChunk или просто строка
                    if hasattr(chunk, "content"):
                        content = chunk.content
                    elif isinstance(chunk, str):
                        content = chunk
                    else:
                        content = str(chunk)
                    
                    if content:
                        yield StreamEvent(type="token", token=content)
            
            # Обрабатываем завершение генерации
            elif event_type == "on_llm_end":
                # LLM завершил генерацию
                yield StreamEvent(type="llm_end", data={"event": "generation_complete"})
            
            # Дополнительные события если запрошены
            elif event_type == "on_chat_model_stream" and "on_chat_model_stream" in include_events:
                # Альтернативное событие для streaming (для совместимости)
                chunk = event.get("data", {}).get("chunk")
                if chunk:
                    content = getattr(chunk, "content", None) or str(chunk)
                    if content:
                        yield StreamEvent(type="token", token=content)
            
            elif event_type == "on_chain_start" and "on_chain_start" in include_events:
                name = event.get("name", "unknown")
                yield StreamEvent(type="chain_start", data={"name": name})
            
            elif event_type == "on_chain_end" and "on_chain_end" in include_events:
                name = event.get("name", "unknown")
                yield StreamEvent(type="chain_end", data={"name": name})
            
            elif event_type == "on_tool_start" and "on_tool_start" in include_events:
                name = event.get("name", "unknown")
                yield StreamEvent(type="tool_start", data={"name": name})
            
            elif event_type == "on_tool_end" and "on_tool_end" in include_events:
                name = event.get("name", "unknown")
                output = event.get("data", {}).get("output")
                yield StreamEvent(type="tool_end", data={"name": name, "output": str(output)[:500]})
        
        yield StreamEvent(type="complete")
        
    except Exception as e:
        logger.error(f"[Streaming] Token stream error: {e}", exc_info=True)
        yield StreamEvent(type="error", data={"error": str(e)})


async def stream_with_progress(
    graph,
    initial_state: Dict[str, Any],
    config: Dict[str, Any],
    progress_keys: List[str] = None
) -> AsyncGenerator[StreamEvent, None]:
    """
    Streaming с отслеживанием прогресса.
    
    Отправляет события прогресса на основе указанных ключей состояния.
    
    Args:
        graph: Скомпилированный LangGraph
        initial_state: Начальное состояние
        config: Конфигурация
        progress_keys: Ключи состояния для отслеживания прогресса
    
    Yields:
        StreamEvent объекты
    """
    if progress_keys is None:
        progress_keys = ["current_phase", "current_level", "step_results"]
    
    logger.info("[Streaming] Starting progress stream")
    
    nodes_visited = []
    
    try:
        async for chunk in graph.astream(initial_state, config=config, stream_mode="updates"):
            if not isinstance(chunk, dict):
                continue
            
            for node_name, node_data in chunk.items():
                if not isinstance(node_data, dict):
                    continue
                
                nodes_visited.append(node_name)
                
                # Отправляем событие узла
                yield StreamEvent(
                    type="node",
                    node=node_name,
                    data={"visited": len(nodes_visited)}
                )
                
                # Проверяем ключи прогресса
                for key in progress_keys:
                    value = node_data.get(key)
                    if value is not None:
                        yield StreamEvent(
                            type="progress",
                            node=node_name,
                            data={key: _serialize_value(value)}
                        )
                
                # Отправляем сообщения
                messages = node_data.get("messages", [])
                for msg in messages:
                    if isinstance(msg, BaseMessage) and msg.content:
                        yield StreamEvent(
                            type="message",
                            node=node_name,
                            message=msg.content
                        )
        
        yield StreamEvent(
            type="complete",
            data={"nodes_visited": nodes_visited}
        )
        
    except Exception as e:
        logger.error(f"[Streaming] Progress stream error: {e}", exc_info=True)
        yield StreamEvent(type="error", data={"error": str(e)})


def _extract_updates(node_name: str, node_data: Dict[str, Any]) -> List[StreamEvent]:
    """Извлечь значимые обновления из данных узла."""
    events = []
    
    # Фаза/статус
    phase = node_data.get("current_phase")
    if phase:
        events.append(StreamEvent(type="phase", node=node_name, data={"phase": phase}))
    
    # Сообщения
    messages = node_data.get("messages", [])
    for msg in messages:
        if isinstance(msg, BaseMessage) and msg.content:
            events.append(StreamEvent(type="message", node=node_name, message=msg.content))
    
    # Ответ (финальный)
    response = node_data.get("response")
    if response:
        events.append(StreamEvent(type="response", node=node_name, message=response))
    
    # Цитаты
    citations = node_data.get("citations")
    if citations:
        events.append(StreamEvent(type="citations", node=node_name, data={"citations": citations}))
    
    # Ошибки
    errors = node_data.get("errors")
    if errors:
        events.append(StreamEvent(type="errors", node=node_name, data={"errors": errors}))
    
    # Результаты извлечения (для TabularGraph)
    extraction = node_data.get("extraction_results")
    if extraction:
        events.append(StreamEvent(type="extraction", node=node_name, data={"count": len(extraction)}))
    
    # Результаты шагов (для WorkflowGraph)
    step_results = node_data.get("step_results")
    if step_results:
        events.append(StreamEvent(type="step_results", node=node_name, data={"count": len(step_results)}))
    
    # План (для WorkflowGraph)
    plan = node_data.get("plan")
    if plan:
        events.append(StreamEvent(type="plan", node=node_name, data={"plan": plan}))
    
    # Финальный результат
    final_result = node_data.get("final_result")
    if final_result:
        events.append(StreamEvent(type="final_result", node=node_name, data={"result": final_result}))
    
    # Созданный документ (для draft mode)
    document = node_data.get("document_created")
    if document:
        events.append(StreamEvent(type="document", node=node_name, data={"document": document}))
    
    # Thinking steps (для deep_think mode)
    thinking = node_data.get("thinking_steps")
    if thinking:
        events.append(StreamEvent(type="thinking", node=node_name, data={"steps": thinking}))
    
    # Запросы на уточнение (HITL)
    clarifications = node_data.get("clarification_requests")
    if clarifications:
        events.append(StreamEvent(type="clarification", node=node_name, data={"requests": clarifications}))
    
    return events


def _serialize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Сериализовать состояние для JSON."""
    result = {}
    for key, value in state.items():
        result[key] = _serialize_value(value)
    return result


def _serialize_value(value: Any) -> Any:
    """Сериализовать значение для JSON."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, BaseMessage):
        return {"type": type(value).__name__, "content": value.content}
    # Fallback
    return str(value)


def format_sse_event(event: Union[StreamEvent, Dict[str, Any]]) -> str:
    """
    Форматировать событие в SSE формат.
    
    Args:
        event: StreamEvent или словарь
    
    Returns:
        SSE строка
    """
    if isinstance(event, StreamEvent):
        return event.to_sse()
    return f"data: {json.dumps(event)}\n\n"


def create_text_delta_event(text: str) -> str:
    """
    Создать SSE событие text-delta для assistant-ui.
    
    Args:
        text: Текст для отправки
    
    Returns:
        SSE строка
    """
    return f"data: {json.dumps({'type': 'text-delta', 'textDelta': text})}\n\n"


def create_finish_event(reason: str = "stop", error: str = None) -> str:
    """
    Создать SSE событие finish.
    
    Args:
        reason: Причина завершения ("stop", "error", "cancelled")
        error: Текст ошибки (если reason="error")
    
    Returns:
        SSE строка
    """
    event = {"type": "finish", "finishReason": reason}
    if error:
        event["error"] = error
    return f"data: {json.dumps(event)}\n\n"

