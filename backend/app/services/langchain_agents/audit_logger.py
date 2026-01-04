"""Audit Logger - логирование tool calls, маршрутизации, human feedback, ошибок"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from enum import Enum
import logging
import json

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """Типы событий для аудита"""
    TOOL_CALL = "tool_call"
    ROUTING = "routing"
    HUMAN_FEEDBACK = "human_feedback"
    ERROR = "error"
    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    CLASSIFICATION = "classification"
    MIDDLEWARE = "middleware"


class AuditLogger:
    """
    Логгер для аудита действий системы:
    - Tool calls и их результаты
    - Маршрутизация запросов
    - Human feedback запросы и ответы
    - Ошибки и исключения
    - Метрики производительности
    """
    
    def __init__(self, enable_file_logging: bool = True, log_file_path: Optional[str] = None):
        """
        Инициализация AuditLogger
        
        Args:
            enable_file_logging: Включить логирование в файл
            log_file_path: Путь к файлу логов (по умолчанию: audit.log)
        """
        self.enable_file_logging = enable_file_logging
        self.log_file_path = log_file_path or "audit.log"
        self._audit_logger = logging.getLogger("audit")
        self._audit_logger.setLevel(logging.INFO)
        
        # Настраиваем файловый handler если включено
        if enable_file_logging:
            file_handler = logging.FileHandler(self.log_file_path)
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(formatter)
            self._audit_logger.addHandler(file_handler)
    
    def log_tool_call(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        result: Any,
        case_id: str,
        user_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None
    ):
        """
        Логировать вызов tool
        
        Args:
            tool_name: Имя tool
            tool_args: Аргументы tool
            result: Результат выполнения
            case_id: Идентификатор дела
            user_id: Идентификатор пользователя
            agent_name: Имя агента, вызвавшего tool
            latency_ms: Задержка выполнения в миллисекундах
            error: Ошибка если была
        """
        event = {
            "event_type": AuditEventType.TOOL_CALL.value,
            "timestamp": datetime.utcnow().isoformat(),
            "tool_name": tool_name,
            "tool_args": self._sanitize_args(tool_args),
            "case_id": case_id,
            "user_id": user_id,
            "agent_name": agent_name,
            "latency_ms": latency_ms,
            "success": error is None,
            "error": error
        }
        
        # Не логируем полный результат (может быть большим)
        if result is not None:
            result_str = str(result)
            event["result_preview"] = result_str[:200] if len(result_str) > 200 else result_str
        
        self._log_event(event)
    
    def log_routing(
        self,
        query: str,
        classification: Dict[str, Any],
        case_id: str,
        user_id: Optional[str] = None,
        routing_path: Optional[str] = None
    ):
        """
        Логировать маршрутизацию запроса
        
        Args:
            query: Запрос пользователя
            classification: Результат классификации
            case_id: Идентификатор дела
            user_id: Идентификатор пользователя
            routing_path: Выбранный путь (rag/agent)
        """
        event = {
            "event_type": AuditEventType.ROUTING.value,
            "timestamp": datetime.utcnow().isoformat(),
            "query": query[:200],  # Ограничиваем длину
            "classification": classification,
            "routing_path": routing_path,
            "case_id": case_id,
            "user_id": user_id
        }
        
        self._log_event(event)
    
    def log_human_feedback(
        self,
        request_id: str,
        question: str,
        response: Optional[str],
        case_id: str,
        user_id: Optional[str] = None,
        approved: Optional[bool] = None
    ):
        """
        Логировать human feedback
        
        Args:
            request_id: Идентификатор запроса обратной связи
            question: Вопрос для пользователя
            response: Ответ пользователя
            case_id: Идентификатор дела
            user_id: Идентификатор пользователя
            approved: Одобрено ли действие
        """
        event = {
            "event_type": AuditEventType.HUMAN_FEEDBACK.value,
            "timestamp": datetime.utcnow().isoformat(),
            "request_id": request_id,
            "question": question,
            "response": response,
            "approved": approved,
            "case_id": case_id,
            "user_id": user_id
        }
        
        self._log_event(event)
    
    def log_error(
        self,
        error: Exception,
        context: Dict[str, Any],
        case_id: Optional[str] = None,
        user_id: Optional[str] = None
    ):
        """
        Логировать ошибку
        
        Args:
            error: Исключение
            context: Контекст ошибки
            case_id: Идентификатор дела
            user_id: Идентификатор пользователя
        """
        event = {
            "event_type": AuditEventType.ERROR.value,
            "timestamp": datetime.utcnow().isoformat(),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "context": context,
            "case_id": case_id,
            "user_id": user_id
        }
        
        self._log_event(event)
    
    def log_agent_start(
        self,
        agent_name: str,
        case_id: str,
        user_id: Optional[str] = None,
        analysis_type: Optional[str] = None
    ):
        """
        Логировать начало работы агента
        
        Args:
            agent_name: Имя агента
            case_id: Идентификатор дела
            user_id: Идентификатор пользователя
            analysis_type: Тип анализа
        """
        event = {
            "event_type": AuditEventType.AGENT_START.value,
            "timestamp": datetime.utcnow().isoformat(),
            "agent_name": agent_name,
            "case_id": case_id,
            "user_id": user_id,
            "analysis_type": analysis_type
        }
        
        self._log_event(event)
    
    def log_agent_complete(
        self,
        agent_name: str,
        case_id: str,
        success: bool,
        user_id: Optional[str] = None,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None
    ):
        """
        Логировать завершение работы агента
        
        Args:
            agent_name: Имя агента
            case_id: Идентификатор дела
            success: Успешность выполнения
            user_id: Идентификатор пользователя
            latency_ms: Задержка выполнения в миллисекундах
            error: Ошибка если была
        """
        event = {
            "event_type": AuditEventType.AGENT_COMPLETE.value,
            "timestamp": datetime.utcnow().isoformat(),
            "agent_name": agent_name,
            "case_id": case_id,
            "success": success,
            "user_id": user_id,
            "latency_ms": latency_ms,
            "error": error
        }
        
        self._log_event(event)
    
    def log_classification(
        self,
        query: str,
        classification_result: Dict[str, Any],
        case_id: Optional[str] = None,
        user_id: Optional[str] = None
    ):
        """
        Логировать классификацию запроса
        
        Args:
            query: Запрос пользователя
            classification_result: Результат классификации
            case_id: Идентификатор дела
            user_id: Идентификатор пользователя
        """
        event = {
            "event_type": AuditEventType.CLASSIFICATION.value,
            "timestamp": datetime.utcnow().isoformat(),
            "query": query[:200],
            "classification": classification_result,
            "case_id": case_id,
            "user_id": user_id
        }
        
        self._log_event(event)
    
    def log_middleware(
        self,
        middleware_name: str,
        action: str,
        case_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Логировать действие middleware
        
        Args:
            middleware_name: Имя middleware
            action: Действие (before_execution, after_execution, on_error)
            case_id: Идентификатор дела
            metadata: Дополнительные метаданные
        """
        event = {
            "event_type": AuditEventType.MIDDLEWARE.value,
            "timestamp": datetime.utcnow().isoformat(),
            "middleware_name": middleware_name,
            "action": action,
            "case_id": case_id,
            "metadata": metadata or {}
        }
        
        self._log_event(event)
    
    def _sanitize_args(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Очистить аргументы от чувствительных данных
        
        Args:
            args: Исходные аргументы
            
        Returns:
            Очищенные аргументы
        """
        sanitized = {}
        sensitive_keys = ['password', 'token', 'api_key', 'secret', 'runtime']
        
        for key, value in args.items():
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_args(value)
            elif isinstance(value, str) and len(value) > 500:
                sanitized[key] = value[:500] + "..."
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _log_event(self, event: Dict[str, Any]):
        """
        Записать событие в лог
        
        Args:
            event: Событие для логирования
        """
        try:
            event_json = json.dumps(event, ensure_ascii=False, default=str)
            self._audit_logger.info(event_json)
            logger.debug(f"Audit event logged: {event.get('event_type')}")
        except Exception as e:
            logger.error(f"Failed to log audit event: {e}", exc_info=True)


# Глобальный экземпляр audit logger
_audit_logger_instance: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """
    Получить глобальный экземпляр AuditLogger
    
    Returns:
        AuditLogger instance
    """
    global _audit_logger_instance
    if _audit_logger_instance is None:
        _audit_logger_instance = AuditLogger()
    return _audit_logger_instance

