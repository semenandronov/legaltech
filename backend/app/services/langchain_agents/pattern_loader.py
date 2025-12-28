"""Pattern Loader Service for loading saved patterns from LangGraph Store"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.services.langchain_agents.store_service import LangGraphStoreService
from datetime import datetime
import logging
import asyncio

logger = logging.getLogger(__name__)


class PatternLoader:
    """Service for loading saved patterns from LangGraph Store for reuse in analysis"""
    
    def __init__(self, db: Session):
        """Initialize pattern loader
        
        Args:
            db: Database session
        """
        self.db = db
        self.store_service = LangGraphStoreService(db)
        logger.info("✅ Pattern Loader initialized")
    
    async def load_similar_patterns(
        self,
        case_type: str,
        agent_name: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Load similar patterns for a case type and agent
        
        Args:
            case_type: Type of case (e.g., "supply_contract", "employment_contract")
            agent_name: Name of the agent (e.g., "risk", "discrepancy", "key_facts")
            limit: Maximum number of patterns to return
            
        Returns:
            List of pattern dictionaries
        """
        try:
            # Normalize case_type
            case_type_normalized = case_type.lower().replace(" ", "_").replace("-", "_")
            
            # Namespace format: {agent_name}_patterns/{case_type}
            namespace = f"{agent_name}_patterns/{case_type_normalized}"
            
            # Search for patterns in this namespace
            patterns = await self.store_service.search_precedents(
                namespace=namespace,
                limit=limit
            )
            
            logger.info(f"Loaded {len(patterns)} patterns from namespace {namespace}")
            return patterns
            
        except Exception as e:
            logger.error(f"Error loading patterns for {agent_name}/{case_type}: {e}", exc_info=True)
            return []
    
    async def load_risk_patterns(
        self,
        case_type: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Load saved risk patterns for a case type
        
        Args:
            case_type: Type of case
            limit: Maximum number of patterns to return
            
        Returns:
            List of risk pattern dictionaries
        """
        return await self.load_similar_patterns(case_type, "risk", limit)
    
    async def load_discrepancy_patterns(
        self,
        case_type: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Load saved discrepancy patterns for a case type
        
        Args:
            case_type: Type of case
            limit: Maximum number of patterns to return
            
        Returns:
            List of discrepancy pattern dictionaries
        """
        return await self.load_similar_patterns(case_type, "discrepancy", limit)
    
    async def load_key_facts_patterns(
        self,
        case_type: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Load saved key facts patterns for a case type
        
        Args:
            case_type: Type of case
            limit: Maximum number of patterns to return
            
        Returns:
            List of key facts pattern dictionaries
        """
        return await self.load_similar_patterns(case_type, "key_facts", limit)
    
    def format_patterns_for_prompt(
        self,
        patterns: List[Dict[str, Any]],
        pattern_type: str = "risks"
    ) -> str:
        """
        Format patterns for inclusion in agent prompt
        
        Args:
            patterns: List of pattern dictionaries
            pattern_type: Type of patterns ("risks", "discrepancies", "facts")
            
        Returns:
            Formatted string for prompt
        """
        if not patterns:
            return ""
        
        formatted = []
        formatted.append(f"\nИзвестные типичные {pattern_type} для этого типа контрактов (из предыдущих анализов):\n")
        
        for i, pattern in enumerate(patterns[:10], 1):  # Top 10 patterns
            value = pattern.get("value", {})
            
            if pattern_type == "risks":
                risk_name = value.get("risk_name", "Unknown Risk")
                risk_category = value.get("risk_category", "")
                description = value.get("description", "")
                formatted.append(f"{i}. {risk_name} ({risk_category}): {description[:150]}...")
            elif pattern_type == "discrepancies":
                discrepancy_type = value.get("type", "Unknown")
                description = value.get("description", "")
                severity = value.get("severity", "")
                formatted.append(f"{i}. {discrepancy_type} ({severity}): {description[:150]}...")
            elif pattern_type == "facts":
                fact_type = value.get("fact_type", "Unknown")
                value_text = value.get("value", "")
                formatted.append(f"{i}. {fact_type}: {value_text[:150]}...")
            else:
                # Generic format
                formatted.append(f"{i}. {str(value)[:150]}...")
        
        formatted.append("\nИспользуй эти известные паттерны как отправную точку, но также ищи новые, специфичные для данного дела.")
        return "\n".join(formatted)
    
    async def get_case_type(self, case_id: str) -> str:
        """
        Get case type for a case
        
        Args:
            case_id: Case identifier
            
        Returns:
            Case type string (normalized)
        """
        try:
            from app.models.case import Case
            case = self.db.query(Case).filter(Case.id == case_id).first()
            if case and case.case_type:
                return case.case_type.lower().replace(" ", "_").replace("-", "_")
            return "general"
        except Exception as e:
            logger.warning(f"Error getting case type for {case_id}: {e}")
            return "general"


def get_pattern_loader(db: Session) -> Optional[PatternLoader]:
    """Get pattern loader instance"""
    try:
        return PatternLoader(db)
    except Exception as e:
        logger.warning(f"Failed to create PatternLoader: {e}")
        return None

