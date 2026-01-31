"""
Trustcall интеграция для обновления memory schemas.

Trustcall обеспечивает:
- Надёжное извлечение JSON из ответов LLM
- Валидацию по Pydantic схемам
- JSON Patch для инкрементальных обновлений
- Обработку ошибок парсинга

# ИСПОЛЬЗОВАНИЕ
```python
from app.services.langchain_agents.memory.trustcall import (
    TrustcallExtractor,
    extract_and_validate,
    update_with_patch,
)

# Извлечение с валидацией
extractor = TrustcallExtractor(UserProfile)
profile = await extractor.extract(llm_response)

# Обновление через patch
updated = await update_with_patch(
    current=profile,
    new_info="Пользователь работает юристом",
    schema=UserProfile
)
```
"""
from typing import TypeVar, Type, Optional, List, Dict, Any, Union
from pydantic import BaseModel, ValidationError
from datetime import datetime
import logging
import json
import re

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class TrustcallError(Exception):
    """Ошибка извлечения или валидации."""
    pass


class TrustcallExtractor:
    """
    Извлекатель структурированных данных из текста LLM.
    
    Реализует паттерн Trustcall:
    1. Извлечение JSON из текста (с поддержкой markdown code blocks)
    2. Валидация по Pydantic схеме
    3. Повторные попытки при ошибках
    4. JSON Patch для частичных обновлений
    """
    
    def __init__(
        self,
        schema: Type[T],
        max_retries: int = 2,
        strict: bool = False
    ):
        """
        Args:
            schema: Pydantic модель для валидации
            max_retries: Максимальное количество повторных попыток
            strict: Строгий режим (ошибка при missing fields)
        """
        self.schema = schema
        self.max_retries = max_retries
        self.strict = strict
    
    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Извлечь JSON из текста.
        
        Поддерживает:
        - Чистый JSON
        - JSON в markdown code blocks
        - JSON с комментариями
        """
        # Пробуем найти JSON в code blocks
        code_block_patterns = [
            r'```json\s*([\s\S]*?)\s*```',
            r'```\s*([\s\S]*?)\s*```',
            r'`([\s\S]*?)`'
        ]
        
        for pattern in code_block_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue
        
        # Пробуем найти JSON напрямую
        json_patterns = [
            r'\{[\s\S]*\}',  # Object
            r'\[[\s\S]*\]'   # Array
        ]
        
        for pattern in json_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue
        
        return None
    
    def _validate(self, data: Dict[str, Any]) -> T:
        """Валидировать данные по схеме."""
        try:
            return self.schema(**data)
        except ValidationError as e:
            if self.strict:
                raise TrustcallError(f"Validation error: {e}")
            
            # В нестрогом режиме пробуем исправить
            logger.warning(f"[Trustcall] Validation warning: {e}")
            
            # Удаляем невалидные поля
            valid_fields = set(self.schema.model_fields.keys())
            cleaned_data = {k: v for k, v in data.items() if k in valid_fields}
            
            return self.schema(**cleaned_data)
    
    async def extract(
        self,
        text: str,
        llm=None,
        context: Optional[str] = None
    ) -> T:
        """
        Извлечь и валидировать данные из текста.
        
        Args:
            text: Текст для парсинга
            llm: LLM для повторных попыток (опционально)
            context: Дополнительный контекст для LLM
        
        Returns:
            Валидированный объект схемы
        
        Raises:
            TrustcallError: При неудачном извлечении
        """
        # Первая попытка
        data = self._extract_json(text)
        
        if data:
            try:
                return self._validate(data)
            except TrustcallError:
                pass
        
        # Повторные попытки с LLM
        if llm and self.max_retries > 0:
            for attempt in range(self.max_retries):
                logger.info(f"[Trustcall] Retry attempt {attempt + 1}")
                
                retry_prompt = f"""Предыдущий ответ не удалось распарсить как JSON.

Исходный текст:
{text[:500]}

Ожидаемая схема:
{json.dumps(self.schema.model_json_schema(), indent=2, ensure_ascii=False)}

Пожалуйста, верни ТОЛЬКО валидный JSON без дополнительного текста."""

                try:
                    response = llm.invoke(retry_prompt)
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    
                    data = self._extract_json(response_text)
                    if data:
                        return self._validate(data)
                except Exception as e:
                    logger.warning(f"[Trustcall] Retry {attempt + 1} failed: {e}")
        
        raise TrustcallError(f"Failed to extract valid JSON from text")
    
    def extract_sync(self, text: str) -> T:
        """Синхронная версия extract (без retry через LLM)."""
        data = self._extract_json(text)
        
        if data:
            return self._validate(data)
        
        raise TrustcallError(f"Failed to extract valid JSON from text")


class JsonPatch:
    """
    JSON Patch операции для инкрементального обновления.
    
    Поддерживает операции:
    - add: Добавить значение
    - remove: Удалить значение
    - replace: Заменить значение
    - merge: Объединить объекты
    """
    
    @staticmethod
    def apply(
        target: Dict[str, Any],
        patch: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Применить patch к целевому объекту.
        
        Args:
            target: Целевой объект
            patch: Список операций
        
        Returns:
            Обновлённый объект
        """
        result = dict(target)
        
        for op in patch:
            operation = op.get("op")
            path = op.get("path", "").strip("/").split("/")
            value = op.get("value")
            
            if not path or path == [""]:
                continue
            
            if operation == "add":
                JsonPatch._set_nested(result, path, value)
            
            elif operation == "remove":
                JsonPatch._remove_nested(result, path)
            
            elif operation == "replace":
                JsonPatch._set_nested(result, path, value)
            
            elif operation == "merge":
                current = JsonPatch._get_nested(result, path)
                if isinstance(current, dict) and isinstance(value, dict):
                    merged = {**current, **value}
                    JsonPatch._set_nested(result, path, merged)
                elif isinstance(current, list) and isinstance(value, list):
                    merged = current + [v for v in value if v not in current]
                    JsonPatch._set_nested(result, path, merged)
                else:
                    JsonPatch._set_nested(result, path, value)
        
        return result
    
    @staticmethod
    def _get_nested(obj: Dict, path: List[str]) -> Any:
        """Получить значение по пути."""
        current = obj
        for key in path:
            if isinstance(current, dict):
                current = current.get(key)
            elif isinstance(current, list) and key.isdigit():
                idx = int(key)
                current = current[idx] if idx < len(current) else None
            else:
                return None
        return current
    
    @staticmethod
    def _set_nested(obj: Dict, path: List[str], value: Any):
        """Установить значение по пути."""
        current = obj
        for key in path[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        final_key = path[-1]
        if isinstance(current, dict):
            current[final_key] = value
        elif isinstance(current, list) and final_key.isdigit():
            idx = int(final_key)
            if idx < len(current):
                current[idx] = value
            else:
                current.append(value)
    
    @staticmethod
    def _remove_nested(obj: Dict, path: List[str]):
        """Удалить значение по пути."""
        current = obj
        for key in path[:-1]:
            if key not in current:
                return
            current = current[key]
        
        final_key = path[-1]
        if isinstance(current, dict) and final_key in current:
            del current[final_key]
        elif isinstance(current, list) and final_key.isdigit():
            idx = int(final_key)
            if idx < len(current):
                current.pop(idx)


async def extract_and_validate(
    text: str,
    schema: Type[T],
    llm=None,
    strict: bool = False
) -> T:
    """
    Извлечь и валидировать данные из текста.
    
    Удобная функция-обёртка над TrustcallExtractor.
    
    Args:
        text: Текст для парсинга
        schema: Pydantic схема
        llm: LLM для повторных попыток
        strict: Строгий режим валидации
    
    Returns:
        Валидированный объект
    """
    extractor = TrustcallExtractor(schema, strict=strict)
    return await extractor.extract(text, llm)


async def update_with_patch(
    current: T,
    new_info: str,
    schema: Type[T],
    llm=None
) -> T:
    """
    Обновить объект через JSON Patch.
    
    Использует LLM для генерации patch операций.
    
    Args:
        current: Текущий объект
        new_info: Новая информация
        schema: Pydantic схема
        llm: LLM instance
    
    Returns:
        Обновлённый объект
    """
    if not llm:
        from app.services.llm_factory import create_llm
        llm = create_llm()
    
    prompt = f"""# ЗАДАЧА
Сгенерируй JSON Patch операции для обновления объекта.

# ТЕКУЩИЙ ОБЪЕКТ
{current.model_dump_json(indent=2)}

# НОВАЯ ИНФОРМАЦИЯ
{new_info}

# ИНСТРУКЦИИ
1. Определи, какие поля нужно обновить
2. Сгенерируй patch операции
3. НЕ удаляй существующую информацию без причины
4. Используй "merge" для списков и объектов

# ФОРМАТ ОТВЕТА (JSON)
{{
    "patch": [
        {{"op": "replace", "path": "/field_name", "value": "new_value"}},
        {{"op": "merge", "path": "/nested/field", "value": {{"key": "value"}}}},
        {{"op": "add", "path": "/list_field/-", "value": "new_item"}}
    ]
}}

Операции:
- replace: заменить значение
- add: добавить значение (/-  для добавления в конец списка)
- remove: удалить значение
- merge: объединить объекты/списки"""

    try:
        response = llm.invoke(prompt)
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # Извлекаем patch
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            result = json.loads(json_match.group())
            patch = result.get("patch", [])
            
            # Применяем patch
            current_dict = current.model_dump()
            updated_dict = JsonPatch.apply(current_dict, patch)
            
            # Обновляем timestamp
            if "updated_at" in schema.model_fields:
                updated_dict["updated_at"] = datetime.utcnow().isoformat()
            
            # Валидируем и возвращаем
            return schema(**updated_dict)
    
    except Exception as e:
        logger.error(f"[Trustcall] Patch update error: {e}")
    
    # Fallback: возвращаем без изменений
    return current


def generate_extraction_prompt(
    schema: Type[BaseModel],
    context: str,
    instructions: Optional[str] = None
) -> str:
    """
    Сгенерировать промпт для извлечения данных.
    
    Args:
        schema: Pydantic схема
        context: Контекст для извлечения
        instructions: Дополнительные инструкции
    
    Returns:
        Промпт для LLM
    """
    schema_json = json.dumps(schema.model_json_schema(), indent=2, ensure_ascii=False)
    
    prompt = f"""# ЗАДАЧА
Извлеки структурированные данные из текста.

# КОНТЕКСТ
{context}

# ОЖИДАЕМАЯ СХЕМА
{schema_json}

# ИНСТРУКЦИИ
{instructions or "Извлеки все релевантные данные из контекста."}

# ФОРМАТ ОТВЕТА
Верни ТОЛЬКО валидный JSON, соответствующий схеме.
НЕ добавляй комментарии или пояснения."""

    return prompt

