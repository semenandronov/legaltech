"""Replanning agent for intelligent plan modification based on failures"""
from typing import Dict, Any, List, Optional
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent
from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.langchain_agents.state import AnalysisState, PlanStep, PlanStepStatus
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from langchain_core.messages import HumanMessage
import json
import logging
import uuid

logger = logging.getLogger(__name__)


class ReplanningAgent:
    """
    Agent that creates new plans based on failures and errors.
    
    Analyzes failure reasons and proposes alternative approaches:
    - Retry with modifications
    - Alternative approach
    - Simplify task
    - Decompose into subtasks
    - Skip and compensate
    """
    
    def __init__(
        self,
        rag_service: Optional[RAGService] = None,
        document_processor: Optional[DocumentProcessor] = None
    ):
        """Initialize replanning agent"""
        try:
            self.llm = create_llm(temperature=0.2)  # Slightly higher for creativity
            logger.info("✅ Using GigaChat for replanning")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            raise ValueError(f"Ошибка инициализации LLM: {str(e)}")
        
        self.rag_service = rag_service
        self.document_processor = document_processor
        
        # Get replanning prompt
        prompt = self._get_replanning_prompt()
        
        # Create agent (no tools needed for replanning, just reasoning)
        self.agent = create_legal_agent(self.llm, [], system_prompt=prompt)
        
        logger.info("Replanning Agent initialized")
    
    def replan(
        self,
        state: AnalysisState,
        failure_reason: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Creates a new plan based on failure analysis
        
        Args:
            state: Current analysis state
            failure_reason: Reason for failure
            context: Additional context (evaluation result, error details, etc.)
        
        Returns:
            New plan dictionary with strategy and steps
        """
        try:
            case_id = state.get("case_id", "unknown")
            logger.info(f"Replanning for case {case_id}, failure: {failure_reason[:100]}")
            
            # Analyze failure
            failure_analysis = self._analyze_failure(failure_reason, context, state)
            
            # Determine replanning strategy
            strategy = self._determine_strategy(failure_analysis, state)
            
            # Create new plan based on strategy
            new_plan = self._create_replan(strategy, failure_analysis, state)
            
            logger.info(
                f"Replanning completed: strategy={strategy}, "
                f"steps={len(new_plan.get('steps', []))}"
            )
            
            return new_plan
            
        except Exception as e:
            logger.error(f"Error in replanning: {e}", exc_info=True)
            return self._fallback_replan(state, failure_reason)
    
    def _analyze_failure(
        self,
        failure_reason: str,
        context: Dict[str, Any],
        state: AnalysisState
    ) -> Dict[str, Any]:
        """Analyzes failure to understand root cause"""
        analysis = {
            "failure_type": "unknown",
            "root_cause": failure_reason,
            "affected_agent": context.get("agent_name", "unknown"),
            "error_category": "unknown",
            "recoverable": True,
            "suggestions": []
        }
        
        failure_lower = failure_reason.lower()
        
        # Categorize failure
        if "timeout" in failure_lower or "timed out" in failure_lower:
            analysis["failure_type"] = "timeout"
            analysis["error_category"] = "performance"
            analysis["suggestions"].append("Упростить задачу или увеличить время выполнения")
            analysis["suggestions"].append("Разбить на более мелкие подзадачи")
        
        elif "error" in failure_lower or "exception" in failure_lower:
            analysis["failure_type"] = "error"
            analysis["error_category"] = "execution"
            analysis["suggestions"].append("Проверить входные данные")
            analysis["suggestions"].append("Использовать альтернативный подход")
        
        elif "no result" in failure_lower or "empty" in failure_lower:
            analysis["failure_type"] = "no_result"
            analysis["error_category"] = "data"
            analysis["suggestions"].append("Проверить наличие релевантных документов")
            analysis["suggestions"].append("Использовать более широкий поиск")
        
        elif "low confidence" in failure_lower or "confidence" in failure_lower:
            analysis["failure_type"] = "low_quality"
            analysis["error_category"] = "quality"
            analysis["suggestions"].append("Улучшить промпт или параметры")
            analysis["suggestions"].append("Повторить с дополнительным контекстом")
        
        elif "dependency" in failure_lower or "requires" in failure_lower:
            analysis["failure_type"] = "dependency"
            analysis["error_category"] = "planning"
            analysis["suggestions"].append("Выполнить зависимости сначала")
            analysis["suggestions"].append("Изменить порядок выполнения")
        
        else:
            analysis["failure_type"] = "unknown"
            analysis["suggestions"].append("Повторить попытку")
            analysis["suggestions"].append("Упростить задачу")
        
        # Check if recoverable
        if analysis["failure_type"] in ["timeout", "no_result", "low_quality"]:
            analysis["recoverable"] = True
        elif analysis["failure_type"] == "error":
            # Check if it's a recoverable error
            if any(keyword in failure_lower for keyword in ["network", "connection", "rate limit"]):
                analysis["recoverable"] = True
            else:
                analysis["recoverable"] = False
        
        return analysis
    
    def _determine_strategy(
        self,
        failure_analysis: Dict[str, Any],
        state: AnalysisState
    ) -> str:
        """Determines best replanning strategy"""
        failure_type = failure_analysis.get("failure_type", "unknown")
        recoverable = failure_analysis.get("recoverable", True)
        
        # Check retry count
        retry_count = state.get("metadata", {}).get("retry_count", {}).get(
            failure_analysis.get("affected_agent", ""), 0
        )
        
        if retry_count >= 2:
            # Already retried multiple times, try different strategy
            if failure_type == "timeout":
                return "simplify"
            elif failure_type == "no_result":
                return "alternative_approach"
            elif failure_type == "dependency":
                return "reorder"
            else:
                return "skip_and_compensate"
        
        if not recoverable:
            return "skip_and_compensate"
        
        if failure_type == "timeout":
            return "simplify"
        elif failure_type == "no_result":
            return "alternative_approach"
        elif failure_type == "dependency":
            return "reorder"
        elif failure_type == "low_quality":
            return "retry_with_modifications"
        else:
            return "retry_with_modifications"
    
    def _create_replan(
        self,
        strategy: str,
        failure_analysis: Dict[str, Any],
        state: AnalysisState
    ) -> Dict[str, Any]:
        """Creates new plan based on strategy"""
        case_id = state.get("case_id", "unknown")
        current_plan = state.get("current_plan", [])
        analysis_types = state.get("analysis_types", [])
        affected_agent = failure_analysis.get("affected_agent", "unknown")
        
        if strategy == "retry_with_modifications":
            return self._create_retry_plan(current_plan, affected_agent, failure_analysis)
        
        elif strategy == "alternative_approach":
            return self._create_alternative_plan(analysis_types, affected_agent, state)
        
        elif strategy == "simplify":
            return self._create_simplified_plan(current_plan, affected_agent, state)
        
        elif strategy == "decompose":
            return self._create_decomposed_plan(affected_agent, failure_analysis, state)
        
        elif strategy == "reorder":
            return self._create_reordered_plan(current_plan, state)
        
        elif strategy == "skip_and_compensate":
            return self._create_skip_plan(current_plan, affected_agent, state)
        
        else:
            # Fallback: retry
            return self._create_retry_plan(current_plan, affected_agent, failure_analysis)
    
    def _create_retry_plan(
        self,
        current_plan: List[Dict],
        affected_agent: str,
        failure_analysis: Dict
    ) -> Dict[str, Any]:
        """Creates plan to retry with modified parameters"""
        new_steps = []
        
        # Handle case where current_plan might be a dict with 'steps' key
        if isinstance(current_plan, dict):
            steps = current_plan.get("steps", [])
        elif isinstance(current_plan, list):
            steps = current_plan
        else:
            steps = []
        
        for step in steps:
            # Skip non-dict items (like string keys from dict iteration)
            if not isinstance(step, dict):
                continue
            if step.get("agent_name") == affected_agent and step.get("status") == PlanStepStatus.FAILED.value:
                # Modify step for retry
                retry_step = dict(step)
                retry_step["status"] = PlanStepStatus.PENDING.value
                retry_step["error"] = None
                
                # Modify parameters for retry
                params = retry_step.get("parameters", {})
                if "depth" in params:
                    params["depth"] = "standard"  # Simplify depth
                if "focus" in params:
                    params["focus"] = "all"  # Broaden focus
                retry_step["parameters"] = params
                retry_step["reasoning"] = f"Retry with modified parameters after: {failure_analysis.get('root_cause', '')[:100]}"
                
                new_steps.append(retry_step)
            else:
                new_steps.append(step)
        
        return {
            "strategy": "retry_with_modifications",
            "steps": new_steps,
            "analysis_types": [s.get("agent_name") for s in new_steps if s.get("agent_name")],
            "reasoning": f"Повторная попытка для {affected_agent} с модифицированными параметрами",
            "confidence": 0.7
        }
    
    def _create_alternative_plan(
        self,
        analysis_types: List[str],
        affected_agent: str,
        state: AnalysisState
    ) -> Dict[str, Any]:
        """Creates plan with alternative approach"""
        # Map to alternative agents
        alternatives = {
            "timeline": ["key_facts"],  # Can extract dates from key_facts
            "key_facts": ["entity_extraction"],  # Can use entities
            "discrepancy": ["risk"],  # Skip discrepancy, go straight to risk if possible
        }
        
        alternative_agents = alternatives.get(affected_agent, [])
        
        # Remove failed agent, add alternatives
        new_types = [t for t in analysis_types if t != affected_agent]
        new_types.extend(alternative_agents)
        new_types = list(dict.fromkeys(new_types))  # Remove duplicates
        
        # Create new steps
        new_steps = []
        for idx, agent_name in enumerate(new_types):
            step = {
                "step_id": f"{agent_name}_{uuid.uuid4().hex[:8]}",
                "agent_name": agent_name,
                "description": f"Execute {agent_name} analysis (alternative approach)",
                "status": PlanStepStatus.PENDING.value,
                "dependencies": AVAILABLE_ANALYSES.get(agent_name, {}).get("dependencies", []),
                "result_key": f"{agent_name}_result",
                "reasoning": f"Alternative approach instead of {affected_agent}",
                "parameters": {}
            }
            new_steps.append(step)
        
        return {
            "strategy": "alternative_approach",
            "steps": new_steps,
            "analysis_types": new_types,
            "reasoning": f"Использован альтернативный подход вместо {affected_agent}",
            "confidence": 0.6
        }
    
    def _create_simplified_plan(
        self,
        current_plan: List[Dict],
        affected_agent: str,
        state: AnalysisState
    ) -> Dict[str, Any]:
        """Creates simplified plan"""
        # Keep only essential steps
        essential_agents = ["document_classifier", "key_facts", "timeline"]
        
        new_steps = []
        for step in current_plan:
            agent_name = step.get("agent_name", "")
            if agent_name in essential_agents or step.get("status") == PlanStepStatus.COMPLETED.value:
                # Simplify parameters
                simplified_step = dict(step)
                params = simplified_step.get("parameters", {})
                params["depth"] = "standard"
                params["focus"] = "essential"
                simplified_step["parameters"] = params
                simplified_step["reasoning"] = "Упрощенная версия для надежного выполнения"
                new_steps.append(simplified_step)
        
        return {
            "strategy": "simplify",
            "steps": new_steps,
            "analysis_types": [s.get("agent_name") for s in new_steps if s.get("agent_name")],
            "reasoning": f"Упрощенный план после ошибки в {affected_agent}",
            "confidence": 0.7
        }
    
    def _create_decomposed_plan(
        self,
        affected_agent: str,
        failure_analysis: Dict,
        state: AnalysisState
    ) -> Dict[str, Any]:
        """Creates plan by decomposing failed task into subtasks"""
        # For now, decomposition is agent-specific
        # This is a placeholder for future implementation
        return self._create_simplified_plan(state.get("current_plan", []), affected_agent, state)
    
    def _create_reordered_plan(
        self,
        current_plan: List[Dict],
        state: AnalysisState
    ) -> Dict[str, Any]:
        """Creates plan with reordered steps"""
        # Separate by status
        completed = [s for s in current_plan if s.get("status") == PlanStepStatus.COMPLETED.value]
        pending = [s for s in current_plan if s.get("status") == PlanStepStatus.PENDING.value]
        failed = [s for s in current_plan if s.get("status") == PlanStepStatus.FAILED.value]
        
        # Reorder pending: independent first, then by dependencies
        independent = []
        dependent = []
        
        for step in pending:
            deps = step.get("dependencies", [])
            if not deps:
                independent.append(step)
            else:
                dependent.append(step)
        
        # Sort dependent by number of dependencies
        dependent.sort(key=lambda s: len(s.get("dependencies", [])))
        
        new_steps = completed + independent + dependent + failed
        
        return {
            "strategy": "reorder",
            "steps": new_steps,
            "analysis_types": [s.get("agent_name") for s in new_steps if s.get("agent_name")],
            "reasoning": "План переупорядочен для оптимального выполнения",
            "confidence": 0.8
        }
    
    def _create_skip_plan(
        self,
        current_plan: List[Dict],
        affected_agent: str,
        state: AnalysisState
    ) -> Dict[str, Any]:
        """Creates plan that skips failed agent and compensates"""
        new_steps = []
        
        for step in current_plan:
            # Проверяем, что step является словарем
            if not isinstance(step, dict):
                # Если step - строка, пропускаем или конвертируем
                if isinstance(step, str):
                    logger.warning(f"Skipping non-dict step in skip plan: {step}")
                    continue
                else:
                    # Пытаемся конвертировать в словарь
                    step = {"agent_name": str(step), "status": PlanStepStatus.PENDING.value}
            
            if step.get("agent_name") == affected_agent:
                # Mark as skipped
                skipped_step = dict(step)
                skipped_step["status"] = PlanStepStatus.SKIPPED.value
                skipped_step["reasoning"] = f"Пропущен после множественных ошибок"
                new_steps.append(skipped_step)
            else:
                new_steps.append(step)
        
        return {
            "strategy": "skip_and_compensate",
            "steps": new_steps,
            "analysis_types": [s.get("agent_name") for s in new_steps if s.get("agent_name") and s.get("status") != PlanStepStatus.SKIPPED.value],
            "reasoning": f"План пропускает {affected_agent} после ошибок, продолжает с остальными",
            "confidence": 0.6
        }
    
    def _fallback_replan(
        self,
        state: AnalysisState,
        failure_reason: str
    ) -> Dict[str, Any]:
        """Fallback replanning if main method fails"""
        analysis_types = state.get("analysis_types", [])
        # Remove last failed type if possible
        if len(analysis_types) > 1:
            simplified_types = analysis_types[:-1]
        else:
            simplified_types = ["key_facts", "timeline"]  # Basic fallback
        
        return {
            "strategy": "fallback",
            "analysis_types": simplified_types,
            "steps": [],
            "reasoning": f"Упрощенный план после ошибки: {failure_reason[:100]}",
            "confidence": 0.5
        }
    
    def _get_replanning_prompt(self) -> str:
        """Returns prompt for replanning agent"""
        return """Ты - эксперт по перепланированию задач после ошибок.

Твоя задача - проанализировать причину ошибки и предложить новый план выполнения.

Доступные стратегии:
1. retry_with_modifications - повторить с измененными параметрами
2. alternative_approach - использовать альтернативный метод
3. simplify - упростить задачу
4. decompose - разбить на подзадачи
5. reorder - изменить порядок выполнения
6. skip_and_compensate - пропустить и компенсировать

Анализируй причину ошибки и выбирай оптимальную стратегию."""

