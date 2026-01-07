"""Store Helper for saving large results to Store instead of state"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.store_integration import get_store_instance, save_to_store, load_from_store
import json
import logging

logger = logging.getLogger(__name__)

# Пороговые значения для сохранения в Store
SIZE_THRESHOLD_KB = 10  # >10KB → Store
ELEMENT_COUNT_THRESHOLD = 100  # >100 элементов → Store


def get_result_size_kb(data: Any) -> float:
    """
    Вычислить размер результата в KB
    
    Args:
        data: Данные для измерения
    
    Returns:
        Размер в KB
    """
    try:
        if isinstance(data, dict):
            json_str = json.dumps(data, ensure_ascii=False)
        elif isinstance(data, list):
            json_str = json.dumps(data, ensure_ascii=False)
        else:
            json_str = str(data)
        
        size_bytes = len(json_str.encode('utf-8'))
        return size_bytes / 1024.0
    except Exception as e:
        logger.warning(f"Error calculating result size: {e}")
        return 0.0


def get_result_summary(data: Any, max_summary_length: int = 500) -> Dict[str, Any]:
    """
    Создать краткую сводку результата для state
    
    Args:
        data: Полные данные
        max_summary_length: Максимальная длина сводки
    
    Returns:
        Словарь с краткой сводкой
    """
    summary = {
        "stored_in_store": True,
        "timestamp": None
    }
    
    try:
        if isinstance(data, dict):
            # Извлечь ключевые поля
            if "events" in data and isinstance(data["events"], list):
                summary["event_count"] = len(data["events"])
                if data["events"]:
                    summary["first_event"] = str(data["events"][0])[:200]
                    summary["last_event"] = str(data["events"][-1])[:200]
            
            elif "entities" in data and isinstance(data["entities"], list):
                summary["entity_count"] = len(data["entities"])
                if data["entities"]:
                    summary["sample_entities"] = [str(e) for e in data["entities"][:3]]
            
            elif "discrepancies" in data and isinstance(data["discrepancies"], list):
                summary["discrepancy_count"] = len(data["discrepancies"])
                if data["discrepancies"]:
                    summary["sample_discrepancies"] = [str(d) for d in data["discrepancies"][:3]]
            
            elif "risks" in data and isinstance(data["risks"], list):
                summary["risk_count"] = len(data["risks"])
                if data["risks"]:
                    summary["sample_risks"] = [str(r) for r in data["risks"][:3]]
            
            elif "facts" in data and isinstance(data["facts"], list):
                summary["fact_count"] = len(data["facts"])
                if data["facts"]:
                    summary["sample_facts"] = [str(f) for f in data["facts"][:3]]
            
            # Общая информация
            summary["keys"] = list(data.keys())[:10]  # Первые 10 ключей
            
        elif isinstance(data, list):
            summary["item_count"] = len(data)
            if data:
                summary["sample_items"] = [str(item) for item in data[:3]]
        
        # Добавить timestamp
        from datetime import datetime
        summary["timestamp"] = datetime.utcnow().isoformat()
        
    except Exception as e:
        logger.warning(f"Error creating result summary: {e}")
        summary["error"] = str(e)
    
    return summary


def should_store_result(data: Any) -> bool:
    """
    Определить, нужно ли сохранять результат в Store
    
    Args:
        data: Данные для проверки
    
    Returns:
        True если нужно сохранить в Store
    """
    # Проверка размера
    size_kb = get_result_size_kb(data)
    if size_kb > SIZE_THRESHOLD_KB:
        return True
    
    # Проверка количества элементов
    if isinstance(data, dict):
        # Проверяем вложенные списки
        for key, value in data.items():
            if isinstance(value, list) and len(value) > ELEMENT_COUNT_THRESHOLD:
                return True
    elif isinstance(data, list):
        if len(data) > ELEMENT_COUNT_THRESHOLD:
            return True
    
    return False


def save_large_result_to_store(
    state: AnalysisState,
    result_key: str,
    data: Any,
    case_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Сохранить большие данные в Store и вернуть ссылку
    
    Args:
        state: Состояние анализа
        result_key: Ключ результата (например, "timeline_result")
        data: Данные для сохранения
        case_id: ID дела (опционально, извлекается из state если не указан)
    
    Returns:
        Словарь с ссылкой на данные в Store и summary
    """
    if not case_id:
        case_id = state.get("case_id", "unknown")
    
    store = get_store_instance()
    if not store:
        logger.warning("Store not available, storing in state anyway")
        return {
            "store_available": False,
            "stored_in_state": True
        }
    
    # Создать namespace и key
    namespace = f"agent_results/{case_id}"
    key = f"{result_key}_{case_id}"
    
    # Сохранить в Store
    try:
        # Преобразовать в JSON-совместимый формат
        if isinstance(data, dict):
            data_to_store = data
        elif isinstance(data, list):
            data_to_store = {"items": data}
        else:
            data_to_store = {"value": data}
        
        # Сохранить через store_integration
        saved = save_to_store(store, namespace, key, data_to_store, case_id)
        
        if not saved:
            logger.warning(f"Failed to save {result_key} to store, storing in state")
            return {
                "store_available": True,
                "stored_in_store": False,
                "stored_in_state": True
            }
        
        # Создать summary
        summary = get_result_summary(data)
        
        # Вернуть ссылку
        return {
            "store_available": True,
            "stored_in_store": True,
            "namespace": namespace,
            "key": key,
            "summary": summary
        }
        
    except Exception as e:
        logger.error(f"Error saving {result_key} to store: {e}", exc_info=True)
        return {
            "store_available": True,
            "stored_in_store": False,
            "error": str(e),
            "stored_in_state": True
        }


def load_large_result_from_store(
    state: AnalysisState,
    result_key: str,
    case_id: Optional[str] = None
) -> Optional[Any]:
    """
    Загрузить большие данные из Store по ссылке
    
    Args:
        state: Состояние анализа
        result_key: Ключ результата (например, "timeline_result")
        case_id: ID дела (опционально, извлекается из state если не указан)
    
    Returns:
        Загруженные данные или None если не найдены
    """
    if not case_id:
        case_id = state.get("case_id", "unknown")
    
    # Проверить наличие ссылки в state
    ref_key = f"{result_key}_ref"
    ref = state.get(ref_key)
    
    if not ref or not ref.get("stored_in_store"):
        # Данные не в Store, попробовать загрузить из state напрямую
        return state.get(result_key)
    
    store = get_store_instance()
    if not store:
        logger.warning("Store not available, cannot load result")
        return None
    
    namespace = ref.get("namespace") or f"agent_results/{case_id}"
    key = ref.get("key") or f"{result_key}_{case_id}"
    
    try:
        data = load_from_store(store, namespace, key, case_id)
        if data:
            logger.debug(f"Loaded {result_key} from store: {namespace}/{key}")
            # Если данные были обернуты, распаковать
            if isinstance(data, dict) and "items" in data and len(data) == 1:
                return data["items"]
            elif isinstance(data, dict) and "value" in data and len(data) == 1:
                return data["value"]
            return data
        else:
            logger.warning(f"Result not found in store: {namespace}/{key}")
            return None
    except Exception as e:
        logger.error(f"Error loading {result_key} from store: {e}", exc_info=True)
        return None






