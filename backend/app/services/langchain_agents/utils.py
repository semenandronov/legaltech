"""
Утилиты для langchain_agents.

Содержит общие функции, используемые агентами и графами.
"""
from typing import Dict, Any, Optional
import json
import re
import logging

logger = logging.getLogger(__name__)


def extract_json_from_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Извлечь JSON из ответа LLM.
    
    Args:
        response_text: Текст ответа LLM
    
    Returns:
        Распарсенный JSON или None
    """
    if not response_text:
        return None
    
    # Пробуем найти JSON в markdown блоке
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Пробуем найти JSON напрямую
    try:
        # Ищем первый { и последний }
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_str = response_text[start:end + 1]
            return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    
    # Пробуем найти массив JSON
    try:
        start = response_text.find('[')
        end = response_text.rfind(']')
        if start != -1 and end != -1 and end > start:
            json_str = response_text[start:end + 1]
            return {"items": json.loads(json_str)}
    except json.JSONDecodeError:
        pass
    
    return None


"""
Интеграции с внешними правовыми платформами удалены.
Для СПРАВОЧНИКА используйте `app.services.legal_corpus_service`.
"""
