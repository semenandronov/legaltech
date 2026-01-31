"""
Утилиты для редактирования состояния в LangGraph.

State Editing позволяет:
- Редактировать состояние на breakpoints
- Обновлять конкретные ключи состояния
- Редактировать сообщения по ID
- Возобновлять выполнение с изменённым состоянием

Примеры использования:
```python
from app.services.langchain_agents.utils.state_editing import (
    StateEditor,
    update_state,
    edit_message,
    resume_with_updates,
)

# Редактирование состояния
editor = StateEditor(graph, thread_id)
await editor.update({"question": "Новый вопрос"})
await editor.resume()

# Редактирование сообщения
await edit_message(graph, thread_id, message_id, "Новый текст")
```
"""
from typing import Dict, Any, List, Optional, Union
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, RemoveMessage
from langgraph.types import Command
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class StateUpdate:
    """Обновление состояния."""
    key: str
    value: Any
    operation: str = "set"  # "set", "append", "remove", "merge"
    
    def apply(self, current_value: Any) -> Any:
        """Применить обновление к текущему значению."""
        if self.operation == "set":
            return self.value
        elif self.operation == "append":
            if current_value is None:
                return [self.value] if not isinstance(self.value, list) else self.value
            if isinstance(current_value, list):
                if isinstance(self.value, list):
                    return current_value + self.value
                return current_value + [self.value]
            return [current_value, self.value]
        elif self.operation == "remove":
            if isinstance(current_value, list):
                return [v for v in current_value if v != self.value]
            return None if current_value == self.value else current_value
        elif self.operation == "merge":
            if isinstance(current_value, dict) and isinstance(self.value, dict):
                result = dict(current_value)
                result.update(self.value)
                return result
            return self.value
        return self.value


async def update_state(
    graph,
    thread_id: str,
    updates: Dict[str, Any],
    as_node: str = None
) -> bool:
    """
    Обновить состояние графа.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        updates: Словарь обновлений {key: value}
        as_node: Имя узла для записи (влияет на reducers)
    
    Returns:
        True если успешно
    """
    logger.info(f"[StateEditing] Updating state for thread {thread_id}: {list(updates.keys())}")
    
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        if as_node:
            await graph.aupdate_state(config, updates, as_node=as_node)
        else:
            await graph.aupdate_state(config, updates)
        
        logger.info("[StateEditing] State updated successfully")
        return True
        
    except Exception as e:
        logger.error(f"[StateEditing] Update error: {e}", exc_info=True)
        return False


async def edit_message(
    graph,
    thread_id: str,
    message_id: str,
    new_content: str,
    as_node: str = None
) -> bool:
    """
    Редактировать сообщение по ID.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        message_id: ID сообщения для редактирования
        new_content: Новое содержимое
        as_node: Имя узла для записи
    
    Returns:
        True если успешно
    """
    logger.info(f"[StateEditing] Editing message {message_id} for thread {thread_id}")
    
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        # Получаем текущее состояние
        state = await graph.aget_state(config)
        
        if not state or not state.values:
            logger.error("[StateEditing] No state found")
            return False
        
        messages = state.values.get("messages", [])
        
        # Ищем сообщение по ID
        found = False
        for msg in messages:
            if getattr(msg, "id", None) == message_id:
                found = True
                break
        
        if not found:
            logger.warning(f"[StateEditing] Message {message_id} not found")
            return False
        
        # Создаём новое сообщение с тем же ID
        # Это перезапишет старое благодаря add_messages reducer
        new_message = HumanMessage(content=new_content, id=message_id)
        
        updates = {"messages": [new_message]}
        
        if as_node:
            await graph.aupdate_state(config, updates, as_node=as_node)
        else:
            await graph.aupdate_state(config, updates)
        
        logger.info("[StateEditing] Message edited successfully")
        return True
        
    except Exception as e:
        logger.error(f"[StateEditing] Edit error: {e}", exc_info=True)
        return False


async def remove_message(
    graph,
    thread_id: str,
    message_id: str
) -> bool:
    """
    Удалить сообщение по ID.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        message_id: ID сообщения для удаления
    
    Returns:
        True если успешно
    """
    logger.info(f"[StateEditing] Removing message {message_id} for thread {thread_id}")
    
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        # Используем RemoveMessage для удаления
        updates = {"messages": [RemoveMessage(id=message_id)]}
        await graph.aupdate_state(config, updates)
        
        logger.info("[StateEditing] Message removed successfully")
        return True
        
    except Exception as e:
        logger.error(f"[StateEditing] Remove error: {e}", exc_info=True)
        return False


async def resume_with_updates(
    graph,
    thread_id: str,
    updates: Dict[str, Any] = None,
    input_value: Any = None
) -> Any:
    """
    Возобновить выполнение графа с обновлениями.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
        updates: Обновления состояния перед возобновлением
        input_value: Входное значение для Command(resume=...)
    
    Returns:
        Результат выполнения
    """
    logger.info(f"[StateEditing] Resuming thread {thread_id}")
    
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        # Применяем обновления если есть
        if updates:
            await update_state(graph, thread_id, updates)
        
        # Создаём Command для resume
        if input_value is not None:
            command = Command(resume=input_value)
        else:
            command = None
        
        # Возобновляем выполнение
        result = await graph.ainvoke(command, config=config)
        
        logger.info("[StateEditing] Resume completed")
        return result
        
    except Exception as e:
        logger.error(f"[StateEditing] Resume error: {e}", exc_info=True)
        raise


async def get_editable_state(
    graph,
    thread_id: str
) -> Optional[Dict[str, Any]]:
    """
    Получить состояние для редактирования.
    
    Args:
        graph: Скомпилированный LangGraph
        thread_id: ID потока
    
    Returns:
        Словарь с редактируемыми полями или None
    """
    logger.info(f"[StateEditing] Getting editable state for thread {thread_id}")
    
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        state = await graph.aget_state(config)
        
        if not state or not state.values:
            return None
        
        # Возвращаем состояние с метаданными
        return {
            "values": dict(state.values),
            "next": state.next if state.next else [],
            "checkpoint_id": state.config.get("configurable", {}).get("checkpoint_id"),
            "is_interrupted": len(state.next) > 0
        }
        
    except Exception as e:
        logger.error(f"[StateEditing] Get state error: {e}", exc_info=True)
        return None


class StateEditor:
    """
    Редактор состояния для удобной работы с HITL.
    
    Example:
        >>> editor = StateEditor(graph, thread_id)
        >>> await editor.load()
        >>> editor.set("question", "Новый вопрос")
        >>> editor.append("messages", HumanMessage("Новое сообщение"))
        >>> await editor.save()
        >>> result = await editor.resume()
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
        self._state: Dict[str, Any] = {}
        self._updates: List[StateUpdate] = []
        self._loaded = False
    
    async def load(self) -> "StateEditor":
        """Загрузить текущее состояние."""
        result = await get_editable_state(self.graph, self.thread_id)
        if result:
            self._state = result["values"]
            self._loaded = True
        return self
    
    @property
    def state(self) -> Dict[str, Any]:
        """Текущее состояние."""
        return self._state
    
    @property
    def is_loaded(self) -> bool:
        """Загружено ли состояние."""
        return self._loaded
    
    def get(self, key: str, default: Any = None) -> Any:
        """Получить значение из состояния."""
        return self._state.get(key, default)
    
    def set(self, key: str, value: Any) -> "StateEditor":
        """Установить значение."""
        self._updates.append(StateUpdate(key, value, "set"))
        return self
    
    def append(self, key: str, value: Any) -> "StateEditor":
        """Добавить значение к списку."""
        self._updates.append(StateUpdate(key, value, "append"))
        return self
    
    def remove(self, key: str, value: Any) -> "StateEditor":
        """Удалить значение из списка."""
        self._updates.append(StateUpdate(key, value, "remove"))
        return self
    
    def merge(self, key: str, value: Dict[str, Any]) -> "StateEditor":
        """Объединить словари."""
        self._updates.append(StateUpdate(key, value, "merge"))
        return self
    
    def edit_message(self, message_id: str, new_content: str) -> "StateEditor":
        """Редактировать сообщение."""
        new_message = HumanMessage(content=new_content, id=message_id)
        self._updates.append(StateUpdate("messages", [new_message], "append"))
        return self
    
    def remove_message(self, message_id: str) -> "StateEditor":
        """Удалить сообщение."""
        self._updates.append(StateUpdate("messages", [RemoveMessage(id=message_id)], "append"))
        return self
    
    def get_pending_updates(self) -> Dict[str, Any]:
        """Получить накопленные обновления."""
        result = {}
        for update in self._updates:
            current = result.get(update.key, self._state.get(update.key))
            result[update.key] = update.apply(current)
        return result
    
    async def save(self, as_node: str = None) -> bool:
        """
        Сохранить изменения.
        
        Args:
            as_node: Имя узла для записи
        
        Returns:
            True если успешно
        """
        if not self._updates:
            logger.info("[StateEditor] No updates to save")
            return True
        
        updates = self.get_pending_updates()
        success = await update_state(self.graph, self.thread_id, updates, as_node)
        
        if success:
            # Применяем обновления к локальному состоянию
            self._state.update(updates)
            self._updates = []
        
        return success
    
    async def resume(self, input_value: Any = None) -> Any:
        """
        Возобновить выполнение.
        
        Args:
            input_value: Входное значение для resume
        
        Returns:
            Результат выполнения
        """
        # Сохраняем накопленные изменения
        if self._updates:
            await self.save()
        
        return await resume_with_updates(
            self.graph, self.thread_id, None, input_value
        )
    
    async def discard(self) -> "StateEditor":
        """Отменить накопленные изменения."""
        self._updates = []
        return self


async def create_human_feedback_update(
    feedback_type: str,
    feedback_value: Any,
    metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Создать обновление состояния для human feedback.
    
    Args:
        feedback_type: Тип feedback ("approval", "clarification", "correction")
        feedback_value: Значение feedback
        metadata: Дополнительные метаданные
    
    Returns:
        Словарь обновлений
    """
    updates = {
        "human_feedback": {
            "type": feedback_type,
            "value": feedback_value,
            "metadata": metadata or {}
        }
    }
    
    # Специфичные обновления по типу
    if feedback_type == "approval":
        updates["plan_approved"] = feedback_value
    elif feedback_type == "clarification":
        updates["clarification_responses"] = feedback_value
    elif feedback_type == "correction":
        if isinstance(feedback_value, dict):
            updates.update(feedback_value)
    
    return updates

