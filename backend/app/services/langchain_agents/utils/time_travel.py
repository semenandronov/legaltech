"""
Утилиты для Time Travel в LangGraph.

Time Travel позволяет:
- Просматривать историю выполнения графа (checkpoints)
- Воспроизводить выполнение с определённого checkpoint
- Создавать fork (ответвление) с изменённым состоянием

Примеры использования:
```python
from app.services.langchain_agents.utils.time_travel import (
    get_state_history,
    replay_from_checkpoint,
    fork_checkpoint,
    get_checkpoint_metadata,
)

# Получить историю
history = await get_state_history(graph, thread_id)
for checkpoint in history:
    print(f"Checkpoint {checkpoint['id']}: {checkpoint['node']}")

# Replay с checkpoint
async for event in replay_from_checkpoint(graph, thread_id, checkpoint_id):
    print(event)

# Fork с изменениями
new_thread_id = await fork_checkpoint(
    graph, thread_id, checkpoint_id,
    state_updates={"question": "Новый вопрос"}
)
```
"""
from typing import Dict, Any, List, Optional, AsyncGenerator
from dataclasses import dataclass, asdict
from datetime import datetime
import logging
import uuid

logger = logging.getLogger(__name__)


@dataclass
class CheckpointInfo:
    """Информация о checkpoint."""
    checkpoint_id: str
    thread_id: str
    node: Optional[str]
    timestamp: Optional[datetime]
    parent_id: Optional[str]
    state_keys: List[str]
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь."""
        result = asdict(self)
        if result["timestamp"]:
            result["timestamp"] = result["timestamp"].isoformat()
        return result


@dataclass
class StateSnapshot:
    """Снимок состояния."""
    checkpoint_id: str
    state: Dict[str, Any]
    node: Optional[str]
    timestamp: Optional[datetime]
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь."""
        result = {
            "checkpoint_id": self.checkpoint_id,
            "state": self.state,
            "node": self.node,
        }
        if self.timestamp:
            result["timestamp"] = self.timestamp.isoformat()
        return result


async def get_state_history(
    graph,
    thread_id: str,
    limit: int = 50
) -> List[CheckpointInfo]:
    """
    Получить историю checkpoints для thread.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        limit: Максимальное количество checkpoints
    
    Returns:
        Список CheckpointInfo, отсортированный от новых к старым
    """
    logger.info(f"[TimeTravel] Getting state history for thread {thread_id}")
    
    config = {"configurable": {"thread_id": thread_id}}
    history = []
    
    try:
        # Получаем историю состояний
        async for state in graph.aget_state_history(config):
            if len(history) >= limit:
                break
            
            checkpoint_info = CheckpointInfo(
                checkpoint_id=state.config.get("configurable", {}).get("checkpoint_id", ""),
                thread_id=thread_id,
                node=state.next[0] if state.next else None,
                timestamp=state.created_at if hasattr(state, "created_at") else None,
                parent_id=state.parent_config.get("configurable", {}).get("checkpoint_id") if state.parent_config else None,
                state_keys=list(state.values.keys()) if state.values else [],
                metadata=state.metadata if hasattr(state, "metadata") else {}
            )
            history.append(checkpoint_info)
        
        logger.info(f"[TimeTravel] Found {len(history)} checkpoints")
        return history
        
    except Exception as e:
        logger.error(f"[TimeTravel] Error getting history: {e}", exc_info=True)
        return []


async def get_state_at_checkpoint(
    graph,
    thread_id: str,
    checkpoint_id: str
) -> Optional[StateSnapshot]:
    """
    Получить состояние на определённом checkpoint.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        checkpoint_id: ID checkpoint
    
    Returns:
        StateSnapshot или None
    """
    logger.info(f"[TimeTravel] Getting state at checkpoint {checkpoint_id}")
    
    config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id
        }
    }
    
    try:
        state = await graph.aget_state(config)
        
        if state and state.values:
            return StateSnapshot(
                checkpoint_id=checkpoint_id,
                state=dict(state.values),
                node=state.next[0] if state.next else None,
                timestamp=state.created_at if hasattr(state, "created_at") else None
            )
        
        return None
        
    except Exception as e:
        logger.error(f"[TimeTravel] Error getting state: {e}", exc_info=True)
        return None


async def replay_from_checkpoint(
    graph,
    thread_id: str,
    checkpoint_id: str,
    stream_mode: str = "updates"
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Воспроизвести выполнение графа с определённого checkpoint.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        checkpoint_id: ID checkpoint для начала
        stream_mode: Режим streaming
    
    Yields:
        События выполнения
    """
    logger.info(f"[TimeTravel] Replaying from checkpoint {checkpoint_id}")
    
    config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id
        }
    }
    
    try:
        # Продолжаем выполнение с checkpoint
        async for chunk in graph.astream(None, config=config, stream_mode=stream_mode):
            yield {
                "type": "replay_event",
                "data": chunk
            }
        
        yield {"type": "replay_complete"}
        
    except Exception as e:
        logger.error(f"[TimeTravel] Replay error: {e}", exc_info=True)
        yield {"type": "replay_error", "error": str(e)}


async def fork_checkpoint(
    graph,
    thread_id: str,
    checkpoint_id: str,
    state_updates: Dict[str, Any] = None,
    new_thread_id: str = None
) -> Optional[str]:
    """
    Создать fork (ответвление) с checkpoint.
    
    Создаёт новый thread с состоянием из указанного checkpoint,
    опционально применяя изменения к состоянию.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID исходного потока
        checkpoint_id: ID checkpoint для fork
        state_updates: Изменения для применения к состоянию
        new_thread_id: ID для нового потока (генерируется если не указан)
    
    Returns:
        ID нового потока или None при ошибке
    """
    logger.info(f"[TimeTravel] Forking checkpoint {checkpoint_id}")
    
    if new_thread_id is None:
        new_thread_id = f"fork_{thread_id}_{uuid.uuid4().hex[:8]}"
    
    try:
        # Получаем состояние на checkpoint
        snapshot = await get_state_at_checkpoint(graph, thread_id, checkpoint_id)
        
        if not snapshot:
            logger.error("[TimeTravel] Checkpoint not found")
            return None
        
        # Применяем изменения
        new_state = dict(snapshot.state)
        if state_updates:
            new_state.update(state_updates)
        
        # Создаём новый thread с изменённым состоянием
        new_config = {"configurable": {"thread_id": new_thread_id}}
        
        # Обновляем состояние в новом thread
        await graph.aupdate_state(new_config, new_state)
        
        logger.info(f"[TimeTravel] Created fork: {new_thread_id}")
        return new_thread_id
        
    except Exception as e:
        logger.error(f"[TimeTravel] Fork error: {e}", exc_info=True)
        return None


async def compare_checkpoints(
    graph,
    thread_id: str,
    checkpoint_id_1: str,
    checkpoint_id_2: str
) -> Dict[str, Any]:
    """
    Сравнить два checkpoint.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        checkpoint_id_1: ID первого checkpoint
        checkpoint_id_2: ID второго checkpoint
    
    Returns:
        Словарь с различиями
    """
    logger.info(f"[TimeTravel] Comparing checkpoints {checkpoint_id_1} and {checkpoint_id_2}")
    
    state1 = await get_state_at_checkpoint(graph, thread_id, checkpoint_id_1)
    state2 = await get_state_at_checkpoint(graph, thread_id, checkpoint_id_2)
    
    if not state1 or not state2:
        return {"error": "One or both checkpoints not found"}
    
    # Находим различия
    diff = {
        "added_keys": [],
        "removed_keys": [],
        "changed_keys": [],
        "unchanged_keys": []
    }
    
    all_keys = set(state1.state.keys()) | set(state2.state.keys())
    
    for key in all_keys:
        in_1 = key in state1.state
        in_2 = key in state2.state
        
        if in_1 and not in_2:
            diff["removed_keys"].append(key)
        elif in_2 and not in_1:
            diff["added_keys"].append(key)
        elif state1.state.get(key) != state2.state.get(key):
            diff["changed_keys"].append({
                "key": key,
                "old_value": _summarize_value(state1.state.get(key)),
                "new_value": _summarize_value(state2.state.get(key))
            })
        else:
            diff["unchanged_keys"].append(key)
    
    return diff


async def get_execution_path(
    graph,
    thread_id: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Получить путь выполнения (последовательность узлов).
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        limit: Максимальное количество шагов
    
    Returns:
        Список узлов в порядке выполнения
    """
    logger.info(f"[TimeTravel] Getting execution path for thread {thread_id}")
    
    history = await get_state_history(graph, thread_id, limit)
    
    # Инвертируем порядок (от старых к новым)
    history.reverse()
    
    path = []
    for checkpoint in history:
        if checkpoint.node:
            path.append({
                "checkpoint_id": checkpoint.checkpoint_id,
                "node": checkpoint.node,
                "timestamp": checkpoint.timestamp.isoformat() if checkpoint.timestamp else None
            })
    
    return path


async def rollback_to_checkpoint(
    graph,
    thread_id: str,
    checkpoint_id: str
) -> bool:
    """
    Откатить thread к определённому checkpoint.
    
    ВНИМАНИЕ: Это удаляет все checkpoints после указанного!
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        checkpoint_id: ID checkpoint для отката
    
    Returns:
        True если успешно
    """
    logger.warning(f"[TimeTravel] Rolling back thread {thread_id} to checkpoint {checkpoint_id}")
    
    try:
        # Получаем состояние на checkpoint
        snapshot = await get_state_at_checkpoint(graph, thread_id, checkpoint_id)
        
        if not snapshot:
            logger.error("[TimeTravel] Checkpoint not found")
            return False
        
        # Обновляем состояние (это создаст новый checkpoint)
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id
            }
        }
        
        await graph.aupdate_state(config, snapshot.state)
        
        logger.info(f"[TimeTravel] Rollback complete")
        return True
        
    except Exception as e:
        logger.error(f"[TimeTravel] Rollback error: {e}", exc_info=True)
        return False


def _summarize_value(value: Any) -> str:
    """Создать краткое описание значения."""
    if value is None:
        return "None"
    if isinstance(value, str):
        if len(value) > 100:
            return f"str({len(value)} chars)"
        return f'"{value}"'
    if isinstance(value, (list, tuple)):
        return f"list({len(value)} items)"
    if isinstance(value, dict):
        return f"dict({len(value)} keys)"
    if isinstance(value, (int, float, bool)):
        return str(value)
    return f"{type(value).__name__}"


class TimeTravelManager:
    """
    Менеджер для Time Travel операций.
    
    Предоставляет удобный интерфейс для работы с историей выполнения.
    
    Example:
        >>> manager = TimeTravelManager(graph, thread_id)
        >>> history = await manager.get_history()
        >>> await manager.fork_from(checkpoint_id, {"question": "New question"})
    """
    
    def __init__(self, graph, thread_id: str):
        """
        Инициализация.
        
        Args:
            graph: Скомпилированный LangGraph
            thread_id: ID потока
        """
        self.graph = graph
        self.thread_id = thread_id
    
    async def get_history(self, limit: int = 50) -> List[CheckpointInfo]:
        """Получить историю checkpoints."""
        return await get_state_history(self.graph, self.thread_id, limit)
    
    async def get_state(self, checkpoint_id: str = None) -> Optional[StateSnapshot]:
        """
        Получить состояние.
        
        Args:
            checkpoint_id: ID checkpoint (None для текущего)
        """
        if checkpoint_id:
            return await get_state_at_checkpoint(self.graph, self.thread_id, checkpoint_id)
        
        config = {"configurable": {"thread_id": self.thread_id}}
        state = await self.graph.aget_state(config)
        
        if state and state.values:
            return StateSnapshot(
                checkpoint_id=state.config.get("configurable", {}).get("checkpoint_id", ""),
                state=dict(state.values),
                node=state.next[0] if state.next else None,
                timestamp=state.created_at if hasattr(state, "created_at") else None
            )
        return None
    
    async def replay(
        self,
        checkpoint_id: str,
        stream_mode: str = "updates"
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Воспроизвести с checkpoint."""
        async for event in replay_from_checkpoint(
            self.graph, self.thread_id, checkpoint_id, stream_mode
        ):
            yield event
    
    async def fork_from(
        self,
        checkpoint_id: str,
        state_updates: Dict[str, Any] = None,
        new_thread_id: str = None
    ) -> Optional[str]:
        """Создать fork с checkpoint."""
        return await fork_checkpoint(
            self.graph, self.thread_id, checkpoint_id, state_updates, new_thread_id
        )
    
    async def compare(
        self,
        checkpoint_id_1: str,
        checkpoint_id_2: str
    ) -> Dict[str, Any]:
        """Сравнить два checkpoint."""
        return await compare_checkpoints(
            self.graph, self.thread_id, checkpoint_id_1, checkpoint_id_2
        )
    
    async def get_path(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Получить путь выполнения."""
        return await get_execution_path(self.graph, self.thread_id, limit)
    
    async def rollback(self, checkpoint_id: str) -> bool:
        """Откатить к checkpoint."""
        return await rollback_to_checkpoint(self.graph, self.thread_id, checkpoint_id)

