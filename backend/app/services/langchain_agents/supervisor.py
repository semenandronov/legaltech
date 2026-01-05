"""Supervisor agent for LangGraph multi-agent system"""
from typing import Dict, Any
from app.services.llm_factory import create_llm, create_llm_for_agent
from app.services.langchain_agents.agent_factory import create_legal_agent
from langchain_core.tools import Tool
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.langchain_agents.graph_optimizer import (
    optimize_route_function,
    AgentPriorities,
    get_next_agent_with_priorities
)
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
    
    # Initialize LLM через factory (GigaChat)
    llm = create_llm(temperature=0.1)  # Низкая температура для детерминизма
    
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
    - Human feedback (обрабатывается через LangGraph interrupts автоматически)
    
    Оптимизация: использует Rule-based Router для простых случаев (60-80%),
    LLM supervisor только для сложных случаев.
    
    Args:
        state: Current graph state
    
    Returns:
        Name of the next agent to execute, or "end" if done
    """
    # Note: Human feedback is now handled via LangGraph interrupts
    # Interrupts pause execution automatically, no need to check here
    
    case_id = state.get("case_id", "unknown")
    
    # Оптимизация: сначала попробовать Rule-based Router (быстро и бесплатно)
    from app.services.langchain_agents.rule_based_router import get_rule_router
    from app.services.langchain_agents.route_cache import get_route_cache
    
    # Проверить кэш маршрутизации
    route_cache = get_route_cache()
    cached_route = route_cache.get(state)
    if cached_route:
        logger.debug(f"[Супервизор] {case_id}: Cache hit → {cached_route}")
        return cached_route
    
    # Попробовать Rule-based Router
    rule_router = get_rule_router()
    rule_route = rule_router.route(state)
    
    if rule_route:
        # Сохранить в кэш
        route_cache.set(state, rule_route)
        logger.info(f"[Супервизор] {case_id}: Rule-based → {rule_route}")
        return rule_route
    
    # Fallback к LLM supervisor для сложных случаев
    logger.debug(f"[Супервизор] {case_id}: Rule-based router не смог определить, используем LLM supervisor")
    
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
    
    # Check if we have subtasks to execute (from AdvancedPlanningAgent)
    subtasks = state.get("subtasks", [])
    if subtasks:
        # Check if subagents have been spawned
        subagent_results = state.get("subagent_results")
        if not subagent_results:
            # Need to spawn subagents
            logger.info(f"[Супервизор] Routing to spawn_subagents for {len(subtasks)} subtasks")
            return "spawn_subagents"
        else:
            # Subagents already executed, check if all completed
            completed_subtasks = state.get("subtasks_completed", 0)
            if completed_subtasks < len(subtasks):
                # Some subtasks still pending, continue with regular agents
                logger.info(f"[Супервизор] {completed_subtasks}/{len(subtasks)} subtasks completed, continuing with regular agents")
            else:
                # All subtasks completed, can proceed to evaluation
                logger.info(f"[Супервизор] All {len(subtasks)} subtasks completed")
    
    # Check if deep analysis is needed (LEGORA workflow)
    understanding_result = state.get("understanding_result", {})
    complexity = understanding_result.get("complexity", "medium")
    task_type = understanding_result.get("task_type", "general")
    
    # Check if deep analysis should be used
    needs_deep_analysis = (
        complexity == "high" and
        task_type in ["research", "analysis", "comparison"] and
        not state.get("deep_analysis_result")
    )
    
    if needs_deep_analysis:
        logger.info(f"[Супервизор] Routing to deep_analysis for complex task (complexity={complexity}, type={task_type})")
        return "deep_analysis"
    
    # Fall back to original analysis_types для LLM supervisor
    analysis_types = state.get("analysis_types", [])
    requested_types = set(analysis_types)
    
    # Check evaluation results for retry needs
    evaluation_result = state.get("evaluation_result")
    if evaluation_result and evaluation_result.get("needs_retry", False):
        agent_name = evaluation_result.get("agent_name")
        if agent_name:
            logger.info(f"[Супервизор] Retrying agent {agent_name} based on evaluation")
            # Сохранить в кэш
            route_cache.set(state, agent_name)
            return agent_name
    
    # LLM Supervisor для сложных случаев (используем GigaChat Lite для простых случаев)
    from app.services.langchain_agents.model_selector import get_model_selector
    model_selector = get_model_selector()
    
    # Определить сложность для выбора модели supervisor
    understanding_result = state.get("understanding_result", {})
    complexity = understanding_result.get("complexity", "medium")
    analysis_types_count = len(analysis_types)
    
    # Простой случай → Lite, сложный → Pro
    use_lite = complexity == "simple" and analysis_types_count <= 2
    supervisor_model = model_selector.select_model_for_supervisor(state, use_llm=True)
    
    # Создать supervisor agent с выбранной моделью
    supervisor_llm = create_llm(model=supervisor_model, temperature=0.1)
    supervisor = create_supervisor_agent()
    # Заменить LLM в supervisor (если возможно)
    if hasattr(supervisor, 'llm'):
        supervisor.llm = supervisor_llm
    
    logger.info(f"[Супервизор] {case_id}: Using LLM supervisor (model: {supervisor_model}) for complex routing")
    
    # Вызвать LLM supervisor (старая логика как fallback)
    # Simplified check for completed agents and dependencies
    result_keys = {
        "timeline": "timeline_result",
        "key_facts": "key_facts_result",
        "discrepancy": "discrepancy_result",
        "risk": "risk_result",
        "summary": "summary_result",
        "document_classifier": "classification_result",
        "entity_extraction": "entities_result",
        "privilege_check": "privilege_result",
        "relationship": "relationship_result",
        "deep_analysis": "deep_analysis_result"
    }
    
    # Проверить также ссылки в Store
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
    
    # Build completed set and dependency flags in one pass
    completed = {agent for agent, key in result_keys.items() if state.get(key) is not None}
    # Добавить завершенные по ссылкам в Store
    for agent, ref_key in ref_keys.items():
        if state.get(ref_key) is not None:
            completed.add(agent)
    
    # Dependency readiness flags
    entities_ready = "entity_extraction" in completed
    discrepancy_ready = "discrepancy" in completed
    key_facts_ready = "key_facts" in completed
    classification_ready = "document_classifier" in completed
    
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
            classification = state.get("classification_result") or state.get("classification_ref")
            if classification:
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
    
    # Simplified routing logic: independent vs dependent agents
    INDEPENDENT_AGENTS = {"timeline", "key_facts", "discrepancy", "entity_extraction", "document_classifier"}
    DEPENDENT_AGENTS = {
        "risk": {"discrepancy"},
        "summary": {"key_facts"},
        "relationship": {"entity_extraction"}
    }
    
    # Find pending independent agents
    pending_independent = [
        agent for agent in INDEPENDENT_AGENTS
        if agent in requested_types and agent not in completed
    ]
    
    # Find ready dependent agents (dependencies satisfied)
    pending_dependent_ready = [
        agent for agent, deps in DEPENDENT_AGENTS.items()
        if agent in requested_types and agent not in completed
        and all(dep in completed for dep in deps)
    ]
    
    # Routing priority:
    # 1. Multiple independent agents → parallel execution
    if len(pending_independent) >= 2:
        reasoning_parts.append(f"{len(pending_independent)} независимых агентов → параллельное выполнение")
        next_agent = "parallel_independent"
        logger.info(f"[Супервизор] {case_id}: → Параллельно {len(pending_independent)} агентов")
    # 2. Single independent agent → run directly
    elif len(pending_independent) == 1:
        next_agent = pending_independent[0]
        reasoning_parts.append(f"{next_agent} независим → выполняется отдельно")
        logger.info(f"[Супервизор] {case_id}: → {next_agent}")
    # 3. Ready dependent agents → run in priority order
    elif pending_dependent_ready:
        # Use priority order from graph_optimizer
        from app.services.langchain_agents.graph_optimizer import AgentPriorities
        sorted_dependent = AgentPriorities.sort_by_priority(pending_dependent_ready)
        next_agent = sorted_dependent[0]
        reasoning_parts.append(f"{next_agent} готов (зависимости выполнены)")
        logger.info(f"[Супервизор] {case_id}: → {next_agent} (зависимости готовы)")
    # 4. Check individual dependent agents (fallback)
    elif "risk" in requested_types and "risk" not in completed:
        if discrepancy_ready:
            next_agent = "risk"
            reasoning_parts.append("Risk готов к выполнению")
            logger.info(f"[Супервизор] {case_id}: → Risk")
        else:
            next_agent = "supervisor"  # Wait
    elif "summary" in requested_types and "summary" not in completed:
        if key_facts_ready:
            next_agent = "summary"
            reasoning_parts.append("Summary готов к выполнению")
            logger.info(f"[Супервизор] {case_id}: → Summary")
        else:
            next_agent = "supervisor"  # Wait
    
    # Все готово
    elif requested_types.issubset(completed):
        reasoning_parts.append("Все запрошенные анализы завершены")
        next_agent = "end"
        logger.info(f"[Супервизор] Дело {case_id}: ✅ Все анализы завершены!")
    
    # Если зависимости не готовы, ждем
    else:
        reasoning_parts.append("Ожидание готовности зависимостей...")
        next_agent = "supervisor"
    
    # Сохранить решение в кэш
    if next_agent:
        route_cache.set(state, next_agent)
    
    # Сохраняем reasoning в метаданные для аудита
    if "metadata" not in state:
        state["metadata"] = {}
    if "supervisor_reasoning" not in state["metadata"]:
        state["metadata"]["supervisor_reasoning"] = []
    state["metadata"]["supervisor_reasoning"].append({
        "step": len(state["metadata"]["supervisor_reasoning"]) + 1,
        "reasoning": " | ".join(reasoning_parts) if reasoning_parts else "LLM supervisor decision",
        "next_agent": next_agent,
        "completed": list(completed),
        "requested": list(requested_types),
        "model_used": supervisor_model,
        "routing_method": "llm_supervisor"
    })
    
    return next_agent if next_agent else "supervisor"
