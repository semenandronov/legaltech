"""Security Middleware - PII redaction и валидация tool calls"""
import re
from typing import Dict, Any, Optional, List
from app.services.langchain_agents.state import AnalysisState
import logging

logger = logging.getLogger(__name__)


class PIIRedactor:
    """Утилита для обнаружения и маскировки PII (персональных идентифицирующих данных)"""
    
    # Паттерны для обнаружения PII
    PHONE_PATTERNS = [
        r'\+?\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}',  # Телефоны
        r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # US format
        r'\+7\s?\(?\d{3}\)?\s?\d{3}[-.\s]?\d{2}[-.\s]?\d{2}',  # Российские телефоны
    ]
    
    EMAIL_PATTERN = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    
    # Паттерны для паспортов (российские)
    PASSPORT_PATTERN = r'\d{4}\s?\d{6}'
    
    # IP адреса
    IP_PATTERN = r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'
    
    @classmethod
    def redact_text(cls, text: str, replacement: str = "[REDACTED]") -> str:
        """
        Обнаружить и замаскировать PII в тексте
        
        Args:
            text: Исходный текст
            replacement: Строка для замены PII
            
        Returns:
            Текст с замаскированными PII
        """
        if not text:
            return text
        
        result = text
        
        # Маскируем телефоны
        for pattern in cls.PHONE_PATTERNS:
            result = re.sub(pattern, replacement, result)
        
        # Маскируем email
        result = re.sub(cls.EMAIL_PATTERN, replacement, result)
        
        # Маскируем паспорта
        result = re.sub(cls.PASSPORT_PATTERN, replacement, result)
        
        # Маскируем IP адреса
        result = re.sub(cls.IP_PATTERN, replacement, result)
        
        return result
    
    @classmethod
    def redact_dict(cls, data: Dict[str, Any], replacement: str = "[REDACTED]") -> Dict[str, Any]:
        """
        Рекурсивно замаскировать PII в словаре
        
        Args:
            data: Словарь для обработки
            replacement: Строка для замены PII
            
        Returns:
            Словарь с замаскированными PII
        """
        if not isinstance(data, dict):
            return data
        
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = cls.redact_text(value, replacement)
            elif isinstance(value, dict):
                result[key] = cls.redact_dict(value, replacement)
            elif isinstance(value, list):
                result[key] = [
                    cls.redact_dict(item, replacement) if isinstance(item, dict)
                    else cls.redact_text(item, replacement) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        
        return result


class SecurityMiddleware:
    """Middleware для безопасности: PII redaction и валидация"""
    
    def __init__(self, enable_pii_redaction: bool = True, redaction_replacement: str = "[REDACTED]"):
        """
        Инициализация SecurityMiddleware
        
        Args:
            enable_pii_redaction: Включить автоматическую маскировку PII
            redaction_replacement: Строка для замены PII
        """
        self.enable_pii_redaction = enable_pii_redaction
        self.redaction_replacement = redaction_replacement
        self.redactor = PIIRedactor()
    
    def before_execution(self, state: AnalysisState, node_name: str) -> AnalysisState:
        """
        Вызывается перед выполнением узла
        
        Args:
            state: Текущее состояние
            node_name: Имя узла
            
        Returns:
            Состояние с замаскированными PII (если включено)
        """
        if not self.enable_pii_redaction:
            return state
        
        try:
            # Создаём копию состояния для безопасности
            new_state = dict(state)
            
            # Замаскируем PII в messages (если есть)
            if "messages" in new_state and new_state["messages"]:
                from langchain_core.messages import HumanMessage, AIMessage
                redacted_messages = []
                for msg in new_state["messages"]:
                    if isinstance(msg, (HumanMessage, AIMessage)):
                        # Создаём новый message с замаскированным контентом
                        if hasattr(msg, 'content') and isinstance(msg.content, str):
                            redacted_content = self.redactor.redact_text(msg.content, self.redaction_replacement)
                            # Создаём новый message с замаскированным контентом
                            new_msg = type(msg)(content=redacted_content)
                            # Копируем другие атрибуты
                            for attr in ['name', 'id', 'additional_kwargs']:
                                if hasattr(msg, attr):
                                    setattr(new_msg, attr, getattr(msg, attr))
                            redacted_messages.append(new_msg)
                        else:
                            redacted_messages.append(msg)
                    else:
                        redacted_messages.append(msg)
                new_state["messages"] = redacted_messages
            
            # Замаскируем PII в metadata (если есть строковые значения)
            if "metadata" in new_state and isinstance(new_state["metadata"], dict):
                new_state["metadata"] = self.redactor.redact_dict(new_state["metadata"], self.redaction_replacement)
            
            logger.debug(f"[SecurityMiddleware] PII redaction applied for node {node_name}")
            return new_state
            
        except Exception as e:
            logger.warning(f"[SecurityMiddleware] Error in PII redaction: {e}, returning original state")
            return state
    
    def after_execution(self, state: AnalysisState, node_name: str, result_state: AnalysisState) -> AnalysisState:
        """
        Вызывается после выполнения узла
        
        Args:
            state: Исходное состояние
            node_name: Имя узла
            result_state: Результирующее состояние
            
        Returns:
            Результирующее состояние (PII redaction опционально)
        """
        # После выполнения можно также замаскировать результаты, но обычно это не нужно
        # так как результаты уже сохраняются в БД и там может быть другой уровень защиты
        return result_state
    
    def validate_tool_call(self, tool_name: str, tool_args: Dict[str, Any]) -> bool:
        """
        Валидация вызова tool
        
        Args:
            tool_name: Имя tool
            tool_args: Аргументы tool
            
        Returns:
            True если валидно, False если нет
        """
        # Базовая валидация - можно расширить
        if not tool_name or not isinstance(tool_args, dict):
            logger.warning(f"[SecurityMiddleware] Invalid tool call: tool_name={tool_name}, args={tool_args}")
            return False
        
        # Можно добавить проверку на известные уязвимости
        # Например, SQL injection в case_id и т.д.
        
        return True
    
    def on_error(self, state: AnalysisState, node_name: str, error: Exception) -> Optional[AnalysisState]:
        """
        Вызывается при ошибке
        
        Args:
            state: Состояние на момент ошибки
            node_name: Имя узла
            error: Произошедшая ошибка
            
        Returns:
            None (не восстанавливаем состояние при ошибках безопасности)
        """
        logger.error(f"[SecurityMiddleware] Error in node {node_name}: {error}")
        return None

