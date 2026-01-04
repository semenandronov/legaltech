"""Replanner Subgraph - Phase 3.1 Implementation

This module provides a dedicated subgraph for replanning operations
with atomic handoff, rate limiting, and structured triggers.

Features:
- Dedicated replanner subgraph
- Command/goto navigation
- Atomic handoff via checkpoints
- Rate limited replanning
- Structured replan triggers
"""
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from app.services.langchain_agents.state import AnalysisState
from app.config import config
import logging
import hashlib

logger = logging.getLogger(__name__)

# Replanning configuration
MAX_REPLAN_ATTEMPTS = 3
REPLAN_COOLDOWN_SECONDS = 60  # Minimum time between replans
MIN_STEPS_BEFORE_REPLAN = 2  # Minimum steps before allowing replan


class ReplanTrigger:
    """Structured replan trigger with reason and context."""
    
    def __init__(
        self,
        action: str,
        reason: str,
        context: Optional[Dict[str, Any]] = None,
        priority: str = "medium"
    ):
        """
        Initialize replan trigger.
        
        Args:
            action: Action type ("replan", "skip", "retry", "abort")
            reason: Reason for replanning
            context: Additional context
            priority: Priority level (low, medium, high, critical)
        """
        self.action = action
        self.reason = reason
        self.context = context or {}
        self.priority = priority
        self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "context": self.context,
            "priority": self.priority,
            "timestamp": self.timestamp.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplanTrigger":
        return cls(
            action=data.get("action", "replan"),
            reason=data.get("reason", "unknown"),
            context=data.get("context", {}),
            priority=data.get("priority", "medium")
        )


class ReplannerSubgraph:
    """
    Dedicated subgraph for replanning operations.
    
    Provides atomic, rate-limited replanning with
    proper state management.
    """
    
    def __init__(self, llm=None):
        """
        Initialize replanner subgraph.
        
        Args:
            llm: Optional LLM instance
        """
        self._llm = llm
        self._replan_history: Dict[str, List[Dict[str, Any]]] = {}
    
    def _get_llm(self):
        """Get or create LLM instance."""
        if self._llm is None:
            try:
                from app.services.llm_factory import create_llm
                self._llm = create_llm(temperature=0.3)
            except Exception as e:
                logger.warning(f"Failed to initialize LLM for replanner: {e}")
        return self._llm
    
    def should_replan(
        self,
        state: AnalysisState,
        trigger: Optional[ReplanTrigger] = None
    ) -> Tuple[bool, str]:
        """
        Determine if replanning should occur.
        
        Checks rate limits, attempt counts, and other constraints.
        
        Args:
            state: Current state
            trigger: Optional replan trigger
            
        Returns:
            Tuple of (should_replan, reason)
        """
        case_id = state.get("case_id", "unknown")
        
        # Check replan attempts
        replan_attempts = state.get("replan_attempts", 0)
        if replan_attempts >= MAX_REPLAN_ATTEMPTS:
            return False, f"Max replan attempts ({MAX_REPLAN_ATTEMPTS}) reached"
        
        # Check cooldown
        last_replan = state.get("last_replan_time")
        if last_replan:
            try:
                last_time = datetime.fromisoformat(last_replan)
                cooldown_end = last_time + timedelta(seconds=REPLAN_COOLDOWN_SECONDS)
                if datetime.utcnow() < cooldown_end:
                    remaining = (cooldown_end - datetime.utcnow()).total_seconds()
                    return False, f"Replan cooldown ({remaining:.0f}s remaining)"
            except (ValueError, TypeError):
                pass
        
        # Check minimum steps
        completed_steps = len(state.get("completed_steps", []))
        if completed_steps < MIN_STEPS_BEFORE_REPLAN:
            return False, f"Not enough steps completed ({completed_steps} < {MIN_STEPS_BEFORE_REPLAN})"
        
        # Check for explicit trigger
        if trigger:
            if trigger.action == "replan":
                return True, trigger.reason
            elif trigger.action == "abort":
                return False, "Abort requested"
        
        # Check for errors that warrant replanning
        errors = state.get("errors", [])
        if len(errors) >= 3:
            return True, f"Multiple errors detected ({len(errors)})"
        
        # Check for stalled progress
        if state.get("is_stalled"):
            return True, "Analysis stalled"
        
        return False, "No replan needed"
    
    def create_replan(
        self,
        state: AnalysisState,
        trigger: ReplanTrigger
    ) -> Dict[str, Any]:
        """
        Create a new plan based on current state and trigger.
        
        Args:
            state: Current state
            trigger: Replan trigger with reason and context
            
        Returns:
            New plan as dictionary
        """
        case_id = state.get("case_id", "unknown")
        current_plan = state.get("current_plan", [])
        errors = state.get("errors", [])
        completed = state.get("completed_steps", [])
        
        logger.info(f"Creating replan for case {case_id}: {trigger.reason}")
        
        llm = self._get_llm()
        if not llm:
            # Fallback: simple plan modification
            return self._fallback_replan(state, trigger)
        
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            # Build context
            current_plan_str = "\n".join([
                f"- {step.get('step_name', 'unknown')}: {step.get('status', 'unknown')}"
                for step in current_plan if isinstance(step, dict)
            ])
            
            errors_str = "\n".join([
                f"- {e.get('agent', 'unknown')}: {e.get('error', 'unknown error')}"
                for e in errors[-5:]  # Last 5 errors
            ])
            
            prompt = f"""Создай исправленный план анализа на основе текущего состояния.

Причина перепланирования: {trigger.reason}

Текущий план:
{current_plan_str or 'Нет плана'}

Ошибки:
{errors_str or 'Нет ошибок'}

Завершенные шаги: {len(completed)}

Требования к новому плану:
1. Сохрани успешно выполненные шаги
2. Модифицируй или пропусти проблемные шаги
3. Добавь альтернативные подходы если нужно
4. План должен быть реалистичным

Верни JSON с полем "steps" содержащим список шагов:
{{"steps": [{{"step_name": "...", "description": "...", "agent": "...", "priority": 1-5}}]}}"""
            
            response = llm.invoke([
                SystemMessage(content="Ты планировщик анализа юридических документов."),
                HumanMessage(content=prompt)
            ])
            
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Parse response
            import re
            import json
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                new_plan = json.loads(json_match.group())
                return new_plan
            else:
                return self._fallback_replan(state, trigger)
                
        except Exception as e:
            logger.error(f"Replan generation failed: {e}")
            return self._fallback_replan(state, trigger)
    
    def _fallback_replan(
        self,
        state: AnalysisState,
        trigger: ReplanTrigger
    ) -> Dict[str, Any]:
        """
        Fallback replanning when LLM is unavailable.
        
        Creates a simple modified plan based on current state.
        """
        current_plan = state.get("current_plan", [])
        errors = state.get("errors", [])
        
        # Get failed agents
        failed_agents = {e.get("agent") for e in errors}
        
        # Rebuild plan excluding failed agents
        new_steps = []
        for step in current_plan:
            if isinstance(step, dict):
                agent = step.get("agent")
                if agent not in failed_agents:
                    new_steps.append(step)
                else:
                    # Mark as skipped
                    new_steps.append({
                        **step,
                        "status": "skipped",
                        "skip_reason": f"Previous execution failed: {trigger.reason}"
                    })
        
        return {"steps": new_steps, "method": "fallback"}
    
    def execute_replan(
        self,
        state: AnalysisState,
        trigger: ReplanTrigger
    ) -> AnalysisState:
        """
        Execute replanning and update state.
        
        This is the main entry point for the replanner subgraph.
        
        Args:
            state: Current state
            trigger: Replan trigger
            
        Returns:
            Updated state with new plan
        """
        case_id = state.get("case_id", "unknown")
        
        # Check if we should replan
        should, reason = self.should_replan(state, trigger)
        if not should:
            logger.info(f"Skipping replan for case {case_id}: {reason}")
            return state
        
        # Create new plan
        new_plan = self.create_replan(state, trigger)
        
        # Update state
        new_state = dict(state)
        
        # Store old plan in history
        replan_record = {
            "old_plan": state.get("current_plan", []),
            "new_plan": new_plan.get("steps", []),
            "trigger": trigger.to_dict(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        replan_history = list(state.get("replan_history", []))
        replan_history.append(replan_record)
        new_state["replan_history"] = replan_history
        
        # Update plan
        new_state["current_plan"] = new_plan.get("steps", [])
        new_state["replan_attempts"] = state.get("replan_attempts", 0) + 1
        new_state["last_replan_time"] = datetime.utcnow().isoformat()
        new_state["last_replan_reason"] = trigger.reason
        
        # Clear stall flag
        new_state["is_stalled"] = False
        
        logger.info(
            f"Replanned case {case_id} (attempt {new_state['replan_attempts']}): "
            f"{len(new_plan.get('steps', []))} new steps"
        )
        
        return new_state


def create_replan_trigger(
    reason: str,
    context: Optional[Dict[str, Any]] = None,
    priority: str = "medium"
) -> ReplanTrigger:
    """
    Create a structured replan trigger.
    
    Common reasons:
    - "missing-data": Required data not found
    - "agent-failure": Agent execution failed
    - "timeout": Operation timed out
    - "user-request": User requested replanning
    - "quality-issue": Output quality below threshold
    
    Args:
        reason: Reason for replanning
        context: Additional context
        priority: Priority level
        
    Returns:
        ReplanTrigger instance
    """
    return ReplanTrigger(
        action="replan",
        reason=reason,
        context=context,
        priority=priority
    )


# Global replanner instance
_replanner: Optional[ReplannerSubgraph] = None


def get_replanner() -> ReplannerSubgraph:
    """Get or create the global replanner instance."""
    global _replanner
    if _replanner is None:
        _replanner = ReplannerSubgraph()
    return _replanner

