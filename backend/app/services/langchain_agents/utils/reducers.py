"""
Кастомные редьюсеры для LangGraph состояний.

Редьюсеры определяют, как обновляется состояние при получении новых данных.
Используются с Annotated типами в TypedDict состояниях.

Пример использования:
```python
from typing import TypedDict, Annotated
from app.services.langchain_agents.utils.reducers import merge_dicts_reducer

class MyState(TypedDict):
    results: Annotated[Dict[str, Any], merge_dicts_reducer]
```
"""
from typing import Dict, Any, List, Optional, Union, Sequence
import logging

logger = logging.getLogger(__name__)


def merge_dicts_reducer(
    existing: Optional[Dict[str, Any]], 
    new: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Редьюсер для объединения словарей.
    
    Объединяет существующий словарь с новым. При конфликте ключей
    новые значения перезаписывают старые.
    
    Args:
        existing: Существующий словарь (может быть None)
        new: Новый словарь для объединения (может быть None)
    
    Returns:
        Объединённый словарь
    
    Example:
        >>> merge_dicts_reducer({"a": 1}, {"b": 2})
        {"a": 1, "b": 2}
        >>> merge_dicts_reducer({"a": 1}, {"a": 2})
        {"a": 2}
    """
    if existing is None and new is None:
        return {}
    if existing is None:
        return dict(new) if new else {}
    if new is None:
        return dict(existing)
    
    result = dict(existing)
    result.update(new)
    return result


def merge_dicts_deep_reducer(
    existing: Optional[Dict[str, Any]], 
    new: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Редьюсер для глубокого объединения словарей.
    
    Рекурсивно объединяет вложенные словари вместо перезаписи.
    
    Args:
        existing: Существующий словарь
        new: Новый словарь
    
    Returns:
        Глубоко объединённый словарь
    """
    if existing is None and new is None:
        return {}
    if existing is None:
        return dict(new) if new else {}
    if new is None:
        return dict(existing)
    
    def deep_merge(d1: Dict, d2: Dict) -> Dict:
        result = dict(d1)
        for key, value in d2.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    return deep_merge(existing, new)


def append_unique_reducer(
    existing: Optional[List[Any]], 
    new: Optional[Union[List[Any], Any]]
) -> List[Any]:
    """
    Редьюсер для списков с проверкой уникальности.
    
    Добавляет элементы из нового списка, только если их ещё нет в существующем.
    Для словарей сравнивает по ключу 'id', если он есть.
    
    Args:
        existing: Существующий список
        new: Новый список или элемент для добавления
    
    Returns:
        Объединённый список без дубликатов
    
    Example:
        >>> append_unique_reducer([{"id": 1}], [{"id": 2}])
        [{"id": 1}, {"id": 2}]
        >>> append_unique_reducer([{"id": 1}], [{"id": 1}])
        [{"id": 1}]
    """
    if existing is None:
        existing = []
    if new is None:
        return list(existing)
    
    # Если new не список, оборачиваем
    if not isinstance(new, (list, tuple)):
        new = [new]
    
    result = list(existing)
    
    # Собираем существующие ID для быстрой проверки
    existing_ids = set()
    for item in existing:
        if isinstance(item, dict) and "id" in item:
            existing_ids.add(item["id"])
        elif isinstance(item, (str, int, float)):
            existing_ids.add(item)
    
    for item in new:
        if isinstance(item, dict) and "id" in item:
            if item["id"] not in existing_ids:
                result.append(item)
                existing_ids.add(item["id"])
        elif isinstance(item, (str, int, float)):
            if item not in existing_ids:
                result.append(item)
                existing_ids.add(item)
        else:
            # Для сложных объектов просто добавляем
            if item not in result:
                result.append(item)
    
    return result


def sort_by_confidence_reducer(
    existing: Optional[List[Dict[str, Any]]], 
    new: Optional[List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """
    Редьюсер для списков с сортировкой по уверенности.
    
    Объединяет списки и сортирует по убыванию поля 'confidence'.
    Дубликаты по 'id' удаляются, остаётся элемент с большей уверенностью.
    
    Args:
        existing: Существующий список
        new: Новый список
    
    Returns:
        Объединённый и отсортированный список
    
    Example:
        >>> sort_by_confidence_reducer(
        ...     [{"id": 1, "confidence": 0.5}],
        ...     [{"id": 1, "confidence": 0.9}, {"id": 2, "confidence": 0.7}]
        ... )
        [{"id": 1, "confidence": 0.9}, {"id": 2, "confidence": 0.7}]
    """
    if existing is None:
        existing = []
    if new is None:
        new = []
    
    # Объединяем, сохраняя элемент с большей уверенностью
    by_id: Dict[Any, Dict[str, Any]] = {}
    
    for item in existing + new:
        item_id = item.get("id")
        confidence = item.get("confidence", 0.0)
        
        if item_id is None:
            # Без ID - добавляем как есть
            by_id[id(item)] = item
        elif item_id not in by_id or confidence > by_id[item_id].get("confidence", 0.0):
            by_id[item_id] = item
    
    # Сортируем по убыванию confidence
    result = list(by_id.values())
    result.sort(key=lambda x: x.get("confidence", 0.0), reverse=True)
    
    return result


def append_errors_reducer(
    existing: Optional[List[str]], 
    new: Optional[Union[List[str], str]]
) -> Optional[List[str]]:
    """
    Редьюсер для списка ошибок.
    
    Добавляет новые ошибки к существующим. Возвращает None если ошибок нет.
    
    Args:
        existing: Существующий список ошибок
        new: Новые ошибки (список или строка)
    
    Returns:
        Объединённый список ошибок или None
    """
    if existing is None and new is None:
        return None
    
    result = list(existing) if existing else []
    
    if new is not None:
        if isinstance(new, str):
            result.append(new)
        elif isinstance(new, (list, tuple)):
            result.extend(new)
    
    return result if result else None


def merge_citations_reducer(
    existing: Optional[List[Dict[str, Any]]], 
    new: Optional[List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """
    Редьюсер для объединения цитат.
    
    Объединяет списки цитат, удаляя дубликаты по source + page.
    Перенумеровывает индексы.
    
    Args:
        existing: Существующий список цитат
        new: Новый список цитат
    
    Returns:
        Объединённый список цитат с уникальными индексами
    """
    if existing is None:
        existing = []
    if new is None:
        new = []
    
    # Собираем уникальные цитаты по source + page
    seen = set()
    result = []
    
    for citation in existing + new:
        source = citation.get("source", "")
        page = citation.get("page")
        key = (source, page)
        
        if key not in seen:
            seen.add(key)
            result.append(citation)
    
    # Перенумеровываем
    for i, citation in enumerate(result, 1):
        citation["index"] = i
    
    return result


def last_value_reducer(
    existing: Any, 
    new: Any
) -> Any:
    """
    Редьюсер, который всегда возвращает последнее значение.
    
    Полезен когда нужно просто перезаписать значение.
    
    Args:
        existing: Существующее значение (игнорируется)
        new: Новое значение
    
    Returns:
        Новое значение
    """
    return new


def max_value_reducer(
    existing: Optional[Union[int, float]], 
    new: Optional[Union[int, float]]
) -> Optional[Union[int, float]]:
    """
    Редьюсер, который сохраняет максимальное значение.
    
    Args:
        existing: Существующее значение
        new: Новое значение
    
    Returns:
        Максимальное из двух значений
    """
    if existing is None:
        return new
    if new is None:
        return existing
    return max(existing, new)


def min_value_reducer(
    existing: Optional[Union[int, float]], 
    new: Optional[Union[int, float]]
) -> Optional[Union[int, float]]:
    """
    Редьюсер, который сохраняет минимальное значение.
    
    Args:
        existing: Существующее значение
        new: Новое значение
    
    Returns:
        Минимальное из двух значений
    """
    if existing is None:
        return new
    if new is None:
        return existing
    return min(existing, new)


def count_reducer(
    existing: Optional[int], 
    new: Optional[int]
) -> int:
    """
    Редьюсер для подсчёта (сумма значений).
    
    Args:
        existing: Существующее значение
        new: Новое значение для добавления
    
    Returns:
        Сумма значений
    """
    return (existing or 0) + (new or 0)

