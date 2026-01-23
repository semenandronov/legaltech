"""
Legacy stubs - заглушки для обратной совместимости.

Эти заглушки позволяют старому коду в routes работать,
пока идёт миграция на новую архитектуру.

TODO: Постепенно мигрировать routes на новую архитектуру и удалить этот файл.
"""
from typing import Dict, Any, Optional, List, AsyncIterator
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


# ============== AgentCoordinator Stub ==============

class AgentCoordinator:
    """Заглушка для AgentCoordinator."""
    
    def __init__(self, *args, **kwargs):
        logger.warning("[STUB] AgentCoordinator is deprecated. Use ChatGraphService instead.")
    
    async def run_analysis(self, *args, **kwargs) -> AsyncIterator[Dict[str, Any]]:
        """Заглушка для run_analysis."""
        yield {"type": "error", "message": "AgentCoordinator deprecated. Use new architecture."}


# ============== PlanningAgent Stub ==============

class PlanningAgent:
    """Заглушка для PlanningAgent."""
    
    def __init__(self, *args, **kwargs):
        logger.warning("[STUB] PlanningAgent is deprecated.")
    
    def create_plan(self, *args, **kwargs) -> Dict[str, Any]:
        return {"steps": [], "error": "PlanningAgent deprecated"}


# ============== AdvancedPlanningAgent Stub ==============

class AdvancedPlanningAgent:
    """Заглушка для AdvancedPlanningAgent."""
    
    def __init__(self, *args, **kwargs):
        logger.warning("[STUB] AdvancedPlanningAgent is deprecated.")
    
    def create_plan(self, *args, **kwargs) -> Dict[str, Any]:
        return {"steps": [], "error": "AdvancedPlanningAgent deprecated"}


# ============== PipelineService Stub ==============

class PipelineService:
    """Заглушка для PipelineService."""
    
    def __init__(self, *args, **kwargs):
        logger.warning("[STUB] PipelineService is deprecated.")
    
    def run(self, *args, **kwargs):
        return {"error": "PipelineService deprecated"}


# ============== ChatAgent Stub ==============

class ChatAgent:
    """Заглушка для ChatAgent."""
    
    def __init__(self, *args, **kwargs):
        logger.warning("[STUB] ChatAgent is deprecated. Use ChatReActAgent instead.")
    
    async def answer_stream(self, *args, **kwargs) -> AsyncIterator[str]:
        """Заглушка для answer_stream."""
        yield "ChatAgent deprecated. Используйте новую архитектуру."


# ============== AnalysisState Stub ==============

class AnalysisState(dict):
    """Заглушка для AnalysisState."""
    pass


# ============== Function Stubs ==============

def get_feedback_service(*args, **kwargs):
    """Заглушка для get_feedback_service."""
    logger.warning("[STUB] get_feedback_service is deprecated.")
    return None


def get_audit_logger(*args, **kwargs):
    """Заглушка для get_audit_logger."""
    logger.warning("[STUB] get_audit_logger is deprecated.")
    return None


def get_garant_source():
    """Заглушка для get_garant_source."""
    from app.services.langchain_agents.utils import get_garant_source as real_get_garant_source
    return real_get_garant_source()


def _garant_search_sync(*args, **kwargs):
    """Заглушка для _garant_search_sync."""
    logger.warning("[STUB] _garant_search_sync is deprecated.")
    return []


def list_workflow_templates(*args, **kwargs):
    """Заглушка для list_workflow_templates."""
    return []


def document_classifier_agent_node(*args, **kwargs):
    """Заглушка для document_classifier_agent_node."""
    return {"classification": "unknown", "error": "deprecated"}


def entity_extraction_agent_node(*args, **kwargs):
    """Заглушка для entity_extraction_agent_node."""
    return {"entities": [], "error": "deprecated"}


def privilege_check_agent_node(*args, **kwargs):
    """Заглушка для privilege_check_agent_node."""
    return {"privileges": [], "error": "deprecated"}


def deliver_node(*args, **kwargs):
    """Заглушка для deliver_node."""
    return {"error": "deprecated"}


class PlanningValidator:
    """Заглушка для PlanningValidator."""
    
    def __init__(self, *args, **kwargs):
        pass
    
    def validate(self, *args, **kwargs):
        return True


class MetricsCollector:
    """Заглушка для MetricsCollector."""
    
    def __init__(self, *args, **kwargs):
        pass
    
    def collect(self, *args, **kwargs):
        pass


# ============== AVAILABLE_ANALYSES ==============

AVAILABLE_ANALYSES = [
    {"id": "timeline", "name": "Хронология"},
    {"id": "key_facts", "name": "Ключевые факты"},
    {"id": "discrepancy", "name": "Противоречия"},
    {"id": "risk", "name": "Риски"},
    {"id": "summary", "name": "Резюме"},
]


# ============== Template Graph Stubs ==============

def create_template_graph(*args, **kwargs):
    """Заглушка для create_template_graph."""
    logger.warning("[STUB] create_template_graph is deprecated. Use draft_node in ChatGraph.")
    return None


class TemplateState(dict):
    """Заглушка для TemplateState."""
    pass

