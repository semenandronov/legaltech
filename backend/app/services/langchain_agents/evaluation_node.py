"""Evaluation node for assessing agent results and triggering adaptation"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
from app.services.llm_factory import create_llm
from app.config import config
import logging

logger = logging.getLogger(__name__)


class ResultEvaluator:
    """Evaluates agent results to determine if adaptation is needed"""
    
    # Thresholds for evaluation
    MIN_CONFIDENCE_THRESHOLD = 0.5
    MIN_COMPLETENESS_THRESHOLD = 0.6
    MAX_ERROR_RATE = 0.3
    
    def __init__(self):
        """Initialize evaluator"""
        try:
            self.llm = create_llm(temperature=0.1)
        except Exception as e:
            logger.warning(f"Failed to initialize LLM for evaluator: {e}")
            self.llm = None
    
    def evaluate_step_result(
        self,
        step_id: str,
        agent_name: str,
        result: Optional[Dict[str, Any]],
        expected_output: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate a single step's result
        
        Args:
            step_id: Step identifier
            agent_name: Name of the agent
            result: Result from the agent
            expected_output: Optional expected output description
            
        Returns:
            Evaluation result with scores and recommendations
        """
        evaluation = {
            "step_id": step_id,
            "agent_name": agent_name,
            "success": False,
            "confidence": 0.0,
            "completeness": 0.0,
            "issues": [],
            "recommendations": [],
            "needs_retry": False,
            "needs_adaptation": False,
        }
        
        if result is None:
            evaluation["issues"].append("No result returned")
            evaluation["needs_retry"] = True
            return evaluation
        
        # Check for errors in result
        if "error" in result or "errors" in result:
            errors = result.get("errors", [result.get("error")])
            evaluation["issues"].extend([str(e) for e in errors if e])
            evaluation["needs_retry"] = True
            return evaluation
        
        # Evaluate based on agent type
        if agent_name == "timeline":
            evaluation = self._evaluate_timeline_result(evaluation, result)
        elif agent_name == "key_facts":
            evaluation = self._evaluate_key_facts_result(evaluation, result)
        elif agent_name == "discrepancy":
            evaluation = self._evaluate_discrepancy_result(evaluation, result)
        elif agent_name == "risk":
            evaluation = self._evaluate_risk_result(evaluation, result)
        elif agent_name == "summary":
            evaluation = self._evaluate_summary_result(evaluation, result)
        else:
            # Generic evaluation
            evaluation = self._evaluate_generic_result(evaluation, result)
        
        # Determine if adaptation is needed
        evaluation["needs_adaptation"] = (
            evaluation["confidence"] < self.MIN_CONFIDENCE_THRESHOLD or
            evaluation["completeness"] < self.MIN_COMPLETENESS_THRESHOLD or
            len(evaluation["issues"]) > 2
        )
        
        evaluation["success"] = (
            not evaluation["needs_retry"] and 
            not evaluation["needs_adaptation"]
        )
        
        return evaluation
    
    def _evaluate_timeline_result(
        self, 
        evaluation: Dict[str, Any], 
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate timeline extraction result"""
        events = result.get("events", [])
        total = result.get("total_events", len(events))
        
        if total == 0:
            evaluation["issues"].append("No timeline events extracted")
            evaluation["completeness"] = 0.0
            evaluation["confidence"] = 0.0
            evaluation["recommendations"].append(
                "Consider using broader date extraction patterns"
            )
        else:
            # Check event quality
            events_with_dates = sum(1 for e in events if e.get("date"))
            events_with_sources = sum(1 for e in events if e.get("source_document"))
            
            evaluation["completeness"] = min(total / 10.0, 1.0)  # Expect ~10 events
            evaluation["confidence"] = (
                (events_with_dates / total * 0.5) +
                (events_with_sources / total * 0.5)
            ) if total > 0 else 0.0
            
            if events_with_dates < total * 0.8:
                evaluation["issues"].append("Some events missing dates")
        
        return evaluation
    
    def _evaluate_key_facts_result(
        self, 
        evaluation: Dict[str, Any], 
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate key facts extraction result"""
        facts = result.get("facts", result.get("key_facts", []))
        
        if not facts:
            evaluation["issues"].append("No key facts extracted")
            evaluation["completeness"] = 0.0
            evaluation["confidence"] = 0.0
        else:
            evaluation["completeness"] = min(len(facts) / 5.0, 1.0)  # Expect ~5 facts
            
            # Check fact quality
            facts_with_sources = sum(
                1 for f in facts 
                if isinstance(f, dict) and f.get("source")
            )
            evaluation["confidence"] = (
                facts_with_sources / len(facts) if len(facts) > 0 else 0.0
            )
        
        return evaluation
    
    def _evaluate_discrepancy_result(
        self, 
        evaluation: Dict[str, Any], 
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate discrepancy detection result"""
        discrepancies = result.get("discrepancies", [])
        
        # It's okay to have no discrepancies
        evaluation["completeness"] = 1.0
        evaluation["confidence"] = result.get("confidence", 0.7)
        
        if discrepancies:
            # Check discrepancy quality
            valid_discrepancies = sum(
                1 for d in discrepancies 
                if isinstance(d, dict) and d.get("description")
            )
            evaluation["confidence"] = (
                valid_discrepancies / len(discrepancies)
                if len(discrepancies) > 0 else 0.7
            )
        
        return evaluation
    
    def _evaluate_risk_result(
        self, 
        evaluation: Dict[str, Any], 
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate risk analysis result"""
        risks = result.get("risks", [])
        overall_risk = result.get("overall_risk_level")
        
        if not risks and not overall_risk:
            evaluation["issues"].append("No risk assessment provided")
            evaluation["completeness"] = 0.3
            evaluation["confidence"] = 0.3
        else:
            evaluation["completeness"] = 1.0 if overall_risk else 0.7
            evaluation["confidence"] = 0.8
        
        return evaluation
    
    def _evaluate_summary_result(
        self, 
        evaluation: Dict[str, Any], 
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate summary result"""
        summary = result.get("summary", result.get("text", ""))
        
        if not summary:
            evaluation["issues"].append("No summary generated")
            evaluation["completeness"] = 0.0
            evaluation["confidence"] = 0.0
        else:
            # Check summary length (should be substantial)
            word_count = len(summary.split())
            evaluation["completeness"] = min(word_count / 100.0, 1.0)
            evaluation["confidence"] = 0.8 if word_count > 50 else 0.5
        
        return evaluation
    
    def _evaluate_generic_result(
        self, 
        evaluation: Dict[str, Any], 
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generic evaluation for unknown agent types"""
        # Check if result has any meaningful content
        has_content = any(
            v for k, v in result.items() 
            if k not in ["error", "errors", "metadata"] and v
        )
        
        evaluation["completeness"] = 1.0 if has_content else 0.0
        evaluation["confidence"] = result.get("confidence", 0.7) if has_content else 0.0
        
        return evaluation
    
    def evaluate_overall_progress(
        self,
        state: AnalysisState
    ) -> Dict[str, Any]:
        """
        Evaluate overall analysis progress
        
        Args:
            state: Current analysis state
            
        Returns:
            Overall evaluation with progress and recommendations
        """
        requested = set(state.get("analysis_types", []))
        completed = set(state.get("completed_steps", []))
        errors = state.get("errors", [])
        
        # Calculate progress
        progress = len(completed) / len(requested) if requested else 0.0
        error_rate = len(errors) / max(len(completed), 1)
        
        evaluation = {
            "progress": progress,
            "completed_count": len(completed),
            "total_count": len(requested),
            "error_rate": error_rate,
            "is_healthy": error_rate <= self.MAX_ERROR_RATE,
            "recommendations": [],
        }
        
        if error_rate > self.MAX_ERROR_RATE:
            evaluation["recommendations"].append(
                "High error rate detected. Consider simplifying the analysis."
            )
        
        if progress < 0.5 and len(errors) > 2:
            evaluation["recommendations"].append(
                "Multiple early failures. Consider retrying failed steps."
            )
        
        return evaluation


def evaluation_node(
    state: AnalysisState,
    db=None,
    rag_service=None,
    document_processor=None
) -> AnalysisState:
    """
    Evaluation node for the analysis graph.
    Evaluates results and determines if adaptation is needed.
    
    Args:
        state: Current analysis state
        db: Database session (unused but required for signature)
        rag_service: RAG service (unused)
        document_processor: Document processor (unused)
        
    Returns:
        Updated state with evaluation results
    """
    case_id = state.get("case_id", "unknown")
    logger.info(f"[Evaluation] Starting evaluation for case {case_id}")
    
    evaluator = ResultEvaluator()
    new_state = dict(state)
    
    # Determine which agent was just executed by checking which result was updated
    # Check results in order of execution priority
    agent_result_keys = [
        ("document_classifier", "classification_result"),
        ("privilege_check", "privilege_result"),
        ("entity_extraction", "entities_result"),
        ("timeline", "timeline_result"),
        ("key_facts", "key_facts_result"),
        ("discrepancy", "discrepancy_result"),
        ("relationship", "relationship_result"),
        ("risk", "risk_result"),
        ("summary", "summary_result"),
    ]
    
    # Find the agent that was just executed (has result but wasn't evaluated yet)
    agent_name = None
    result = None
    result_key = None
    
    # Check if we have a current_step_id from state
    current_step_id = state.get("current_step_id")
    if current_step_id:
        # Find the step in current plan
        current_plan = state.get("current_plan", [])
        for step in current_plan:
            if step.get("step_id") == current_step_id:
                agent_name = step.get("agent_name", "")
                result_key = f"{agent_name}_result"
                result = state.get(result_key)
                break
    
    # If no current_step_id, try to determine from results
    if not agent_name or not result:
        # Find the first agent with a result that hasn't been evaluated
        # We check by looking for results that exist but weren't in previous evaluation
        previous_eval = state.get("evaluation_result")
        if previous_eval is None:
            previous_eval = {}
        previous_agent = previous_eval.get("agent_name") if isinstance(previous_eval, dict) else None
        
        for agent, key in agent_result_keys:
            if state.get(key) is not None:
                # If this is a new result (different from previous evaluation), evaluate it
                if agent != previous_agent:
                    agent_name = agent
                    result_key = key
                    result = state.get(key)
                    break
    
    if not agent_name or result is None:
        # No specific agent to evaluate, check overall progress
        overall_eval = evaluator.evaluate_overall_progress(state)
        new_state["evaluation_result"] = overall_eval
        logger.info(f"[Evaluation] Overall progress: {overall_eval['progress']:.1%}")
        return new_state
    
    # Generate step_id if not present
    if not current_step_id:
        current_step_id = f"{agent_name}_{case_id}"
        new_state["current_step_id"] = current_step_id
    
    # Evaluate the step
    step_evaluation = evaluator.evaluate_step_result(
        step_id=current_step_id,
        agent_name=agent_name,
        result=result
    )
    
    # Log evaluation
    logger.info(
        f"[Evaluation] Step {current_step_id} ({agent_name}): "
        f"success={step_evaluation['success']}, "
        f"confidence={step_evaluation['confidence']:.2f}, "
        f"completeness={step_evaluation['completeness']:.2f}"
    )
    
    if step_evaluation["issues"]:
        logger.warning(f"[Evaluation] Issues: {step_evaluation['issues']}")
    
    # Update state
    new_state["evaluation_result"] = step_evaluation
    new_state["needs_replanning"] = step_evaluation.get("needs_adaptation", False)
    
    # Check if human feedback is needed (low confidence)
    confidence = step_evaluation.get("confidence", 1.0)
    HUMAN_FEEDBACK_THRESHOLD = 0.5
    
    if confidence < HUMAN_FEEDBACK_THRESHOLD and not step_evaluation.get("needs_retry", False):
        # Create human feedback request
        from app.services.langchain_agents.state import HumanFeedbackRequest
        import uuid
        from datetime import datetime
        
        feedback_request = HumanFeedbackRequest(
            request_id=str(uuid.uuid4()),
            agent_name=agent_name,
            question_type="clarification",
            question_text=f"Агент {agent_name} получил низкую уверенность ({confidence:.2f}) в результате. "
                         f"Проблемы: {', '.join(step_evaluation.get('issues', ['Неизвестно']))}. "
                         f"Можете уточнить задачу или подтвердить, что результат приемлем?",
            context=f"Результат агента {agent_name} для дела {case_id}. Confidence: {confidence:.2f}",
            status="pending"
        )
        
        # Add to pending feedback
        pending_feedback = list(state.get("pending_feedback", []))
        pending_feedback.append(feedback_request.to_dict())
        new_state["pending_feedback"] = pending_feedback
        new_state["waiting_for_human"] = True
        new_state["current_feedback_request"] = feedback_request.to_dict()
        
        logger.info(
            f"[Evaluation] Low confidence ({confidence:.2f}) for {agent_name}, "
            f"requesting human feedback: {feedback_request.request_id}"
        )
    
    if step_evaluation["success"]:
        # Mark step as completed
        completed = list(state.get("completed_steps", []))
        if current_step_id not in completed:
            completed.append(current_step_id)
        new_state["completed_steps"] = completed
    
    return new_state

