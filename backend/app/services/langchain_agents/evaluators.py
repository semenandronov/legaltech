"""Evaluators for automatic quality assessment of agent results"""
from typing import Dict, Any, Optional
from app.services.llm_factory import create_llm
import logging
import json

logger = logging.getLogger(__name__)


def create_agent_evaluator(agent_type: str) -> Optional[Any]:
    """
    Create evaluator for specific agent type
    
    Args:
        agent_type: Type of agent (timeline, key_facts, discrepancy, risk, summary)
        
    Returns:
        Evaluator instance or None if unavailable
    """
    try:
        from langchain.evaluation import load_evaluator, EvaluatorType
        
        # Define criteria for each agent type
        criteria_map = {
            "timeline": (
                "Точность дат и событий, полнота временной линии, "
                "корректность извлечения из документов, отсутствие пропусков важных событий"
            ),
            "key_facts": (
                "Релевантность фактов, полнота извлечения ключевой информации, "
                "отсутствие пропусков важных фактов, корректность классификации фактов"
            ),
            "discrepancy": (
                "Корректность выявления противоречий, точность определения типа противоречия, "
                "обоснованность severity оценки, наличие доказательств"
            ),
            "risk": (
                "Корректность оценки рисков, обоснованность probability и impact, "
                "релевантность рекомендаций, связь с найденными противоречиями"
            ),
            "summary": (
                "Полнота резюме, структурированность, охват всех ключевых аспектов дела, "
                "отсутствие важных пропусков, читаемость и логичность"
            ),
            "entity_extraction": (
                "Точность извлечения сущностей, полнота покрытия всех типов сущностей, "
                "корректность классификации, отсутствие ложных срабатываний"
            ),
            "document_classifier": (
                "Точность классификации документов, корректность определения типа документа, "
                "обоснованность классификации"
            ),
            "privilege_check": (
                "Корректность определения привилегий, точность выявления конфликтов интересов, "
                "обоснованность выводов"
            ),
            "relationship": (
                "Точность построения графа связей, полнота выявления отношений, "
                "корректность типизации связей"
            )
        }
        
        criteria = criteria_map.get(agent_type, "Общее качество анализа")
        
        # Create criteria evaluator
        llm = create_llm(temperature=0.1)  # Low temperature for consistent evaluation
        
        evaluator = load_evaluator(
            EvaluatorType.CRITERIA,
            criteria=criteria,
            llm=llm
        )
        
        logger.debug(f"Created evaluator for {agent_type}")
        return evaluator
        
    except ImportError:
        logger.warning("LangChain evaluators not available. Quality evaluation disabled.")
        return None
    except Exception as e:
        logger.warning(f"Failed to create evaluator for {agent_type}: {e}")
        return None


def evaluate_agent_result(
    evaluator: Any,
    prediction: Dict[str, Any],
    reference: Optional[Dict[str, Any]] = None,
    input_text: Optional[str] = None
) -> Dict[str, Any]:
    """
    Evaluate agent result using evaluator
    
    Args:
        evaluator: Evaluator instance
        prediction: Agent result to evaluate
        reference: Optional reference/expected result
        input_text: Optional input text for context
        
    Returns:
        Evaluation result dictionary
    """
    if evaluator is None:
        return {
            "score": None,
            "reasoning": "Evaluator not available",
            "passed": False
        }
    
    try:
        # Convert prediction to string for evaluation
        if isinstance(prediction, dict):
            prediction_str = json.dumps(prediction, ensure_ascii=False, indent=2)
        else:
            prediction_str = str(prediction)
        
        # Prepare evaluation input
        eval_input = {
            "input": input_text or "Agent execution",
            "prediction": prediction_str
        }
        
        if reference:
            if isinstance(reference, dict):
                reference_str = json.dumps(reference, ensure_ascii=False, indent=2)
            else:
                reference_str = str(reference)
            eval_input["reference"] = reference_str
        
        # Run evaluation
        result = evaluator.evaluate(**eval_input)
        
        # Parse result
        if isinstance(result, dict):
            score = result.get("score", 0.0)
            reasoning = result.get("reasoning", "")
            passed = result.get("value", "N") == "Y" if "value" in result else score >= 0.7
        else:
            # Fallback parsing
            score = 0.5
            reasoning = str(result)
            passed = False
        
        return {
            "score": score,
            "reasoning": reasoning,
            "passed": passed,
            "raw_result": result
        }
        
    except Exception as e:
        logger.error(f"Error evaluating result: {e}")
        return {
            "score": None,
            "reasoning": f"Evaluation error: {str(e)}",
            "passed": False,
            "error": str(e)
        }


def evaluate_agent_result_simple(
    agent_type: str,
    prediction: Dict[str, Any],
    reference: Optional[Dict[str, Any]] = None,
    input_text: Optional[str] = None
) -> Dict[str, Any]:
    """
    Simple wrapper to create evaluator and evaluate in one call
    
    Args:
        agent_type: Type of agent
        prediction: Agent result
        reference: Optional reference
        input_text: Optional input text
        
    Returns:
        Evaluation result
    """
    evaluator = create_agent_evaluator(agent_type)
    return evaluate_agent_result(evaluator, prediction, reference, input_text)

