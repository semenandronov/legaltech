"""
Error Handling - Централизованная обработка ошибок

Предоставляет:
- Типизированные исключения
- Error codes для frontend
- Детальные сообщения для пользователей
- Logging и трекинг ошибок
"""
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
import traceback
import logging
import uuid

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# =============================================================================
# Error Codes
# =============================================================================

class ErrorCode(str, Enum):
    """Коды ошибок для frontend"""
    
    # Authentication & Authorization
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
    
    # Validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    
    # Resources
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    
    # Business Logic
    NO_DOCUMENTS_IN_CASE = "NO_DOCUMENTS_IN_CASE"
    DOCUMENT_PROCESSING_FAILED = "DOCUMENT_PROCESSING_FAILED"
    ANALYSIS_FAILED = "ANALYSIS_FAILED"
    PLAN_CREATION_FAILED = "PLAN_CREATION_FAILED"
    
    # External Services
    LLM_ERROR = "LLM_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    GARANT_ERROR = "GARANT_ERROR"
    RAG_ERROR = "RAG_ERROR"
    
    # Rate Limiting
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    
    # Server Errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    DATABASE_ERROR = "DATABASE_ERROR"


# =============================================================================
# Error Messages (Russian)
# =============================================================================

ERROR_MESSAGES: Dict[ErrorCode, str] = {
    ErrorCode.AUTH_REQUIRED: "Требуется авторизация",
    ErrorCode.AUTH_INVALID_TOKEN: "Недействительный токен авторизации",
    ErrorCode.AUTH_TOKEN_EXPIRED: "Срок действия токена истёк",
    ErrorCode.AUTH_FORBIDDEN: "Доступ запрещён",
    
    ErrorCode.VALIDATION_ERROR: "Ошибка валидации данных",
    ErrorCode.INVALID_INPUT: "Некорректные входные данные",
    ErrorCode.MISSING_REQUIRED_FIELD: "Отсутствует обязательное поле",
    
    ErrorCode.RESOURCE_NOT_FOUND: "Ресурс не найден",
    ErrorCode.CASE_NOT_FOUND: "Дело не найдено",
    ErrorCode.DOCUMENT_NOT_FOUND: "Документ не найден",
    ErrorCode.FILE_NOT_FOUND: "Файл не найден",
    
    ErrorCode.NO_DOCUMENTS_IN_CASE: "В деле нет загруженных документов",
    ErrorCode.DOCUMENT_PROCESSING_FAILED: "Ошибка обработки документа",
    ErrorCode.ANALYSIS_FAILED: "Ошибка анализа",
    ErrorCode.PLAN_CREATION_FAILED: "Не удалось создать план анализа",
    
    ErrorCode.LLM_ERROR: "Ошибка языковой модели",
    ErrorCode.LLM_TIMEOUT: "Превышено время ожидания ответа от ИИ",
    ErrorCode.GARANT_ERROR: "Ошибка сервиса ГАРАНТ",
    ErrorCode.RAG_ERROR: "Ошибка поиска в документах",
    
    ErrorCode.RATE_LIMIT_EXCEEDED: "Превышен лимит запросов",
    
    ErrorCode.INTERNAL_ERROR: "Внутренняя ошибка сервера",
    ErrorCode.SERVICE_UNAVAILABLE: "Сервис временно недоступен",
    ErrorCode.DATABASE_ERROR: "Ошибка базы данных",
}


# =============================================================================
# Base Application Exception
# =============================================================================

class AppException(Exception):
    """
    Базовое исключение приложения
    
    Все бизнес-исключения должны наследоваться от него.
    """
    
    def __init__(
        self,
        code: ErrorCode,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 400,
        original_error: Optional[Exception] = None
    ):
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, str(code))
        self.details = details or {}
        self.status_code = status_code
        self.original_error = original_error
        self.error_id = str(uuid.uuid4())[:8]  # Короткий ID для логов
        self.timestamp = datetime.utcnow()
        
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь для ответа"""
        return {
            "error": {
                "code": self.code.value,
                "message": self.message,
                "details": self.details,
                "error_id": self.error_id,
                "timestamp": self.timestamp.isoformat()
            }
        }
    
    def log(self) -> None:
        """Залогировать ошибку"""
        log_data = {
            "error_id": self.error_id,
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }
        
        if self.original_error:
            log_data["original_error"] = str(self.original_error)
            log_data["traceback"] = traceback.format_exc()
        
        if self.status_code >= 500:
            logger.error(f"AppException: {log_data}")
        else:
            logger.warning(f"AppException: {log_data}")


# =============================================================================
# Specific Exceptions
# =============================================================================

class AuthenticationError(AppException):
    """Ошибка аутентификации"""
    def __init__(self, code: ErrorCode = ErrorCode.AUTH_REQUIRED, **kwargs):
        super().__init__(code=code, status_code=401, **kwargs)


class AuthorizationError(AppException):
    """Ошибка авторизации"""
    def __init__(self, message: str = None, **kwargs):
        super().__init__(
            code=ErrorCode.AUTH_FORBIDDEN,
            message=message,
            status_code=403,
            **kwargs
        )


class ValidationError(AppException):
    """Ошибка валидации"""
    def __init__(self, message: str = None, field: str = None, **kwargs):
        details = kwargs.pop("details", {})
        if field:
            details["field"] = field
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            details=details,
            status_code=400,
            **kwargs
        )


class ResourceNotFoundError(AppException):
    """Ресурс не найден"""
    def __init__(
        self,
        resource_type: str = "resource",
        resource_id: str = None,
        code: ErrorCode = ErrorCode.RESOURCE_NOT_FOUND,
        **kwargs
    ):
        details = {"resource_type": resource_type}
        if resource_id:
            details["resource_id"] = resource_id
        
        message = kwargs.pop("message", None)
        if not message:
            message = f"{resource_type.title()} не найден"
            if resource_id:
                message += f" (ID: {resource_id})"
        
        super().__init__(
            code=code,
            message=message,
            details=details,
            status_code=404,
            **kwargs
        )


class CaseNotFoundError(ResourceNotFoundError):
    """Дело не найдено"""
    def __init__(self, case_id: str = None, **kwargs):
        super().__init__(
            resource_type="case",
            resource_id=case_id,
            code=ErrorCode.CASE_NOT_FOUND,
            **kwargs
        )


class DocumentNotFoundError(ResourceNotFoundError):
    """Документ не найден"""
    def __init__(self, document_id: str = None, **kwargs):
        super().__init__(
            resource_type="document",
            resource_id=document_id,
            code=ErrorCode.DOCUMENT_NOT_FOUND,
            **kwargs
        )


class NoDocumentsError(AppException):
    """В деле нет документов"""
    def __init__(self, case_id: str = None, **kwargs):
        details = {}
        if case_id:
            details["case_id"] = case_id
        super().__init__(
            code=ErrorCode.NO_DOCUMENTS_IN_CASE,
            details=details,
            status_code=400,
            **kwargs
        )


class LLMError(AppException):
    """Ошибка LLM"""
    def __init__(
        self,
        message: str = None,
        code: ErrorCode = ErrorCode.LLM_ERROR,
        **kwargs
    ):
        super().__init__(
            code=code,
            message=message,
            status_code=503,
            **kwargs
        )


class ExternalServiceError(AppException):
    """Ошибка внешнего сервиса"""
    def __init__(
        self,
        service_name: str,
        message: str = None,
        code: ErrorCode = ErrorCode.SERVICE_UNAVAILABLE,
        **kwargs
    ):
        details = kwargs.pop("details", {})
        details["service"] = service_name
        
        super().__init__(
            code=code,
            message=message or f"Сервис {service_name} временно недоступен",
            details=details,
            status_code=503,
            **kwargs
        )


class RateLimitError(AppException):
    """Превышен лимит запросов"""
    def __init__(self, retry_after: int = 60, **kwargs):
        details = {"retry_after": retry_after}
        super().__init__(
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            details=details,
            status_code=429,
            **kwargs
        )


# =============================================================================
# Error Response Model
# =============================================================================

class ErrorDetail(BaseModel):
    """Модель детали ошибки"""
    code: str
    message: str
    details: Dict[str, Any] = {}
    error_id: str
    timestamp: str


class ErrorResponse(BaseModel):
    """Модель ответа с ошибкой"""
    error: ErrorDetail


# =============================================================================
# Exception Handlers for FastAPI
# =============================================================================

async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Обработчик AppException"""
    exc.log()
    
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict()
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Обработчик HTTPException"""
    error_id = str(uuid.uuid4())[:8]
    
    # Маппинг HTTP статусов на ErrorCode
    code_mapping = {
        401: ErrorCode.AUTH_REQUIRED,
        403: ErrorCode.AUTH_FORBIDDEN,
        404: ErrorCode.RESOURCE_NOT_FOUND,
        429: ErrorCode.RATE_LIMIT_EXCEEDED,
    }
    
    code = code_mapping.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code.value,
                "message": str(exc.detail),
                "details": {},
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Обработчик всех остальных исключений"""
    error_id = str(uuid.uuid4())[:8]
    
    logger.error(
        f"Unhandled exception [{error_id}]: {exc}",
        exc_info=True,
        extra={
            "error_id": error_id,
            "path": request.url.path,
            "method": request.method
        }
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": "Произошла внутренняя ошибка сервера",
                "details": {"error_id": error_id},
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
    )


def register_exception_handlers(app):
    """Зарегистрировать обработчики исключений в FastAPI приложении"""
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

