"""Adaptation engine for dynamic plan modification"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.services.langchain_agents.state import (
    AnalysisState, 
    PlanStepStatus,
    AdaptationRecord
)
from app.services.langchain_agents.replanning_agent import ReplanningAgent
from app.services.llm_factory import create_llm
from app.config import config
import logging

logger = logging.getLogger(__name__)


class AdaptationEngine:
    """
    Engine for adapting analysis plans based on evaluation results.
    Implements the adaptation capability from Harvey Agents.
    """
    
    def __init__(
        self,
        rag_service: Optional[Any] = None,
        document_processor: Optional[Any] = None
    ):
        """Initialize adaptation engine"""
        try:
            self.llm = create_llm(temperature=0.2)
        except Exception as e:
            logger.warning(f"Failed to initialize LLM for adaptation engine: {e}")
            self.llm = None
        
        # Initialize replanning agent for intelligent replanning
        try:
            self.replanning_agent = ReplanningAgent(
                rag_service=rag_service,
                document_processor=document_processor
            )
            logger.info("Replanning agent initialized for adaptation engine")
        except Exception as e:
            logger.warning(f"Failed to initialize replanning agent: {e}")
            self.replanning_agent = None
    
    def should_adapt(
        self,
        state: AnalysisState,
        evaluation: Dict[str, Any]
    ) -> bool:
        """
        Determine if plan adaptation is needed
        
        Args:
            state: Current analysis state
            evaluation: Evaluation result
            
        Returns:
            True if adaptation is recommended
        """
        # Check explicit flag
        if state.get("needs_replanning"):
            return True
        
        # Check evaluation recommendations
        if evaluation.get("needs_adaptation"):
            return True
        
        # Check error rate
        errors = state.get("errors", [])
        completed = state.get("completed_steps", [])
        if len(errors) > 0 and len(errors) / max(len(completed), 1) > 0.3:
            return True
        
        # Check if we're stuck (no progress with pending steps)
        current_plan = state.get("current_plan", [])
        pending_steps = [
            s for s in current_plan 
            if isinstance(s, dict) and s.get("status") == PlanStepStatus.PENDING.value
        ]
        if pending_steps and not completed:
            # We have pending steps but no progress - might need adaptation
            return True
        
        return False
    
    def adapt_plan(
        self,
        state: AnalysisState,
        evaluation: Dict[str, Any],
        trigger: str = "evaluation"
    ) -> AnalysisState:
        """
        Adapt the analysis plan based on current state and evaluation
        
        Args:
            state: Current analysis state
            evaluation: Evaluation result
            trigger: What triggered the adaptation
            
        Returns:
            Updated state with adapted plan
        """
        new_state = dict(state)
        plan_data = state.get("current_plan", [])
        
        # Handle case where current_plan might be a dict with 'steps' key
        if isinstance(plan_data, dict):
            current_plan = plan_data.get("steps", [])
        elif isinstance(plan_data, list):
            current_plan = plan_data
        else:
            current_plan = []
        
        if not current_plan:
            logger.info("[Adaptation] No plan to adapt")
            return new_state
        
        # Determine adaptation strategy
        strategy = self._determine_strategy(state, evaluation)
        
        logger.info(f"[Adaptation] Applying strategy: {strategy}")
        
        # Use intelligent replanning for complex failures
        if self.replanning_agent and strategy in ["retry_failed", "alternative_approach", "simplify", "reorder"]:
            try:
                # Extract failure reason from evaluation
                failure_reason = self._extract_failure_reason(evaluation, state)
                context = {
                    "agent_name": evaluation.get("agent_name", "unknown"),
                    "evaluation": evaluation,
                    "strategy": strategy
                }
                
                # Use replanning agent for intelligent replanning
                replanned = self.replanning_agent.replan(state, failure_reason, context)
                
                if replanned and replanned.get("steps"):
                    logger.info(f"[Adaptation] Using intelligent replanning: {replanned.get('strategy')}")
                    new_plan = replanned.get("steps", current_plan)
                else:
                    # Fallback to rule-based strategies
                    new_plan = self._apply_rule_based_strategy(strategy, current_plan, state, evaluation)
            except Exception as e:
                logger.warning(f"Intelligent replanning failed: {e}, using rule-based")
                new_plan = self._apply_rule_based_strategy(strategy, current_plan, state, evaluation)
        else:
            # Use rule-based strategies
            new_plan = self._apply_rule_based_strategy(strategy, current_plan, state, evaluation)
        
        # Record adaptation
        if new_plan != current_plan:
            adaptation_record = AdaptationRecord(
                timestamp=datetime.utcnow().isoformat(),
                reason=evaluation.get("issues", ["Unknown"])[0] if evaluation.get("issues") else "Optimization",
                original_plan=[s.get("step_id") if isinstance(s, dict) else str(s) for s in current_plan],
                new_plan=[s.get("step_id") if isinstance(s, dict) else str(s) for s in new_plan],
                trigger=trigger
            )
            
            history = list(state.get("adaptation_history", []))
            history.append(adaptation_record.to_dict())
            
            new_state["adaptation_history"] = history
            new_state["current_plan"] = new_plan
            
            # Learn from error patterns
            self._learn_from_error(state, evaluation, new_plan)
            
            logger.info(
                f"[Adaptation] Plan adapted: {len(current_plan)} -> {len(new_plan)} steps"
            )
        
        # Reset replanning flag
        new_state["needs_replanning"] = False
        
        return new_state
    
    def _learn_from_error(
        self,
        state: AnalysisState,
        evaluation: Dict[str, Any],
        new_plan: List[Dict[str, Any]]
    ) -> None:
        """Learns from error patterns to prevent future failures"""
        agent_name = evaluation.get("agent_name", "unknown")
        failure_type = evaluation.get("issues", [])
        
        # Store error pattern in metadata for future reference
        if "metadata" not in state:
            state["metadata"] = {}
        
        if "error_patterns" not in state["metadata"]:
            state["metadata"]["error_patterns"] = {}
        
        if agent_name not in state["metadata"]["error_patterns"]:
            state["metadata"]["error_patterns"][agent_name] = {
                "count": 0,
                "common_issues": [],
                "successful_adaptations": []
            }
        
        pattern = state["metadata"]["error_patterns"][agent_name]
        pattern["count"] = pattern["count"] + 1
        
        # Track common issues
        for issue in failure_type[:3]:  # Top 3 issues
            if issue not in pattern["common_issues"]:
                pattern["common_issues"].append(issue)
        
        # Track successful adaptation strategy
        if new_plan:
            strategy = new_plan[0].get("reasoning", "") if isinstance(new_plan[0], dict) else ""
            if strategy and strategy not in pattern["successful_adaptations"]:
                pattern["successful_adaptations"].append(strategy[:100])  # Limit length
        
        logger.debug(f"Learned error pattern for {agent_name}: {pattern}")
    
    def _determine_strategy(
        self,
        state: AnalysisState,
        evaluation: Dict[str, Any]
    ) -> str:
        """
        Determine the best adaptation strategy
        
        Args:
            state: Current state
            evaluation: Evaluation result
            
        Returns:
            Strategy name
        """
        issues = evaluation.get("issues", [])
        errors = state.get("errors", [])
        confidence = evaluation.get("confidence", 1.0)
        completeness = evaluation.get("completeness", 1.0)
        
        # Check for recoverable errors - retry
        if evaluation.get("needs_retry"):
            retry_count = state.get("metadata", {}).get("retry_count", 0)
            if retry_count < 2:
                return "retry_failed"
            else:
                return "skip_failed"
        
        # Low confidence - might need more data
        if confidence < 0.5:
            return "add_steps"
        
        # Low completeness - might need to simplify
        if completeness < 0.5:
            return "simplify"
        
        # Multiple errors - reorder to do easier tasks first
        if len(errors) > 2:
            return "reorder"
        
        return "none"
    
    def _extract_failure_reason(
        self,
        evaluation: Dict[str, Any],
        state: AnalysisState
    ) -> str:
        """Extracts failure reason from evaluation and state"""
        issues = evaluation.get("issues", [])
        errors = state.get("errors", [])
        
        if issues:
            return "; ".join(issues[:3])  # First 3 issues
        elif errors:
            last_error = errors[-1] if errors else {}
            return last_error.get("error", "Unknown error")
        else:
            return "Low quality result"
    
    def _apply_rule_based_strategy(
        self,
        strategy: str,
        current_plan: List[Dict[str, Any]],
        state: AnalysisState,
        evaluation: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Applies rule-based adaptation strategy"""
        if strategy == "retry_failed":
            return self._apply_retry_strategy(current_plan, state)
        elif strategy == "skip_failed":
            return self._apply_skip_strategy(current_plan, state)
        elif strategy == "add_steps":
            return self._apply_add_steps_strategy(current_plan, state, evaluation)
        elif strategy == "reorder":
            return self._apply_reorder_strategy(current_plan, state)
        elif strategy == "simplify":
            return self._apply_simplify_strategy(current_plan, state)
        else:
            return current_plan
    
    def _apply_retry_strategy(
        self,
        plan: List[Dict[str, Any]],
        state: AnalysisState
    ) -> List[Dict[str, Any]]:
        """Retry failed steps with modified parameters"""
        new_plan = []
        
        for step in plan:
            # Проверяем, что step является словарем
            if not isinstance(step, dict):
                if isinstance(step, str):
                    logger.warning(f"Skipping non-dict step in retry strategy: {step}")
                    continue
                else:
                    step = {"agent_name": str(step), "status": PlanStepStatus.PENDING.value}
            
            if step.get("status") == PlanStepStatus.FAILED.value:
                # Reset to pending for retry
                retry_step = dict(step)
                retry_step["status"] = PlanStepStatus.PENDING.value
                retry_step["error"] = None
                retry_step["reasoning"] = "Retrying after evaluation"
                new_plan.append(retry_step)
            else:
                new_plan.append(step)
        
        # Update retry count
        metadata = dict(state.get("metadata", {}))
        metadata["retry_count"] = metadata.get("retry_count", 0) + 1
        
        return new_plan
    
    def _apply_skip_strategy(
        self,
        plan: List[Dict[str, Any]],
        state: AnalysisState
    ) -> List[Dict[str, Any]]:
        """Skip failed steps and continue with remaining"""
        new_plan = []
        
        for step in plan:
            # Проверяем, что step является словарем
            if not isinstance(step, dict):
                if isinstance(step, str):
                    logger.warning(f"Skipping non-dict step in skip strategy: {step}")
                    continue
                else:
                    step = {"agent_name": str(step), "status": PlanStepStatus.PENDING.value}
            
            if step.get("status") == PlanStepStatus.FAILED.value:
                # Mark as skipped
                skip_step = dict(step)
                skip_step["status"] = PlanStepStatus.SKIPPED.value
                skip_step["reasoning"] = "Skipped after multiple failures"
                new_plan.append(skip_step)
            else:
                new_plan.append(step)
        
        return new_plan
    
    def _apply_add_steps_strategy(
        self,
        plan: List[Dict[str, Any]],
        state: AnalysisState,
        evaluation: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Add additional steps to improve results"""
        new_plan = list(plan)
        
        # Check what might help
        recommendations = evaluation.get("recommendations", [])
        
        # Add entity extraction if not present and might help
        analysis_types = state.get("analysis_types", [])
        if "entity_extraction" not in analysis_types:
            # Check if entities would help
            if any("date" in str(r).lower() for r in recommendations):
                new_step = {
                    "step_id": f"added_entity_extraction_{datetime.utcnow().timestamp()}",
                    "agent_name": "entity_extraction",
                    "description": "Extract additional entities to improve analysis",
                    "status": PlanStepStatus.PENDING.value,
                    "dependencies": [],
                    "result_key": "entities_result",
                    "reasoning": "Added to improve data extraction",
                }
                new_plan.insert(0, new_step)
        
        return new_plan
    
    def _apply_reorder_strategy(
        self,
        plan: List[Dict[str, Any]],
        state: AnalysisState
    ) -> List[Dict[str, Any]]:
        """Reorder steps to do simpler tasks first"""
        # Separate completed, pending, and failed
        completed = [s for s in plan if isinstance(s, dict) and s.get("status") == PlanStepStatus.COMPLETED.value]
        pending = [s for s in plan if isinstance(s, dict) and s.get("status") == PlanStepStatus.PENDING.value]
        failed = [s for s in plan if isinstance(s, dict) and s.get("status") == PlanStepStatus.FAILED.value]
        
        # Sort pending by complexity (simple agents first)
        simple_agents = ["timeline", "key_facts", "entity_extraction"]
        complex_agents = ["risk", "summary", "relationship"]
        
        def sort_key(step):
            if not isinstance(step, dict):
                return 999  # Non-dict steps go to end
            agent = step.get("agent_name", "")
            if agent in simple_agents:
                return 0
            elif agent in complex_agents:
                return 2
            return 1
        
        pending.sort(key=sort_key)
        
        # Reconstruct plan
        return completed + pending + failed
    
    def _apply_simplify_strategy(
        self,
        plan: List[Dict[str, Any]],
        state: AnalysisState
    ) -> List[Dict[str, Any]]:
        """Simplify plan by removing optional steps"""
        # Required steps that should always run
        required_agents = ["timeline", "key_facts"]
        
        new_plan = []
        for step in plan:
            # Проверяем, что step является словарем
            if not isinstance(step, dict):
                # Если step - строка, пропускаем или конвертируем
                if isinstance(step, str):
                    logger.warning(f"Skipping non-dict step in simplify strategy: {step}")
                    continue
                else:
                    # Пытаемся конвертировать в словарь
                    step = {"agent_name": str(step), "status": PlanStepStatus.PENDING.value}
            
            agent = step.get("agent_name", "")
            status = step.get("status", "")
            
            # Keep completed and required steps
            if status == PlanStepStatus.COMPLETED.value:
                new_plan.append(step)
            elif agent in required_agents:
                new_plan.append(step)
            elif status == PlanStepStatus.FAILED.value:
                # Mark optional failed steps as skipped
                skip_step = dict(step)
                skip_step["status"] = PlanStepStatus.SKIPPED.value
                skip_step["reasoning"] = "Skipped during simplification"
                new_plan.append(skip_step)
            else:
                # Keep other pending steps but mark as optional
                optional_step = dict(step)
                optional_step["reasoning"] = "Optional - may be skipped"
                new_plan.append(optional_step)
        
        return new_plan


def adaptation_node(
    state: AnalysisState,
    db=None,
    rag_service=None,
    document_processor=None
) -> AnalysisState:
    """
    Adaptation node for the analysis graph.
    Adapts the plan based on evaluation results.
    
    Args:
        state: Current analysis state
        db: Database session (unused)
        rag_service: RAG service for replanning agent
        document_processor: Document processor for replanning agent
        
    Returns:
        Updated state with adapted plan
    """
    case_id = state.get("case_id", "unknown")
    logger.info(f"[Adaptation] Starting adaptation for case {case_id}")
    
    engine = AdaptationEngine(rag_service=rag_service, document_processor=document_processor)
    evaluation = state.get("evaluation_result", {})
    
    # Check if adaptation is needed
    if not engine.should_adapt(state, evaluation):
        logger.info("[Adaptation] No adaptation needed")
        return state
    
    # Adapt the plan
    new_state = engine.adapt_plan(state, evaluation, trigger="evaluation")
    
    return new_state

