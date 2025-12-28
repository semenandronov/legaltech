"""Prompt Improvement Service for automatic prompt optimization based on feedback"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.services.langchain_agents.learning_service import ContinuousLearningService
from app.services.langchain_agents.store_service import LangGraphStoreService
from app.config import config
from datetime import datetime, timedelta
import logging
import json

logger = logging.getLogger(__name__)


class PromptImprovementService:
    """Service for analyzing feedback and improving prompts automatically"""
    
    # Threshold for prompt improvement (5% improvement)
    IMPROVEMENT_THRESHOLD = 0.05
    
    def __init__(self, db: Session):
        """Initialize prompt improvement service
        
        Args:
            db: Database session
        """
        self.db = db
        self.learning_service = ContinuousLearningService(db)
        self.store_service = LangGraphStoreService(db)
        logger.info("✅ Prompt Improvement Service initialized")
    
    async def analyze_feedback(
        self,
        agent_name: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Analyze feedback for an agent over time
        
        Args:
            agent_name: Name of the agent
            days: Number of days to analyze
            
        Returns:
            Analysis result with recommendations
        """
        try:
            # Load feedback from Store
            namespace = f"feedback/{agent_name}"
            all_feedback = await self.store_service.search_precedents(
                namespace=namespace,
                limit=1000
            )
            
            # Filter by date
            cutoff_date = datetime.now() - timedelta(days=days)
            recent_feedback = [
                f for f in all_feedback
                if datetime.fromisoformat(f.get("metadata", {}).get("saved_at", "2000-01-01")) > cutoff_date
            ]
            
            if not recent_feedback:
                return {
                    "agent_name": agent_name,
                    "feedback_count": 0,
                    "recommendations": []
                }
            
            # Analyze feedback patterns
            positive_count = 0
            negative_count = 0
            common_issues = []
            
            for feedback_item in recent_feedback:
                feedback_text = feedback_item.get("value", {}).get("feedback", "").lower()
                if any(word in feedback_text for word in ["хорошо", "отлично", "правильно", "хороший"]):
                    positive_count += 1
                elif any(word in feedback_text for word in ["неправильно", "ошибка", "плохо", "не нашел", "забыл"]):
                    negative_count += 1
                    # Extract issue
                    if "не нашел" in feedback_text or "забыл" in feedback_text:
                        common_issues.append("missing_items")
                    elif "неправильно" in feedback_text or "ошибка" in feedback_text:
                        common_issues.append("incorrect_analysis")
            
            success_rate = positive_count / (positive_count + negative_count) if (positive_count + negative_count) > 0 else 0.0
            
            recommendations = []
            if success_rate < 0.7:  # Less than 70% positive feedback
                recommendations.append({
                    "type": "improve_prompt",
                    "reason": f"Low success rate: {success_rate:.0%}",
                    "suggested_action": "Generate improved prompt based on feedback"
                })
            
            if "missing_items" in common_issues:
                recommendations.append({
                    "type": "add_instructions",
                    "reason": "Common issue: missing items in analysis",
                    "suggested_action": "Add explicit instructions to check for all items"
                })
            
            return {
                "agent_name": agent_name,
                "feedback_count": len(recent_feedback),
                "positive_count": positive_count,
                "negative_count": negative_count,
                "success_rate": success_rate,
                "common_issues": list(set(common_issues)),
                "recommendations": recommendations
            }
            
        except Exception as e:
            logger.error(f"Error analyzing feedback for {agent_name}: {e}", exc_info=True)
            return {
                "agent_name": agent_name,
                "feedback_count": 0,
                "recommendations": [],
                "error": str(e)
            }
    
    async def improve_prompt_from_feedback(
        self,
        agent_name: str,
        feedback_examples: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[str]:
        """
        Improve prompt based on feedback examples
        
        Args:
            agent_name: Name of the agent
            feedback_examples: Optional list of feedback examples (if None, loads from Store)
            
        Returns:
            Improved prompt text or None
        """
        try:
            # Load feedback if not provided
            if feedback_examples is None:
                namespace = f"feedback/{agent_name}"
                feedback_items = await self.store_service.search_precedents(
                    namespace=namespace,
                    limit=50
                )
                feedback_examples = [f.get("value", {}) for f in feedback_items]
            
            if not feedback_examples:
                logger.warning(f"No feedback examples found for {agent_name}")
                return None
            
            # Separate positive and negative feedback
            positive_examples = []
            negative_examples = []
            
            for example in feedback_examples:
                feedback_text = example.get("feedback", "").lower()
                if any(word in feedback_text for word in ["хорошо", "отлично", "правильно"]):
                    positive_examples.append(example)
                elif any(word in feedback_text for word in ["неправильно", "ошибка", "плохо"]):
                    negative_examples.append(example)
            
            # Use learning service to improve prompt
            improved_prompt = await self.learning_service.improve_prompt(
                agent_name=agent_name,
                successful_examples=positive_examples[:10],  # Top 10 positive
                failed_examples=negative_examples[:5]  # Top 5 negative
            )
            
            logger.info(f"Improved prompt for {agent_name} based on {len(feedback_examples)} feedback examples")
            return improved_prompt
            
        except Exception as e:
            logger.error(f"Error improving prompt from feedback: {e}", exc_info=True)
            return None
    
    async def evaluate_prompt_improvement(
        self,
        agent_name: str,
        old_prompt: str,
        new_prompt: str
    ) -> Dict[str, Any]:
        """
        Evaluate if new prompt is better than old one
        
        Args:
            agent_name: Name of the agent
            old_prompt: Old prompt text
            new_prompt: New prompt text
            
        Returns:
            Evaluation result with improvement score
        """
        try:
            # Load performance metrics for old and new prompts
            # This is a simplified evaluation - in production, would use A/B testing
            
            # For now, we assume new prompt is better if it's longer and more detailed
            old_length = len(old_prompt)
            new_length = len(new_prompt)
            
            improvement_ratio = (new_length - old_length) / old_length if old_length > 0 else 0.0
            
            # Estimate improvement (in production, would use actual metrics)
            estimated_improvement = min(0.1, improvement_ratio * 0.05)  # Max 10% improvement estimate
            
            return {
                "agent_name": agent_name,
                "estimated_improvement": estimated_improvement,
                "improvement_ratio": improvement_ratio,
                "recommendation": "adopt" if estimated_improvement >= self.IMPROVEMENT_THRESHOLD else "keep_testing"
            }
            
        except Exception as e:
            logger.error(f"Error evaluating prompt improvement: {e}", exc_info=True)
            return {
                "agent_name": agent_name,
                "estimated_improvement": 0.0,
                "recommendation": "error"
            }
    
    async def auto_improve_prompts(
        self,
        agent_names: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Automatically improve prompts for agents based on feedback
        
        Args:
            agent_names: Optional list of agent names (if None, improves all)
            
        Returns:
            Dictionary with improvement results
        """
        if agent_names is None:
            agent_names = ["timeline", "key_facts", "discrepancy", "risk", "summary"]
        
        results = {}
        
        for agent_name in agent_names:
            try:
                # Analyze feedback
                analysis = await self.analyze_feedback(agent_name, days=30)
                
                if analysis.get("feedback_count", 0) < 10:
                    # Not enough feedback
                    results[agent_name] = {
                        "status": "skipped",
                        "reason": "insufficient_feedback",
                        "feedback_count": analysis.get("feedback_count", 0)
                    }
                    continue
                
                # Check if improvement is needed
                success_rate = analysis.get("success_rate", 1.0)
                if success_rate >= 0.85:
                    # Already good
                    results[agent_name] = {
                        "status": "skipped",
                        "reason": "already_good",
                        "success_rate": success_rate
                    }
                    continue
                
                # Improve prompt
                improved_prompt = await self.improve_prompt_from_feedback(agent_name)
                
                if improved_prompt:
                    # Get current prompt
                    from app.services.langchain_agents.prompts import get_agent_prompt
                    current_prompt = get_agent_prompt(agent_name)
                    
                    # Evaluate improvement
                    evaluation = await self.evaluate_prompt_improvement(
                        agent_name,
                        current_prompt,
                        improved_prompt
                    )
                    
                    results[agent_name] = {
                        "status": "improved" if evaluation.get("recommendation") == "adopt" else "needs_testing",
                        "estimated_improvement": evaluation.get("estimated_improvement", 0.0),
                        "success_rate": success_rate
                    }
                else:
                    results[agent_name] = {
                        "status": "failed",
                        "reason": "could_not_improve"
                    }
                    
            except Exception as e:
                logger.error(f"Error auto-improving prompt for {agent_name}: {e}", exc_info=True)
                results[agent_name] = {
                    "status": "error",
                    "error": str(e)
                }
        
        return results

