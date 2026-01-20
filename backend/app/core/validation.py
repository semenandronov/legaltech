"""
Input Validation - Валидация входных данных

Предоставляет:
- Валидаторы для chat requests
- Санитизация пользовательского ввода
- Проверки безопасности
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
import re
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Максимальные размеры
MAX_QUESTION_LENGTH = 10000
MAX_DOCUMENT_CONTEXT_LENGTH = 100000
MAX_SELECTED_TEXT_LENGTH = 5000
MAX_TEMPLATE_CONTENT_LENGTH = 500000
MAX_MESSAGES_COUNT = 100
MAX_ATTACHED_FILES = 10

# Паттерны для санитизации
DANGEROUS_PATTERNS = [
    r'<script[^>]*>.*?</script>',  # Script tags
    r'javascript:',  # JavaScript URLs
    r'on\w+\s*=',  # Event handlers
    r'data:text/html',  # Data URLs with HTML
]


# =============================================================================
# Validation Models
# =============================================================================

class MessageInput(BaseModel):
    """Валидированное сообщение"""
    role: str = Field(..., pattern=r'^(user|assistant|system)$')
    content: str = Field(..., min_length=1, max_length=MAX_QUESTION_LENGTH)
    
    @field_validator('content')
    @classmethod
    def sanitize_content(cls, v):
        """Санитизировать контент"""
        return sanitize_input(v)


class ChatRequestInput(BaseModel):
    """Валидированный запрос к чату"""
    messages: List[MessageInput] = Field(..., min_items=1, max_items=MAX_MESSAGES_COUNT)
    case_id: str = Field(..., min_length=1, max_length=100)
    
    # Режимы (boolean)
    web_search: bool = False
    legal_research: bool = False
    deep_think: bool = False
    draft_mode: bool = False
    
    # Контекст редактора
    document_context: Optional[str] = Field(None, max_length=MAX_DOCUMENT_CONTEXT_LENGTH)
    document_id: Optional[str] = Field(None, max_length=100)
    selected_text: Optional[str] = Field(None, max_length=MAX_SELECTED_TEXT_LENGTH)
    
    # Шаблон для draft mode
    template_file_id: Optional[str] = Field(None, max_length=100)
    template_file_content: Optional[str] = Field(None, max_length=MAX_TEMPLATE_CONTENT_LENGTH)
    
    # Прикреплённые файлы
    attached_file_ids: Optional[List[str]] = Field(None, max_items=MAX_ATTACHED_FILES)
    
    @field_validator('case_id')
    @classmethod
    def validate_case_id(cls, v):
        """Валидировать case_id"""
        # Должен быть UUID или alphanumeric
        if not re.match(r'^[a-zA-Z0-9\-_]+$', v):
            raise ValueError('Invalid case_id format')
        return v
    
    @field_validator('document_context')
    @classmethod
    def sanitize_document_context(cls, v):
        """Санитизировать контекст документа"""
        if v:
            return sanitize_html(v)
        return v
    
    @field_validator('template_file_content')
    @classmethod
    def sanitize_template_content(cls, v):
        """Санитизировать контент шаблона"""
        if v:
            return sanitize_html(v)
        return v
    
    @model_validator(mode='before')
    @classmethod
    def validate_request(cls, values):
        """Валидировать запрос целиком"""
        messages = values.get('messages', [])
        
        # Последнее сообщение должно быть от user
        if messages and messages[-1].role != 'user':
            raise ValueError('Last message must be from user')
        
        # draft_mode требует либо template_file_id, либо просто вопрос
        draft_mode = values.get('draft_mode', False)
        if draft_mode:
            # OK - draft mode может работать без шаблона
            pass
        
        # document_context требует document_id
        document_context = values.get('document_context')
        document_id = values.get('document_id')
        if document_context and not document_id:
            logger.warning("document_context provided without document_id")
        
        return values
    
    def get_question(self) -> str:
        """Получить вопрос (последнее сообщение от user)"""
        for msg in reversed(self.messages):
            if msg.role == 'user':
                return msg.content
        return ""


# =============================================================================
# Sanitization Functions
# =============================================================================

def sanitize_input(text: str) -> str:
    """
    Базовая санитизация текстового ввода
    
    - Удаляет опасные паттерны
    - Нормализует пробелы
    - Обрезает до максимальной длины
    """
    if not text:
        return text
    
    # Удаляем опасные паттерны
    for pattern in DANGEROUS_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
    
    # Нормализуем пробелы (но сохраняем переносы строк)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    # Удаляем null bytes
    text = text.replace('\x00', '')
    
    return text.strip()


def sanitize_html(html: str) -> str:
    """
    Санитизация HTML контента
    
    Удаляет:
    - Script теги
    - Event handlers
    - Опасные URLs
    """
    if not html:
        return html
    
    # Удаляем script теги
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.IGNORECASE | re.DOTALL)
    
    # Удаляем event handlers
    html = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', '', html, flags=re.IGNORECASE)
    html = re.sub(r'\s+on\w+\s*=\s*\S+', '', html, flags=re.IGNORECASE)
    
    # Удаляем javascript: URLs
    html = re.sub(r'href\s*=\s*["\']javascript:[^"\']*["\']', 'href="#"', html, flags=re.IGNORECASE)
    html = re.sub(r'src\s*=\s*["\']javascript:[^"\']*["\']', 'src=""', html, flags=re.IGNORECASE)
    
    # Удаляем data: URLs с HTML
    html = re.sub(r'(href|src)\s*=\s*["\']data:text/html[^"\']*["\']', r'\1=""', html, flags=re.IGNORECASE)
    
    return html


def validate_uuid(value: str) -> bool:
    """Проверить, является ли строка валидным UUID"""
    uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    return bool(re.match(uuid_pattern, value.lower()))


def validate_file_extension(filename: str, allowed_extensions: List[str]) -> bool:
    """Проверить расширение файла"""
    if not filename:
        return False
    
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return ext in [e.lower().lstrip('.') for e in allowed_extensions]


# =============================================================================
# Validation Decorator
# =============================================================================

def validate_request(model_class):
    """
    Декоратор для валидации request body
    
    Пример:
    ```python
    @router.post("/api/chat")
    @validate_request(ChatRequestInput)
    async def chat(request: Request, validated: ChatRequestInput):
        ...
    ```
    """
    from functools import wraps
    from fastapi import Request, HTTPException
    
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            try:
                body = await request.json()
                validated = model_class(**body)
                return await func(request, validated=validated, *args, **kwargs)
            except Exception as e:
                logger.warning(f"Validation error: {e}")
                raise HTTPException(
                    status_code=422,
                    detail=f"Validation error: {str(e)}"
                )
        return wrapper
    return decorator


# =============================================================================
# Security Checks
# =============================================================================

def check_injection_attempt(text: str) -> bool:
    """
    Проверить на попытку injection
    
    Returns:
        True если обнаружена попытка injection
    """
    injection_patterns = [
        r';\s*DROP\s+TABLE',  # SQL injection
        r'UNION\s+SELECT',  # SQL injection
        r'\{\{.*\}\}',  # Template injection
        r'\$\{.*\}',  # Template injection
        r'__import__',  # Python injection
        r'eval\s*\(',  # Code injection
        r'exec\s*\(',  # Code injection
    ]
    
    for pattern in injection_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Potential injection attempt detected: {pattern}")
            return True
    
    return False


def check_prompt_injection(text: str) -> bool:
    """
    Проверить на попытку prompt injection
    
    Returns:
        True если обнаружена попытка prompt injection
    """
    prompt_injection_patterns = [
        r'ignore\s+(all\s+)?previous\s+instructions',
        r'disregard\s+(all\s+)?previous',
        r'forget\s+(all\s+)?previous',
        r'you\s+are\s+now\s+(?!a\s+legal)',  # "you are now X" (except legal assistant)
        r'new\s+system\s+prompt',
        r'override\s+system',
    ]
    
    for pattern in prompt_injection_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"Potential prompt injection attempt detected: {pattern}")
            return True
    
    return False

