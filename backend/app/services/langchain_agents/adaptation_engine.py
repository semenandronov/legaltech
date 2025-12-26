"""Adaptation engine for dynamic plan modification"""
from typing import Dict, Any, List
from datetime import datetime
from app.services.langchain_agents.state import (
    AnalysisState, 
    PlanStepStatus,
    AdaptationRecord
)
from app.services.yandex_llm import ChatYandexGPT
from app.config import config
import logging

logger = logging.getLogger(__name__)


class AdaptationEngine:
    """
    Engine for adapting analysis plans based on evaluation results.
    Implements the adaptation capability from Harvey Agents.
    """
    
    def __init__(self):
        """Initialize adaptation engine"""
        if config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN:
            self.llm = ChatYandexGPT(
                model=config.YANDEX_GPT_MODEL or "yandexgpt-lite",
                temperature=0.2,
            )
        else:
            self.llm = None
    
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
            if s.get("status") == PlanStepStatus.PENDING.value
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
        current_plan = list(state.get("current_plan", []))
        
        if not current_plan:
            logger.info("[Adaptation] No plan to adapt")
            return new_state
        
        # Determine adaptation strategy
        strategy = self._determine_strategy(state, evaluation)
        
        logger.info(f"[Adaptation] Applying strategy: {strategy}")
        
        if strategy == "retry_failed":
            new_plan = self._apply_retry_strategy(current_plan, state)
        elif strategy == "skip_failed":
            new_plan = self._apply_skip_strategy(current_plan, state)
        elif strategy == "add_steps":
            new_plan = self._apply_add_steps_strategy(current_plan, state, evaluation)
        elif strategy == "reorder":
            new_plan = self._apply_reorder_strategy(current_plan, state)
        elif strategy == "simplify":
            new_plan = self._apply_simplify_strategy(current_plan, state)
        else:
            # No adaptation needed
            new_plan = current_plan
        
        # Record adaptation
        if new_plan != current_plan:
            adaptation_record = AdaptationRecord(
                timestamp=datetime.utcnow().isoformat(),
                reason=evaluation.get("issues", ["Unknown"])[0] if evaluation.get("issues") else "Optimization",
                original_plan=[s.get("step_id") for s in current_plan],
                new_plan=[s.get("step_id") for s in new_plan],
                trigger=trigger
            )
            
            history = list(state.get("adaptation_history", []))
            history.append(adaptation_record.to_dict())
            
            new_state["adaptation_history"] = history
            new_state["current_plan"] = new_plan
            
            logger.info(
                f"[Adaptation] Plan adapted: {len(current_plan)} -> {len(new_plan)} steps"
            )
        
        # Reset replanning flag
        new_state["needs_replanning"] = False
        
        return new_state
    
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
    
    def _apply_retry_strategy(
        self,
        plan: List[Dict[str, Any]],
        state: AnalysisState
    ) -> List[Dict[str, Any]]:
        """Retry failed steps with modified parameters"""
        new_plan = []
        
        for step in plan:
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
        completed = [s for s in plan if s.get("status") == PlanStepStatus.COMPLETED.value]
        pending = [s for s in plan if s.get("status") == PlanStepStatus.PENDING.value]
        failed = [s for s in plan if s.get("status") == PlanStepStatus.FAILED.value]
        
        # Sort pending by complexity (simple agents first)
        simple_agents = ["timeline", "key_facts", "entity_extraction"]
        complex_agents = ["risk", "summary", "relationship"]
        
        def sort_key(step):
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
        rag_service: RAG service (unused)
        document_processor: Document processor (unused)
        
    Returns:
        Updated state with adapted plan
    """
    case_id = state.get("case_id", "unknown")
    logger.info(f"[Adaptation] Starting adaptation for case {case_id}")
    
    engine = AdaptationEngine()
    evaluation = state.get("evaluation_result", {})
    
    # Check if adaptation is needed
    if not engine.should_adapt(state, evaluation):
        logger.info("[Adaptation] No adaptation needed")
        return state
    
    # Adapt the plan
    new_state = engine.adapt_plan(state, evaluation, trigger="evaluation")
    
    return new_state

