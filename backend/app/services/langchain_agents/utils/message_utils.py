"""
Утилиты для работы с сообщениями в LangGraph.

Включает функции для:
- Фильтрации сообщений по количеству
- Обрезки сообщений по токенам
- Создания summary старых сообщений
- Работы с RemoveMessage для удаления сообщений
"""
from typing import List, Dict, Any, Optional, Union, Callable
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    RemoveMessage,
    trim_messages,
)
from langchain_core.language_models import BaseChatModel
import logging

logger = logging.getLogger(__name__)


def filter_messages_by_count(
    messages: List[BaseMessage],
    keep_last_n: int = 10,
    always_keep_system: bool = True
) -> List[BaseMessage]:
    """
    Оставить только последние N сообщений.
    
    Args:
        messages: Список сообщений
        keep_last_n: Количество последних сообщений для сохранения
        always_keep_system: Всегда сохранять SystemMessage
    
    Returns:
        Отфильтрованный список сообщений
    
    Example:
        >>> msgs = [HumanMessage("1"), AIMessage("2"), HumanMessage("3")]
        >>> filter_messages_by_count(msgs, keep_last_n=2)
        [AIMessage("2"), HumanMessage("3")]
    """
    if not messages:
        return []
    
    if len(messages) <= keep_last_n:
        return list(messages)
    
    result = []
    
    # Сохраняем SystemMessage если нужно
    if always_keep_system:
        for msg in messages:
            if isinstance(msg, SystemMessage):
                result.append(msg)
                break
    
    # Добавляем последние N сообщений
    last_messages = messages[-keep_last_n:]
    for msg in last_messages:
        if isinstance(msg, SystemMessage) and always_keep_system:
            continue  # Уже добавлен
        result.append(msg)
    
    return result


def trim_messages_by_tokens(
    messages: List[BaseMessage],
    max_tokens: int = 4000,
    token_counter: Optional[Callable[[List[BaseMessage]], int]] = None,
    strategy: str = "last",
    allow_partial: bool = False,
    include_system: bool = True,
    start_on: Optional[str] = None
) -> List[BaseMessage]:
    """
    Обрезать сообщения по количеству токенов.
    
    Использует встроенную функцию trim_messages из langchain_core.
    
    Args:
        messages: Список сообщений
        max_tokens: Максимальное количество токенов
        token_counter: Функция подсчёта токенов (или LLM с методом get_num_tokens_from_messages)
        strategy: "last" (последние) или "first" (первые)
        allow_partial: Разрешить частичную обрезку сообщения
        include_system: Включить SystemMessage в результат
        start_on: Тип сообщения для начала ("human" или "ai")
    
    Returns:
        Обрезанный список сообщений
    """
    if not messages:
        return []
    
    # Если нет token_counter, используем простую оценку
    if token_counter is None:
        def simple_counter(msgs: List[BaseMessage]) -> int:
            """Простая оценка: ~4 символа = 1 токен."""
            total = 0
            for msg in msgs:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                total += len(content) // 4
            return total
        token_counter = simple_counter
    
    try:
        return trim_messages(
            messages,
            max_tokens=max_tokens,
            token_counter=token_counter,
            strategy=strategy,
            allow_partial=allow_partial,
            include_system=include_system,
            start_on=start_on,
        )
    except Exception as e:
        logger.warning(f"[MessageUtils] trim_messages error: {e}, falling back to simple filter")
        # Fallback: просто ограничиваем количество
        return filter_messages_by_count(messages, keep_last_n=max_tokens // 100)


async def summarize_old_messages(
    messages: List[BaseMessage],
    llm: BaseChatModel,
    keep_last_n: int = 5,
    summary_max_tokens: int = 500
) -> tuple[Optional[str], List[BaseMessage]]:
    """
    Создать summary старых сообщений и вернуть последние.
    
    Args:
        messages: Полный список сообщений
        llm: LLM для генерации summary
        keep_last_n: Количество последних сообщений для сохранения
        summary_max_tokens: Максимальная длина summary
    
    Returns:
        Tuple из (summary_text, recent_messages)
    
    Example:
        >>> summary, recent = await summarize_old_messages(messages, llm, keep_last_n=5)
        >>> # summary содержит краткое содержание старых сообщений
        >>> # recent содержит последние 5 сообщений
    """
    if not messages or len(messages) <= keep_last_n:
        return None, list(messages)
    
    # Разделяем на старые и новые
    old_messages = messages[:-keep_last_n]
    recent_messages = messages[-keep_last_n:]
    
    if not old_messages:
        return None, recent_messages
    
    # Формируем текст для summarization
    conversation_text = []
    for msg in old_messages:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        conversation_text.append(f"{role}: {content}")
    
    summary_prompt = f"""Создай краткое резюме следующего диалога (максимум {summary_max_tokens} токенов).
Сохрани ключевые факты, решения и контекст, важный для продолжения разговора.

ДИАЛОГ:
{chr(10).join(conversation_text)}

РЕЗЮМЕ:"""
    
    try:
        response = await llm.ainvoke([HumanMessage(content=summary_prompt)])
        summary = response.content if hasattr(response, 'content') else str(response)
        
        logger.info(f"[MessageUtils] Created summary of {len(old_messages)} messages")
        return summary, recent_messages
        
    except Exception as e:
        logger.error(f"[MessageUtils] Summary generation error: {e}")
        return None, recent_messages


def create_summary_message(summary: str) -> SystemMessage:
    """
    Создать SystemMessage с summary предыдущего контекста.
    
    Args:
        summary: Текст summary
    
    Returns:
        SystemMessage с summary
    """
    return SystemMessage(content=f"[Контекст предыдущего диалога]\n{summary}")


def get_remove_messages(
    messages: List[BaseMessage],
    keep_ids: Optional[List[str]] = None,
    remove_ids: Optional[List[str]] = None
) -> List[RemoveMessage]:
    """
    Создать список RemoveMessage для удаления сообщений.
    
    Args:
        messages: Список сообщений
        keep_ids: ID сообщений для сохранения (остальные удаляются)
        remove_ids: ID сообщений для удаления
    
    Returns:
        Список RemoveMessage
    """
    result = []
    
    for msg in messages:
        msg_id = getattr(msg, 'id', None)
        if msg_id is None:
            continue
        
        should_remove = False
        
        if remove_ids is not None and msg_id in remove_ids:
            should_remove = True
        elif keep_ids is not None and msg_id not in keep_ids:
            should_remove = True
        
        if should_remove:
            result.append(RemoveMessage(id=msg_id))
    
    return result


def merge_messages_with_summary(
    summary: Optional[str],
    recent_messages: List[BaseMessage],
    system_message: Optional[SystemMessage] = None
) -> List[BaseMessage]:
    """
    Объединить summary с последними сообщениями.
    
    Args:
        summary: Summary старых сообщений (может быть None)
        recent_messages: Последние сообщения
        system_message: Опциональный SystemMessage для начала
    
    Returns:
        Объединённый список сообщений
    """
    result = []
    
    # Добавляем system message если есть
    if system_message:
        result.append(system_message)
    
    # Добавляем summary как SystemMessage
    if summary:
        result.append(create_summary_message(summary))
    
    # Добавляем последние сообщения (исключая SystemMessage если уже добавлен)
    for msg in recent_messages:
        if isinstance(msg, SystemMessage):
            if not system_message:
                result.append(msg)
        else:
            result.append(msg)
    
    return result


def count_message_tokens_approx(messages: List[BaseMessage]) -> int:
    """
    Приблизительный подсчёт токенов в сообщениях.
    
    Использует эвристику: ~4 символа = 1 токен.
    
    Args:
        messages: Список сообщений
    
    Returns:
        Приблизительное количество токенов
    """
    total = 0
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        # ~4 символа = 1 токен для латиницы
        # ~2 символа = 1 токен для кириллицы (более консервативная оценка)
        # Используем среднее
        total += len(content) // 3
    return total


def should_trim_messages(
    messages: List[BaseMessage],
    threshold_tokens: int = 3000
) -> bool:
    """
    Проверить, нужно ли обрезать сообщения.
    
    Args:
        messages: Список сообщений
        threshold_tokens: Порог токенов
    
    Returns:
        True если нужно обрезать
    """
    return count_message_tokens_approx(messages) > threshold_tokens


class MessageManager:
    """
    Менеджер для управления историей сообщений в графе.
    
    Автоматически управляет длиной истории, создаёт summary
    и поддерживает контекст диалога.
    
    Example:
        >>> manager = MessageManager(llm, max_messages=20, max_tokens=4000)
        >>> state = await manager.process_state(state)
    """
    
    def __init__(
        self,
        llm: Optional[BaseChatModel] = None,
        max_messages: int = 20,
        max_tokens: int = 4000,
        summarize_threshold: int = 15,
        keep_last_n: int = 5
    ):
        """
        Инициализация MessageManager.
        
        Args:
            llm: LLM для генерации summary (опционально)
            max_messages: Максимальное количество сообщений
            max_tokens: Максимальное количество токенов
            summarize_threshold: Порог для создания summary
            keep_last_n: Количество последних сообщений при summarization
        """
        self.llm = llm
        self.max_messages = max_messages
        self.max_tokens = max_tokens
        self.summarize_threshold = summarize_threshold
        self.keep_last_n = keep_last_n
    
    async def process_messages(
        self,
        messages: List[BaseMessage],
        force_summarize: bool = False
    ) -> Dict[str, Any]:
        """
        Обработать сообщения и вернуть результат.
        
        Args:
            messages: Список сообщений
            force_summarize: Принудительно создать summary
        
        Returns:
            Dict с ключами: messages, summary, trimmed
        """
        result = {
            "messages": messages,
            "summary": None,
            "trimmed": False
        }
        
        if not messages:
            return result
        
        # Проверяем нужно ли обрабатывать
        needs_processing = (
            force_summarize or
            len(messages) > self.max_messages or
            should_trim_messages(messages, self.max_tokens)
        )
        
        if not needs_processing:
            return result
        
        # Пробуем создать summary если есть LLM
        if self.llm and len(messages) >= self.summarize_threshold:
            try:
                summary, recent = await summarize_old_messages(
                    messages,
                    self.llm,
                    keep_last_n=self.keep_last_n
                )
                if summary:
                    result["summary"] = summary
                    result["messages"] = merge_messages_with_summary(summary, recent)
                    result["trimmed"] = True
                    return result
            except Exception as e:
                logger.warning(f"[MessageManager] Summary failed: {e}")
        
        # Fallback: просто обрезаем
        if len(messages) > self.max_messages:
            result["messages"] = filter_messages_by_count(messages, self.max_messages)
            result["trimmed"] = True
        elif should_trim_messages(messages, self.max_tokens):
            result["messages"] = trim_messages_by_tokens(messages, self.max_tokens)
            result["trimmed"] = True
        
        return result

