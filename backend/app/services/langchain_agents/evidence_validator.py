"""Evidence Validator for Level 1 validation (evidence check)"""
from typing import Dict, Any, List
from langchain_core.documents import Document
import logging

logger = logging.getLogger(__name__)


class EvidenceValidator:
    """Специализированный валидатор для проверки наличия evidence в документах"""
    
    def validate_evidence(
        self,
        finding: Dict[str, Any],
        source_docs: List[Document],
        min_matches: int = 1
    ) -> Dict[str, Any]:
        """
        Проверяет наличие evidence для finding в исходных документах
        
        Args:
            finding: Finding to validate
            source_docs: Source documents
            min_matches: Minimum number of matches required
            
        Returns:
            Validation result with evidence details
        """
        try:
            finding_text = self._extract_finding_text(finding)
            
            if not finding_text:
                return {
                    "has_evidence": False,
                    "matches": 0,
                    "source_documents": [],
                    "confidence": 0.0,
                    "reasoning": "Finding text is empty"
                }
            
            # Extract key phrases
            key_phrases = self._extract_key_phrases(finding_text)
            
            # Search in documents
            matches = []
            source_documents = []
            
            for doc in source_docs:
                doc_content = doc.page_content.lower() if hasattr(doc, 'page_content') else str(doc).lower()
                source_file = doc.metadata.get('source_file', 'unknown') if hasattr(doc, 'metadata') else 'unknown'
                
                # Count matches
                doc_matches = sum(1 for phrase in key_phrases if phrase.lower() in doc_content)
                
                if doc_matches > 0:
                    matches.append({
                        "source": source_file,
                        "matches": doc_matches,
                        "key_phrases_found": [p for p in key_phrases if p.lower() in doc_content]
                    })
                    if source_file not in source_documents:
                        source_documents.append(source_file)
            
            total_matches = sum(m["matches"] for m in matches)
            has_evidence = total_matches >= min_matches
            confidence = min(1.0, total_matches / max(1, len(key_phrases)))
            
            return {
                "has_evidence": has_evidence,
                "matches": total_matches,
                "source_documents": source_documents,
                "match_details": matches,
                "confidence": confidence,
                "reasoning": f"Found {total_matches} matches in {len(source_documents)} documents" if has_evidence else f"Only {total_matches} matches found, need {min_matches}"
            }
            
        except Exception as e:
            logger.error(f"Error in evidence validation: {e}", exc_info=True)
            return {
                "has_evidence": False,
                "matches": 0,
                "source_documents": [],
                "confidence": 0.0,
                "reasoning": f"Error: {str(e)}"
            }
    
    def _extract_finding_text(self, finding: Dict[str, Any]) -> str:
        """Извлекает текстовое представление finding"""
        text_fields = ["description", "text", "content", "finding", "result", "summary"]
        
        for field in text_fields:
            if field in finding and finding[field]:
                return str(finding[field])
        
        return str(finding)
    
    def _extract_key_phrases(self, text: str) -> List[str]:
        """Извлекает ключевые фразы из текста"""
        words = text.split()
        stop_words = {"и", "в", "на", "с", "по", "для", "от", "до", "из", "к", "о", "об", "the", "a", "an", "is", "are", "was", "were"}
        key_words = [w for w in words if len(w) > 3 and w.lower() not in stop_words]
        
        return key_words[:5]

