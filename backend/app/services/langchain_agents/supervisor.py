"""Supervisor agent for LangGraph multi-agent system"""
from typing import Dict, Any
from app.services.yandex_llm import ChatYandexGPT
from app.services.langchain_agents.agent_factory import create_legal_agent
from langchain_core.tools import Tool
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.prompts import get_agent_prompt
import logging

logger = logging.getLogger(__name__)


def create_handoff_tool(agent_name: str) -> Tool:
    """Create a handoff tool for routing to a specific agent"""
    return Tool(
        name=f"handoff_to_{agent_name}",
        func=lambda x: f"Handing off to {agent_name} agent",
        description=f"Transfer control to the {agent_name} agent to handle this task"
    )


def create_supervisor_agent() -> Any:
    """
    Create supervisor agent that routes tasks to specialized agents
    
    Returns:
        Supervisor agent instance
    """
    # Create handoff tools for each agent (все агенты)
    handoff_tools = [
        create_handoff_tool("document_classifier"),
        create_handoff_tool("privilege_check"),
        create_handoff_tool("entity_extraction"),
        create_handoff_tool("timeline"),
        create_handoff_tool("key_facts"),
        create_handoff_tool("discrepancy"),
        create_handoff_tool("risk"),
        create_handoff_tool("summary"),
        create_handoff_tool("relationship"),
    ]
    
    # Initialize LLM with temperature=0 for deterministic routing
    # Только YandexGPT, без fallback
    if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN) or not config.YANDEX_FOLDER_ID:
        raise ValueError("YANDEX_API_KEY/YANDEX_IAM_TOKEN и YANDEX_FOLDER_ID должны быть настроены")
    
    llm = ChatYandexGPT(
        model=config.YANDEX_GPT_MODEL or "yandexgpt-lite",
        temperature=0.1,  # Низкая температура для детерминизма
    )
    
    # Get supervisor prompt
    prompt = get_agent_prompt("supervisor")
    
    # Create supervisor agent
    supervisor = create_legal_agent(llm, handoff_tools, system_prompt=prompt)
    
    return supervisor


def route_to_agent(state: AnalysisState) -> str:
    """
    Route function that determines which agent should handle the next task
    
    Работает как "бригадир" - координирует работу специализированных агентов
    с reasoning и логированием решений.
    
    Учитывает:
    - Результаты evaluation (needs_replanning, confidence)
    - Адаптации плана (current_plan)
    - Human feedback (waiting_for_human)
    
    Args:
        state: Current graph state
    
    Returns:
        Name of the next agent to execute, or "end" if done
    """
    # Check if waiting for human feedback
    if state.get("waiting_for_human", False):
        current_request = state.get("current_feedback_request")
        if current_request:
            request_id = current_request.get("request_id")
            feedback_responses = state.get("feedback_responses", {})
            if request_id not in feedback_responses:
                # Still waiting, return to human_feedback_wait
                logger.info(f"[Супервизор] Дело {case_id}: Ожидание human feedback для запроса {request_id}")
                return "human_feedback_wait"
    
    # Check if we have an adapted plan
    current_plan = state.get("current_plan", [])
    needs_replanning = state.get("needs_replanning", False)
    
    # Use current_plan if available and needs_replanning is True
    if current_plan and needs_replanning:
        # Find next pending step in adapted plan
        from app.services.langchain_agents.state import PlanStepStatus
        completed_steps = set(state.get("completed_steps", []))
        
        for step in current_plan:
            step_id = step.get("step_id")
            step_status = step.get("status")
            agent_name = step.get("agent_name")
            
            if step_status == PlanStepStatus.PENDING.value and step_id not in completed_steps:
                logger.info(f"[Супервизор] Using adapted plan: next step is {agent_name} (step_id: {step_id})")
                return agent_name
        
        # All steps in plan completed, reset needs_replanning
        new_state = dict(state)
        new_state["needs_replanning"] = False
        state.update(new_state)
    
    # Fall back to original analysis_types
    analysis_types = state.get("analysis_types", [])
    requested_types = set(analysis_types)
    case_id = state.get("case_id", "unknown")
    
    # Check evaluation results for retry needs
    evaluation_result = state.get("evaluation_result", {})
    if evaluation_result.get("needs_retry", False):
        agent_name = evaluation_result.get("agent_name")
        if agent_name:
            logger.info(f"[Супервизор] Retrying agent {agent_name} based on evaluation")
            return agent_name
    
    # Check what's already done
    completed = set()
    if state.get("timeline_result"):
        completed.add("timeline")
    if state.get("key_facts_result"):
        completed.add("key_facts")
    if state.get("discrepancy_result"):
        completed.add("discrepancy")
    if state.get("risk_result"):
        completed.add("risk")
    if state.get("summary_result"):
        completed.add("summary")
    if state.get("classification_result"):
        completed.add("document_classifier")
    if state.get("entities_result"):
        completed.add("entity_extraction")
    if state.get("privilege_result"):
        completed.add("privilege_check")
    if state.get("relationship_result"):
        completed.add("relationship")
    
    # Check dependencies
    entities_ready = state.get("entities_result") is not None
    discrepancy_ready = state.get("discrepancy_result") is not None
    key_facts_ready = state.get("key_facts_result") is not None
    classification_ready = state.get("classification_result") is not None
    
    # Determine next agent with reasoning (как бригадир объясняет решение)
    reasoning_parts = []
    next_agent = None
    
    # Priority order (как описал пользователь):
    # 1. Document classifier (должен запуститься первым - "Что за документ?")
    if "document_classifier" in requested_types and "document_classifier" not in completed:
        reasoning_parts.append("Классификатор должен запуститься первым, чтобы понять тип документов")
        next_agent = "document_classifier"
        logger.info(f"[Супервизор] Дело {case_id}: → Классификатор: 'Что за документ?'")
    
    # 2. Privilege check (если классификация показала потенциальную привилегию)
    elif "privilege_check" in requested_types and "privilege_check" not in completed:
        if classification_ready:
            classification = state.get("classification_result", {})
            classifications = classification.get("classifications", [])
            has_potential_privilege = any(c.get("is_privileged", False) for c in classifications)
            if has_potential_privilege:
                privileged_count = len([c for c in classifications if c.get("is_privileged", False)])
                reasoning_parts.append(f"Классификатор нашел {privileged_count} потенциально привилегированных документов → проверяем привилегию")
                next_agent = "privilege_check"
                logger.info(f"[Супервизор] Дело {case_id}: Классификатор нашел привилегированные → Привилегир: 'Проверяю на адвокатскую тайну'")
        # Также запускаем если явно запрошено
        if next_agent is None and "privilege_check" in requested_types:
            reasoning_parts.append("Явно запрошена проверка привилегий")
            next_agent = "privilege_check"
            logger.info(f"[Супервизор] Дело {case_id}: → Привилегир: 'Проверяю привилегию'")
    
    # 3. Entity extraction (независимый, может работать параллельно - "Найди людей и даты")
    elif "entity_extraction" in requested_types and "entity_extraction" not in completed:
        reasoning_parts.append("Энтити-Экстрактор может работать параллельно, извлекая сущности")
        next_agent = "entity_extraction"
        logger.info(f"[Супервизор] Дело {case_id}: → Энтити-Экстрактор: 'Найди людей, даты, суммы'")
    
    # 4. Relationship extraction (требует entities - строит граф связей)
    elif "relationship" in requested_types and "relationship" not in completed:
        if entities_ready:
            reasoning_parts.append("Энтити готовы → строим граф связей между участниками")
            next_agent = "relationship"
            logger.info(f"[Супервизор] Дело {case_id}: Энтити готовы → Relationship: 'Строю граф связей'")
        else:
            # Wait for entities
            reasoning_parts.append("Relationship требует entities, ждем...")
            next_agent = "entity_extraction" if "entity_extraction" in requested_types else "supervisor"
    
    # 4. Независимые агенты могут работать параллельно
    # Check if we have multiple independent agents to run
    independent_agents = ["timeline", "key_facts", "discrepancy", "entity_extraction"]
    pending_independent = [
        agent for agent in independent_agents
        if agent in requested_types and agent not in completed
    ]
    
    if len(pending_independent) > 1:
        # Multiple independent agents - use parallel execution
        reasoning_parts.append(f"Найдено {len(pending_independent)} независимых агентов для параллельного выполнения: {', '.join(pending_independent)}")
        next_agent = "parallel_independent"
        logger.info(f"[Супервизор] Дело {case_id}: → Параллельное выполнение {len(pending_independent)} агентов")
    elif len(pending_independent) == 1:
        # Single independent agent - run directly
        agent_name = pending_independent[0]
        reasoning_parts.append(f"{agent_name} агент независим, выполняется отдельно")
        next_agent = agent_name
        logger.info(f"[Супервизор] Дело {case_id}: → {agent_name}: выполняется отдельно")
    elif "timeline" in requested_types and "timeline" not in completed:
        reasoning_parts.append("Timeline агент независим, может работать параллельно")
        next_agent = "timeline"
        logger.info(f"[Супервизор] Дело {case_id}: → Timeline: 'Извлекаю события'")
    elif "key_facts" in requested_types and "key_facts" not in completed:
        reasoning_parts.append("Key Facts агент независим, может работать параллельно")
        next_agent = "key_facts"
        logger.info(f"[Супервизор] Дело {case_id}: → Key Facts: 'Извлекаю ключевые факты'")
    elif "discrepancy" in requested_types and "discrepancy" not in completed:
        reasoning_parts.append("Discrepancy агент независим, может работать параллельно")
        next_agent = "discrepancy"
        logger.info(f"[Супервизор] Дело {case_id}: → Discrepancy: 'Ищу противоречия'")
    
    # 5. Зависимые агенты (требуют результаты других)
    elif "risk" in requested_types and "risk" not in completed:
        if discrepancy_ready:
            reasoning_parts.append("Discrepancy готов → Risk агент может анализировать риски")
            next_agent = "risk"
            logger.info(f"[Супервизор] Дело {case_id}: Discrepancy готов → Risk: 'Анализирую риски'")
        else:
            reasoning_parts.append("Risk требует Discrepancy, ждем...")
            next_agent = "supervisor"  # Ждем
    elif "summary" in requested_types and "summary" not in completed:
        if key_facts_ready:
            reasoning_parts.append("Key Facts готов → Summary агент может создать резюме")
            next_agent = "summary"
            logger.info(f"[Супервизор] Дело {case_id}: Key Facts готов → Summary: 'Создаю резюме'")
        else:
            reasoning_parts.append("Summary требует Key Facts, ждем...")
            next_agent = "supervisor"  # Ждем
    
    # Все готово
    elif requested_types.issubset(completed):
        reasoning_parts.append("Все запрошенные анализы завершены")
        next_agent = "end"
        logger.info(f"[Супервизор] Дело {case_id}: ✅ Все анализы завершены!")
    
    # Если зависимости не готовы, ждем
    else:
        reasoning_parts.append("Ожидание готовности зависимостей...")
        next_agent = "supervisor"
    
    # Сохраняем reasoning в метаданные для аудита
    if "metadata" not in state:
        state["metadata"] = {}
    if "supervisor_reasoning" not in state["metadata"]:
        state["metadata"]["supervisor_reasoning"] = []
    state["metadata"]["supervisor_reasoning"].append({
        "step": len(state["metadata"]["supervisor_reasoning"]) + 1,
        "reasoning": " | ".join(reasoning_parts) if reasoning_parts else "Определение следующего агента",
        "next_agent": next_agent,
        "completed": list(completed),
        "requested": list(requested_types)
    })
    
    return next_agent if next_agent else "supervisor"
