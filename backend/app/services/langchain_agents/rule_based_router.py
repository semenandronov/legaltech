"""Rule-based Router for fast routing decisions without LLM"""
from typing import Optional, Set, Dict, Any
from app.services.langchain_agents.state import AnalysisState
import logging

logger = logging.getLogger(__name__)

# Зависимости между агентами
DEPENDENT_AGENTS = {
    "risk": {"discrepancy"},
    "summary": {"key_facts"},
    "relationship": {"entity_extraction"}
}

# Независимые агенты (могут выполняться параллельно)
INDEPENDENT_AGENTS = {
    "document_classifier",
    "entity_extraction",
    "timeline",
    "key_facts",
    "discrepancy",
    "privilege_check"
}


class RuleBasedRouter:
    """
    Rule-based router для быстрой маршрутизации без LLM
    
    Обрабатывает 60-80% простых случаев маршрутизации:
    - Прямое соответствие analysis_types → agent
    - Проверка зависимостей
    - Определение параллельного выполнения
    
    Возвращает None если не может определить → fallback к LLM supervisor
    """
    
    def __init__(self):
        self.enabled = True
    
    def route(
        self,
        state: AnalysisState
    ) -> Optional[str]:
        """
        Определить следующий агент на основе правил
        
        Args:
            state: Состояние анализа
        
        Returns:
            Имя следующего агента или None если нужен LLM supervisor
        """
        if not self.enabled:
            return None
        
        case_id = state.get("case_id", "unknown")
        analysis_types = state.get("analysis_types", [])
        requested_types = set(analysis_types)
        
        # Проверка завершенных агентов
        result_keys = {
            "timeline": "timeline_result",
            "key_facts": "key_facts_result",
            "discrepancy": "discrepancy_result",
            "risk": "risk_result",
            "summary": "summary_result",
            "document_classifier": "classification_result",
            "entity_extraction": "entities_result",
            "privilege_check": "privilege_result",
            "relationship": "relationship_result"
        }
        
        # Проверка ссылок в Store (если результат в Store)
        ref_keys = {
            "timeline": "timeline_ref",
            "key_facts": "key_facts_ref",
            "discrepancy": "discrepancy_ref",
            "risk": "risk_ref",
            "summary": "summary_ref",
            "document_classifier": "classification_ref",
            "entity_extraction": "entities_ref",
            "privilege_check": "privilege_ref",
            "relationship": "relationship_ref"
        }
        
        # Построить множество завершенных агентов
        completed = set()
        for agent, result_key in result_keys.items():
            if state.get(result_key) is not None:
                completed.add(agent)
        
        # Проверить ссылки в Store
        for agent, ref_key in ref_keys.items():
            if state.get(ref_key) is not None:
                completed.add(agent)
        
        # Правило 1: document_classifier всегда первым (если запрошен)
        if "document_classifier" in requested_types and "document_classifier" not in completed:
            logger.debug(f"[RuleRouter] {case_id}: → document_classifier (priority rule)")
            return "document_classifier"
        
        # Правило 2: privilege_check после document_classifier (если найдены привилегированные)
        if "privilege_check" in requested_types and "privilege_check" not in completed:
            classification = state.get("classification_result") or state.get("classification_ref")
            if classification:
                classifications = classification.get("classifications", [])
                has_privilege = any(c.get("is_privileged", False) for c in classifications)
                if has_privilege:
                    logger.debug(f"[RuleRouter] {case_id}: → privilege_check (found privileged docs)")
                    return "privilege_check"
        
        # Правило 3: Найти незавершенные независимые агенты
        pending_independent = [
            agent for agent in INDEPENDENT_AGENTS
            if agent in requested_types and agent not in completed
        ]
        
        # Правило 4: Если ≥2 независимых агента → parallel_independent
        if len(pending_independent) >= 2:
            logger.debug(f"[RuleRouter] {case_id}: → parallel_independent ({len(pending_independent)} agents)")
            return "parallel_independent"
        
        # Правило 5: Один независимый агент → выполнить напрямую
        if len(pending_independent) == 1:
            agent = pending_independent[0]
            logger.debug(f"[RuleRouter] {case_id}: → {agent} (single independent)")
            return agent
        
        # Правило 6: Проверка зависимых агентов
        pending_dependent_ready = []
        for agent, deps in DEPENDENT_AGENTS.items():
            if agent in requested_types and agent not in completed:
                # Проверить готовность всех зависимостей
                deps_ready = all(dep in completed for dep in deps)
                if deps_ready:
                    pending_dependent_ready.append(agent)
        
        # Правило 7: Приоритет зависимых агентов (risk > summary > relationship)
        if pending_dependent_ready:
            priority_order = ["risk", "summary", "relationship"]
            for agent in priority_order:
                if agent in pending_dependent_ready:
                    logger.debug(f"[RuleRouter] {case_id}: → {agent} (dependencies ready)")
                    return agent
        
        # Правило 8: Все завершено → end
        if requested_types.issubset(completed):
            logger.debug(f"[RuleRouter] {case_id}: → end (all completed)")
            return "end"
        
        # Правило 9: Ожидание зависимостей → supervisor (ждем)
        # Проверить, есть ли зависимые агенты, которые ждут
        waiting_dependent = []
        for agent, deps in DEPENDENT_AGENTS.items():
            if agent in requested_types and agent not in completed:
                deps_ready = all(dep in completed for dep in deps)
                if not deps_ready:
                    waiting_dependent.append(agent)
        
        if waiting_dependent:
            missing_deps = []
            for agent in waiting_dependent:
                deps = DEPENDENT_AGENTS[agent]
                missing = [d for d in deps if d not in completed]
                missing_deps.extend(missing)
            
            if missing_deps:
                logger.debug(f"[RuleRouter] {case_id}: → supervisor (waiting for: {set(missing_deps)})")
                return "supervisor"
        
        # Правило 10: Не удалось определить → None (fallback к LLM supervisor)
        logger.debug(f"[RuleRouter] {case_id}: → None (complex case, need LLM supervisor)")
        return None
    
    def can_handle(self, state: AnalysisState) -> bool:
        """
        Проверить, может ли router обработать этот случай
        
        Args:
            state: Состояние анализа
        
        Returns:
            True если router может обработать, False если нужен LLM
        """
        result = self.route(state)
        return result is not None


# Глобальный экземпляр
_rule_router = None


def get_rule_router() -> RuleBasedRouter:
    """Получить глобальный экземпляр RuleBasedRouter"""
    global _rule_router
    if _rule_router is None:
        _rule_router = RuleBasedRouter()
    return _rule_router





























