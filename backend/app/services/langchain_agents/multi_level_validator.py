"""Multi-level validator for systematic validation of agent results"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from langchain_core.documents import Document
from app.services.llm_factory import create_llm
from langchain_core.messages import SystemMessage, HumanMessage
import logging

logger = logging.getLogger(__name__)


@dataclass
class EvidenceCheck:
    """Level 1: Evidence check result"""
    passed: bool
    found_in_docs: bool
    source_documents: List[str]
    confidence: float
    reasoning: str


@dataclass
class ConsistencyCheck:
    """Level 2: Consistency check result"""
    passed: bool
    conflicts: List[Dict[str, Any]]
    consistent_with: List[str]
    confidence: float
    reasoning: str


@dataclass
class ConfidenceScore:
    """Level 3: Confidence scoring result"""
    score: float
    factors: Dict[str, float]
    reasoning: str


@dataclass
class CircularVerification:
    """Level 4: Circular verification result"""
    confirmed: bool
    verifying_agent: str
    agreement_score: float
    reasoning: str


@dataclass
class ValidationResult:
    """Complete validation result with all 4 levels"""
    is_valid: bool
    level_1: EvidenceCheck
    level_2: ConsistencyCheck
    level_3: ConfidenceScore
    level_4: CircularVerification
    overall_confidence: float
    issues: List[str]
    recommendations: List[str]


class MultiLevelValidator:
    """4-уровневая валидация результатов агентов"""
    
    def __init__(self):
        """Initialize multi-level validator"""
        try:
            self.llm = create_llm(temperature=0.1)  # Низкая температура для консистентности
            logger.info("✅ Multi-Level Validator initialized")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            raise
    
    async def validate_finding(
        self,
        finding: Dict[str, Any],
        source_docs: List[Document],
        other_findings: List[Dict[str, Any]],
        verifying_agent: Optional[str] = None
    ) -> ValidationResult:
        """
        Валидация на 4 уровнях
        
        Args:
            finding: Finding to validate (result from agent)
            source_docs: Source documents for evidence check
            other_findings: Other findings for consistency check
            verifying_agent: Optional agent name for circular verification
            
        Returns:
            ValidationResult with all 4 levels
        """
        try:
            logger.info(f"Validating finding: {finding.get('type', 'unknown')}...")
            
            # Level 1: Evidence check
            evidence_check = self._check_evidence(finding, source_docs)
            
            # Level 2: Consistency check
            consistency_check = self._check_consistency(finding, other_findings)
            
            # Level 3: Confidence scoring
            confidence_score = self._calculate_confidence(finding, evidence_check, consistency_check)
            
            # Level 4: Circular verification (if verifying agent provided)
            if verifying_agent:
                circular_verification = await self._circular_verify(finding, verifying_agent, source_docs)
            else:
                circular_verification = CircularVerification(
                    confirmed=True,
                    verifying_agent="none",
                    agreement_score=1.0,
                    reasoning="Circular verification skipped (no verifying agent provided)"
                )
            
            # Determine overall validity
            is_valid = all([
                evidence_check.passed,
                consistency_check.passed,
                confidence_score.score > 0.7,
                circular_verification.confirmed
            ])
            
            # Calculate overall confidence
            overall_confidence = (
                evidence_check.confidence * 0.3 +
                consistency_check.confidence * 0.2 +
                confidence_score.score * 0.3 +
                circular_verification.agreement_score * 0.2
            )
            
            # Collect issues and recommendations
            issues = []
            recommendations = []
            
            if not evidence_check.passed:
                issues.append("Finding not found in source documents")
                recommendations.append("Review source documents or refine finding")
            
            if not consistency_check.passed:
                issues.append(f"Finding conflicts with {len(consistency_check.conflicts)} other findings")
                recommendations.append("Review conflicts and reconcile findings")
            
            if confidence_score.score < 0.7:
                issues.append(f"Low confidence score: {confidence_score.score:.2f}")
                recommendations.append("Gather more evidence or refine finding")
            
            if not circular_verification.confirmed:
                issues.append("Circular verification failed")
                recommendations.append("Re-verify finding with different agent")
            
            return ValidationResult(
                is_valid=is_valid,
                level_1=evidence_check,
                level_2=consistency_check,
                level_3=confidence_score,
                level_4=circular_verification,
                overall_confidence=overall_confidence,
                issues=issues,
                recommendations=recommendations
            )
            
        except Exception as e:
            logger.error(f"Error in multi-level validation: {e}", exc_info=True)
            # Return invalid result on error
            return ValidationResult(
                is_valid=False,
                level_1=EvidenceCheck(False, False, [], 0.0, f"Error: {str(e)}"),
                level_2=ConsistencyCheck(False, [], [], 0.0, f"Error: {str(e)}"),
                level_3=ConfidenceScore(0.0, {}, f"Error: {str(e)}"),
                level_4=CircularVerification(False, "none", 0.0, f"Error: {str(e)}"),
                overall_confidence=0.0,
                issues=[f"Validation error: {str(e)}"],
                recommendations=["Review finding manually"]
            )
    
    def _check_evidence(
        self,
        finding: Dict[str, Any],
        source_docs: List[Document]
    ) -> EvidenceCheck:
        """
        Level 1: Проверяет, есть ли finding в исходных документах
        
        Args:
            finding: Finding to check
            source_docs: Source documents
            
        Returns:
            EvidenceCheck result
        """
        try:
            # Извлекаем ключевые элементы finding для поиска
            finding_text = self._extract_finding_text(finding)
            
            if not finding_text:
                return EvidenceCheck(
                    passed=False,
                    found_in_docs=False,
                    source_documents=[],
                    confidence=0.0,
                    reasoning="Finding text is empty"
                )
            
            # Ищем в документах
            found_docs = []
            found_count = 0
            
            for doc in source_docs:
                doc_content = doc.page_content.lower() if hasattr(doc, 'page_content') else str(doc).lower()
                finding_lower = finding_text.lower()
                
                # Проверяем наличие ключевых слов
                key_phrases = self._extract_key_phrases(finding_text)
                matches = sum(1 for phrase in key_phrases if phrase.lower() in doc_content)
                
                if matches > 0:
                    found_docs.append(doc.metadata.get('source_file', 'unknown') if hasattr(doc, 'metadata') else 'unknown')
                    found_count += matches
            
            # Определяем, найден ли finding
            found_in_docs = found_count > 0
            confidence = min(1.0, found_count / max(1, len(key_phrases)))
            
            reasoning = f"Found {found_count} matches in {len(found_docs)} documents" if found_in_docs else "No matches found in source documents"
            
            return EvidenceCheck(
                passed=found_in_docs,
                found_in_docs=found_in_docs,
                source_documents=list(set(found_docs)),
                confidence=confidence,
                reasoning=reasoning
            )
            
        except Exception as e:
            logger.error(f"Error in evidence check: {e}", exc_info=True)
            return EvidenceCheck(
                passed=False,
                found_in_docs=False,
                source_documents=[],
                confidence=0.0,
                reasoning=f"Error: {str(e)}"
            )
    
    def _check_consistency(
        self,
        finding: Dict[str, Any],
        other_findings: List[Dict[str, Any]]
    ) -> ConsistencyCheck:
        """
        Level 2: Проверяет, не противоречит ли finding другим findings
        
        Args:
            finding: Finding to check
            other_findings: Other findings to compare against
            
        Returns:
            ConsistencyCheck result
        """
        try:
            conflicts = []
            consistent_with = []
            
            finding_text = self._extract_finding_text(finding)
            finding_type = finding.get("type", finding.get("agent_name", "unknown"))
            
            for other in other_findings:
                other_text = self._extract_finding_text(other)
                other_type = other.get("type", other.get("agent_name", "unknown"))
                
                # Пропускаем findings того же типа
                if finding_type == other_type:
                    continue
                
                # Проверяем на противоречия через LLM
                conflict = self._detect_conflict(finding_text, other_text)
                
                if conflict:
                    conflicts.append({
                        "finding": other_text[:100],
                        "type": other_type,
                        "reason": conflict
                    })
                else:
                    consistent_with.append(other_type)
            
            # Определяем, прошла ли проверка
            passed = len(conflicts) == 0
            confidence = 1.0 - (len(conflicts) / max(1, len(other_findings)))
            
            reasoning = f"No conflicts found" if passed else f"Found {len(conflicts)} conflicts with other findings"
            
            return ConsistencyCheck(
                passed=passed,
                conflicts=conflicts,
                consistent_with=consistent_with,
                confidence=confidence,
                reasoning=reasoning
            )
            
        except Exception as e:
            logger.error(f"Error in consistency check: {e}", exc_info=True)
            return ConsistencyCheck(
                passed=False,
                conflicts=[],
                consistent_with=[],
                confidence=0.0,
                reasoning=f"Error: {str(e)}"
            )
    
    def _calculate_confidence(
        self,
        finding: Dict[str, Any],
        evidence_check: EvidenceCheck,
        consistency_check: ConsistencyCheck
    ) -> ConfidenceScore:
        """
        Level 3: Рассчитывает confidence score для finding
        
        Args:
            finding: Finding to score
            evidence_check: Level 1 result
            consistency_check: Level 2 result
            
        Returns:
            ConfidenceScore result
        """
        try:
            factors = {}
            
            # Factor 1: Evidence strength
            factors["evidence_strength"] = evidence_check.confidence
            
            # Factor 2: Consistency
            factors["consistency"] = consistency_check.confidence
            
            # Factor 3: Finding completeness
            finding_completeness = self._assess_completeness(finding)
            factors["completeness"] = finding_completeness
            
            # Factor 4: Source quality (if available)
            source_quality = finding.get("source_quality", 0.8)  # Default
            factors["source_quality"] = source_quality
            
            # Factor 5: Agent confidence (if available)
            agent_confidence = finding.get("confidence", finding.get("agent_confidence", 0.8))
            factors["agent_confidence"] = agent_confidence
            
            # Weighted average
            weights = {
                "evidence_strength": 0.3,
                "consistency": 0.2,
                "completeness": 0.2,
                "source_quality": 0.15,
                "agent_confidence": 0.15
            }
            
            score = sum(factors.get(key, 0.5) * weights.get(key, 0.0) for key in weights.keys())
            
            reasoning = f"Confidence score: {score:.2f} based on evidence ({factors['evidence_strength']:.2f}), consistency ({factors['consistency']:.2f}), completeness ({factors['completeness']:.2f})"
            
            return ConfidenceScore(
                score=score,
                factors=factors,
                reasoning=reasoning
            )
            
        except Exception as e:
            logger.error(f"Error calculating confidence: {e}", exc_info=True)
            return ConfidenceScore(
                score=0.5,
                factors={},
                reasoning=f"Error: {str(e)}"
            )
    
    async def _circular_verify(
        self,
        finding: Dict[str, Any],
        verifying_agent: str,
        source_docs: List[Document]
    ) -> CircularVerification:
        """
        Level 4: Circular verification - другой агент подтверждает finding
        
        Args:
            finding: Finding to verify
            verifying_agent: Agent name to use for verification
            source_docs: Source documents
            
        Returns:
            CircularVerification result
        """
        try:
            finding_text = self._extract_finding_text(finding)
            
            # Используем LLM для симуляции другого агента
            verification_prompt = f"""Ты {verifying_agent} агент. Проверь следующее finding:

Finding: {finding_text}

Исходные документы:
{self._format_docs_for_prompt(source_docs[:3])}

Подтверди или опровергни это finding. Верни JSON:
{{
    "confirmed": true/false,
    "agreement_score": 0.0-1.0,
    "reasoning": "объяснение"
}}"""
            
            messages = [
                SystemMessage(content=f"Ты {verifying_agent} агент для проверки findings."),
                HumanMessage(content=verification_prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Парсим JSON
            import json
            import re
            
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                verification_result = json.loads(json_match.group())
            else:
                verification_result = json.loads(response_text)
            
            confirmed = verification_result.get("confirmed", False)
            agreement_score = verification_result.get("agreement_score", 0.5)
            reasoning = verification_result.get("reasoning", "No reasoning provided")
            
            return CircularVerification(
                confirmed=confirmed,
                verifying_agent=verifying_agent,
                agreement_score=agreement_score,
                reasoning=reasoning
            )
            
        except Exception as e:
            logger.error(f"Error in circular verification: {e}", exc_info=True)
            return CircularVerification(
                confirmed=False,
                verifying_agent=verifying_agent,
                agreement_score=0.0,
                reasoning=f"Error: {str(e)}"
            )
    
    def _extract_finding_text(self, finding: Dict[str, Any]) -> str:
        """Извлекает текстовое представление finding"""
        # Пробуем разные поля
        text_fields = ["description", "text", "content", "finding", "result", "summary"]
        
        for field in text_fields:
            if field in finding and finding[field]:
                return str(finding[field])
        
        # Если не найдено, конвертируем весь словарь
        return str(finding)
    
    def _extract_key_phrases(self, text: str) -> List[str]:
        """Извлекает ключевые фразы из текста"""
        # Простая эвристика: берем существительные и важные слова
        words = text.split()
        # Фильтруем стоп-слова
        stop_words = {"и", "в", "на", "с", "по", "для", "от", "до", "из", "к", "о", "об", "the", "a", "an", "is", "are", "was", "were"}
        key_words = [w for w in words if len(w) > 3 and w.lower() not in stop_words]
        
        # Берем первые 5 ключевых слов
        return key_words[:5]
    
    def _detect_conflict(
        self,
        finding1: str,
        finding2: str
    ) -> Optional[str]:
        """Обнаруживает конфликт между двумя findings через LLM"""
        try:
            conflict_prompt = f"""Проверь, противоречат ли друг другу эти два findings:

Finding 1: {finding1[:200]}
Finding 2: {finding2[:200]}

Верни JSON:
{{
    "conflict": true/false,
    "reason": "объяснение если есть конфликт"
}}"""
            
            messages = [
                SystemMessage(content="Ты эксперт по обнаружению противоречий в юридических findings."),
                HumanMessage(content=conflict_prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            import json
            import re
            
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = json.loads(response_text)
            
            if result.get("conflict", False):
                return result.get("reason", "Conflict detected")
            
            return None
            
        except Exception as e:
            logger.warning(f"Error detecting conflict: {e}")
            return None
    
    def _assess_completeness(self, finding: Dict[str, Any]) -> float:
        """Оценивает полноту finding"""
        # Проверяем наличие ключевых полей
        required_fields = ["description", "type", "confidence"]
        optional_fields = ["evidence", "reasoning", "source", "metadata"]
        
        required_count = sum(1 for field in required_fields if field in finding and finding[field])
        optional_count = sum(1 for field in optional_fields if field in finding and finding[field])
        
        completeness = (required_count / len(required_fields)) * 0.7 + (optional_count / len(optional_fields)) * 0.3
        
        return completeness
    
    def _format_docs_for_prompt(self, docs: List[Document]) -> str:
        """Форматирует документы для промпта"""
        formatted = []
        for i, doc in enumerate(docs[:3], 1):
            content = doc.page_content[:200] if hasattr(doc, 'page_content') else str(doc)[:200]
            source = doc.metadata.get('source_file', 'unknown') if hasattr(doc, 'metadata') else 'unknown'
            formatted.append(f"Документ {i} ({source}): {content}...")
        
        return "\n".join(formatted)

