"""LLM-as-Judge for citation verification"""
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
import logging

logger = logging.getLogger(__name__)


class CitationLLMJudge:
    """
    Phase 3: LLM-as-Judge evaluator for citation verification
    
    Uses LLM to evaluate whether sources support a claim.
    """
    
    def __init__(self, llm: Optional[Any] = None):
        """
        Initialize CitationLLMJudge
        
        Args:
            llm: LLM instance (optional, will create if not provided)
        """
        self.llm = llm
        if not self.llm:
            from app.services.llm_factory import create_llm
            self.llm = create_llm(temperature=0.1)
    
    def judge_citation(
        self,
        claim_text: str,
        source_text: str,
        source_metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Judge whether a source supports a claim using LLM
        
        Args:
            claim_text: The claim to verify
            source_text: Text from the source document
            source_metadata: Optional metadata about the source
            
        Returns:
            Dictionary with judgment result:
            {
                "verified": bool,
                "confidence": float (0.0-1.0),
                "reasoning": str,
                "support_level": str  # "strong", "moderate", "weak", "none"
            }
        """
        from langchain_core.messages import SystemMessage, HumanMessage
        
        system_prompt = """Ты эксперт по верификации цитат и утверждений.
Твоя задача - оценить, подтверждает ли предоставленный источник текста утверждение.

Оценивай:
1. Подтверждает ли источник утверждение напрямую
2. Подтверждает ли источник утверждение косвенно (подразумевает)
3. Противоречит ли источник утверждению
4. Нейтрален ли источник к утверждению

Верни оценку с уровнем поддержки: "strong", "moderate", "weak", или "none"."""
        
        user_prompt = f"""Утверждение для проверки:
{claim_text}

Источник:
{source_text}

Оцени, подтверждает ли источник утверждение. Верни JSON с полями:
- verified: true/false (подтверждает ли источник утверждение)
- confidence: число от 0.0 до 1.0 (уверенность в оценке)
- reasoning: объяснение оценки (1-2 предложения)
- support_level: "strong", "moderate", "weak", или "none"

Отвечай ТОЛЬКО валидным JSON."""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        try:
            response = self.llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON response
            import json
            import re
            
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_text = json_match.group(0)
                data = json.loads(json_text)
                
                return {
                    "verified": data.get("verified", False),
                    "confidence": float(data.get("confidence", 0.0)),
                    "reasoning": data.get("reasoning", ""),
                    "support_level": data.get("support_level", "none")
                }
            else:
                logger.warning("Could not parse JSON from LLM judge response")
                return {
                    "verified": False,
                    "confidence": 0.0,
                    "reasoning": "Failed to parse LLM response",
                    "support_level": "none"
                }
        except Exception as e:
            logger.error(f"Error in LLM judge evaluation: {e}", exc_info=True)
            return {
                "verified": False,
                "confidence": 0.0,
                "reasoning": f"Error: {str(e)}",
                "support_level": "none"
            }
    
    def judge_multiple_sources(
        self,
        claim_text: str,
        sources: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Judge claim against multiple sources
        
        Args:
            claim_text: The claim to verify
            sources: List of source dictionaries with 'text' and optional 'metadata'
            
        Returns:
            Dictionary with aggregated judgment result
        """
        judgments = []
        for source in sources:
            source_text = source.get("text", "") or source.get("snippet", "")
            source_metadata = source.get("metadata") or source
            
            judgment = self.judge_citation(claim_text, source_text, source_metadata)
            judgments.append(judgment)
        
        # Aggregate judgments
        verified_count = sum(1 for j in judgments if j.get("verified", False))
        total_confidence = sum(j.get("confidence", 0.0) for j in judgments)
        avg_confidence = total_confidence / len(judgments) if judgments else 0.0
        
        # Consider verified if at least one source strongly supports
        is_verified = verified_count > 0 and avg_confidence > 0.5
        
        return {
            "verified": is_verified,
            "confidence": avg_confidence,
            "verified_sources_count": verified_count,
            "total_sources_count": len(sources),
            "judgments": judgments,
            "reasoning": f"Verified by {verified_count}/{len(sources)} sources with average confidence {avg_confidence:.2f}"
        }
    
    def verify_with_llm_judge(
        self,
        claim_text: str,
        candidate_sources: List[Document]
    ) -> Dict[str, Any]:
        """
        Verify claim using LLM-as-judge against candidate sources
        
        Args:
            claim_text: Claim text to verify
            candidate_sources: List of candidate source documents
            
        Returns:
            Dictionary with verification result
        """
        if not candidate_sources:
            return {
                "verified": False,
                "confidence": 0.0,
                "reasoning": "No candidate sources provided"
            }
        
        # Prepare sources for judgment
        sources_for_judgment = []
        for doc in candidate_sources:
            sources_for_judgment.append({
                "text": doc.page_content,
                "metadata": doc.metadata
            })
        
        # Judge against all sources
        judgment = self.judge_multiple_sources(claim_text, sources_for_judgment)
        
        return judgment


