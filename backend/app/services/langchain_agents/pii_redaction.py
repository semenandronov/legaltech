"""PII Redaction Middleware - автоматическое обнаружение и маскировка PII"""
from typing import Dict, Any, Optional, List
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.security_middleware import PIIRedactor
import logging

logger = logging.getLogger(__name__)


class PIIRedactionMiddleware:
    """
    Middleware для автоматического обнаружения и маскировки PII (персональных идентифицирующих данных)
    
    Отдельный от SecurityMiddleware для более гибкой настройки и интеграции с PipelineService.
    """
    
    def __init__(
        self,
        enable_redaction: bool = True,
        redaction_replacement: str = "[REDACTED]",
        redact_in_logs: bool = True
    ):
        """
        Инициализация PIIRedactionMiddleware
        
        Args:
            enable_redaction: Включить автоматическую маскировку PII
            redaction_replacement: Строка для замены PII
            redact_in_logs: Маскировать PII в логах
        """
        self.enable_redaction = enable_redaction
        self.redaction_replacement = redaction_replacement
        self.redact_in_logs = redact_in_logs
        self.redactor = PIIRedactor()
    
    def redact_text(self, text: str) -> str:
        """
        Замаскировать PII в тексте
        
        Args:
            text: Исходный текст
            
        Returns:
            Текст с замаскированными PII
        """
        if not self.enable_redaction or not text:
            return text
        
        return self.redactor.redact_text(text, self.redaction_replacement)
    
    def redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Рекурсивно замаскировать PII в словаре
        
        Args:
            data: Словарь для обработки
            
        Returns:
            Словарь с замаскированными PII
        """
        if not self.enable_redaction or not data:
            return data
        
        return self.redactor.redact_dict(data, self.redaction_replacement)
    
    def before_execution(self, state: AnalysisState, node_name: str) -> AnalysisState:
        """
        Вызывается перед выполнением узла
        
        Args:
            state: Текущее состояние
            node_name: Имя узла
            
        Returns:
            Состояние с замаскированными PII
        """
        if not self.enable_redaction:
            return state
        
        try:
            new_state = dict(state)
            
            # Замаскируем PII в messages
            if "messages" in new_state and new_state["messages"]:
                from langchain_core.messages import HumanMessage, AIMessage
                redacted_messages = []
                for msg in new_state["messages"]:
                    if isinstance(msg, (HumanMessage, AIMessage)):
                        if hasattr(msg, 'content') and isinstance(msg.content, str):
                            redacted_content = self.redact_text(msg.content)
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
            
            # Замаскируем PII в metadata
            if "metadata" in new_state and isinstance(new_state["metadata"], dict):
                new_state["metadata"] = self.redact_dict(new_state["metadata"])
            
            logger.debug(f"[PIIRedaction] Applied redaction for node {node_name}")
            return new_state
            
        except Exception as e:
            logger.warning(f"[PIIRedaction] Error in PII redaction: {e}, returning original state")
            return state
    
    def after_execution(self, state: AnalysisState, node_name: str, result_state: AnalysisState) -> AnalysisState:
        """
        Вызывается после выполнения узла
        
        Args:
            state: Исходное состояние
            node_name: Имя узла
            result_state: Результирующее состояние
            
        Returns:
            Результирующее состояние (опционально с замаскированными результатами)
        """
        # Обычно не маскируем результаты после выполнения,
        # так как они уже сохраняются в БД с соответствующим уровнем защиты
        return result_state
    
    def on_error(self, state: AnalysisState, node_name: str, error: Exception) -> Optional[AnalysisState]:
        """
        Вызывается при ошибке
        
        Args:
            state: Состояние на момент ошибки
            node_name: Имя узла
            error: Произошедшая ошибка
            
        Returns:
            None (не восстанавливаем состояние)
        """
        # Маскируем PII в сообщении об ошибке для логов
        if self.redact_in_logs:
            error_msg = str(error)
            redacted_error_msg = self.redact_text(error_msg)
            logger.error(f"[PIIRedaction] Error in node {node_name}: {redacted_error_msg}")
        else:
            logger.error(f"[PIIRedaction] Error in node {node_name}: {error}")
        
        return None
    
    def redact_for_logging(self, message: str) -> str:
        """
        Замаскировать PII в сообщении для логирования
        
        Args:
            message: Сообщение для логирования
            
        Returns:
            Сообщение с замаскированными PII
        """
        if not self.redact_in_logs:
            return message
        
        return self.redact_text(message)

