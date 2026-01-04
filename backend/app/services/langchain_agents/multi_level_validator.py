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
class CrossAgentValidation:
    """Level 5: Cross-agent validation result"""
    passed: bool
    agent_name: str  # Name of the agent being validated
    related_agents: List[str]  # List of related agents checked
    conflicts: List[Dict[str, Any]]  # Conflicts with other agents
    agreements: List[Dict[str, Any]]  # Agreements with other agents
    consistency_score: float  # Consistency score across agents (0.0-1.0)
    reasoning: str


@dataclass
class ValidationResult:
    """Complete validation result with all 5 levels"""
    is_valid: bool
    level_1: EvidenceCheck
    level_2: ConsistencyCheck
    level_3: ConfidenceScore
    level_4: CircularVerification
    level_5: Optional[CrossAgentValidation] = None  # Optional cross-agent validation
    overall_confidence: float = 0.0
    issues: List[str] = None
    recommendations: List[str] = None
    
    def __post_init__(self):
        """Initialize default values"""
        if self.issues is None:
            self.issues = []
        if self.recommendations is None:
            self.recommendations = []


class MultiLevelValidator:
    """5-уровневая валидация результатов агентов"""
    
    # Пороги для разных типов дел (автоматическое определение)
    CASE_TYPE_THRESHOLDS = {
        "general": {
            "min_confidence": 0.7,
            "min_consistency": 0.7,
            "min_evidence": 0.6
        },
        "contract": {
            "min_confidence": 0.8,
            "min_consistency": 0.75,
            "min_evidence": 0.7
        },
        "litigation": {
            "min_confidence": 0.75,
            "min_consistency": 0.7,
            "min_evidence": 0.65
        },
        "compliance": {
            "min_confidence": 0.8,
            "min_consistency": 0.8,
            "min_evidence": 0.7
        }
    }
    
    def __init__(self, case_type: Optional[str] = None):
        """
        Initialize multi-level validator
        
        Args:
            case_type: Тип дела для автоматического определения порогов (general, contract, litigation, compliance)
        """
        try:
            self.llm = create_llm(temperature=0.1)  # Низкая температура для консистентности
            self.case_type = case_type or "general"
            self.thresholds = self.CASE_TYPE_THRESHOLDS.get(
                self.case_type.lower(),
                self.CASE_TYPE_THRESHOLDS["general"]
            )
            logger.info(f"✅ Multi-Level Validator initialized (case_type={self.case_type}, thresholds={self.thresholds})")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}")
            raise
    
    async def validate_finding(
        self,
        finding: Dict[str, Any],
        source_docs: List[Document],
        other_findings: List[Dict[str, Any]],
        verifying_agent: Optional[str] = None,
        agent_name: Optional[str] = None,
        other_agent_results: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> ValidationResult:
        """
        Валидация на 5 уровнях (включая cross-agent validation)
        
        Args:
            finding: Finding to validate (result from agent)
            source_docs: Source documents for evidence check
            other_findings: Other findings for consistency check
            verifying_agent: Optional agent name for circular verification
            agent_name: Name of the agent that produced this finding (for cross-agent validation)
            other_agent_results: Dictionary of results from other agents (agent_name -> result) for cross-agent validation
            
        Returns:
            ValidationResult with all 5 levels
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
            
            # Level 5: Cross-agent validation (если есть результаты других агентов)
            cross_agent_validation = None
            if agent_name and other_agent_results:
                cross_agent_validation = await self._cross_agent_validate(
                    finding=finding,
                    agent_name=agent_name,
                    other_agent_results=other_agent_results,
                    source_docs=source_docs
                )
            
            # Determine overall validity using case-specific thresholds
            min_confidence = self.thresholds["min_confidence"]
            min_consistency = self.thresholds["min_consistency"]
            
            is_valid = all([
                evidence_check.passed,
                consistency_check.passed,
                confidence_score.score >= min_confidence,
                circular_verification.confirmed
            ])
            
            # Если есть cross-agent validation, учитываем его
            if cross_agent_validation:
                is_valid = is_valid and (
                    cross_agent_validation.passed and 
                    cross_agent_validation.consistency_score >= min_consistency
                )
            
            # Calculate overall confidence (взвешенное среднее)
            weights = [0.25, 0.15, 0.25, 0.15, 0.20] if cross_agent_validation else [0.3, 0.2, 0.3, 0.2, 0.0]
            confidence_scores = [
                evidence_check.confidence,
                consistency_check.confidence,
                confidence_score.score,
                circular_verification.agreement_score,
                cross_agent_validation.consistency_score if cross_agent_validation else 1.0
            ]
            
            overall_confidence = sum(score * weight for score, weight in zip(confidence_scores, weights))
            
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
            
            if cross_agent_validation and not cross_agent_validation.passed:
                issues.append(
                    f"Cross-agent validation failed: {len(cross_agent_validation.conflicts)} conflicts "
                    f"with {', '.join(cross_agent_validation.related_agents)}"
                )
                recommendations.append("Review conflicts with other agents and reconcile")
            
            return ValidationResult(
                is_valid=is_valid,
                level_1=evidence_check,
                level_2=consistency_check,
                level_3=confidence_score,
                level_4=circular_verification,
                level_5=cross_agent_validation,
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
                level_5=None,
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
    
    async def _cross_agent_validate(
        self,
        finding: Dict[str, Any],
        agent_name: str,
        other_agent_results: Dict[str, Dict[str, Any]],
        source_docs: List[Document]
    ) -> CrossAgentValidation:
        """
        Level 5: Cross-agent validation - проверка согласованности между агентами
        
        Args:
            finding: Finding to validate
            agent_name: Name of the agent that produced this finding
            other_agent_results: Dictionary of results from other agents (agent_name -> result)
            source_docs: Source documents
            
        Returns:
            CrossAgentValidation result
        """
        try:
            finding_text = self._extract_finding_text(finding)
            
            # Определяем связанные агенты (например, timeline и key_facts связаны)
            related_agents_map = {
                "timeline": ["key_facts", "discrepancy"],
                "key_facts": ["timeline", "discrepancy", "risk"],
                "discrepancy": ["timeline", "key_facts", "risk"],
                "risk": ["key_facts", "discrepancy"],
                "summary": ["key_facts", "timeline", "risk"]
            }
            
            related_agent_names = related_agents_map.get(agent_name, list(other_agent_results.keys()))
            related_agents = [name for name in related_agent_names if name in other_agent_results]
            
            if not related_agents:
                return CrossAgentValidation(
                    passed=True,
                    agent_name=agent_name,
                    related_agents=[],
                    conflicts=[],
                    agreements=[],
                    consistency_score=1.0,
                    reasoning="No related agents available for cross-agent validation"
                )
            
            # Форматируем результаты связанных агентов
            related_results_text = []
            for related_agent_name in related_agents:
                related_result = other_agent_results[related_agent_name]
                related_text = self._extract_finding_text(related_result)
                related_results_text.append(f"{related_agent_name}:\n{related_text[:500]}")
            
            # Используем LLM для проверки согласованности
            validation_prompt = f"""Проверь согласованность результатов между агентами.

Текущий агент ({agent_name}):
{finding_text[:500]}

Результаты связанных агентов:
{chr(10).join(related_results_text)}

Проверь:
1. Согласуются ли результаты между агентами?
2. Есть ли противоречия?
3. Дополняют ли результаты друг друга?

Верни JSON:
{{
    "passed": true/false,
    "conflicts": [{{"agent": "agent_name", "conflict": "описание противоречия"}}],
    "agreements": [{{"agent": "agent_name", "agreement": "описание согласия"}}],
    "consistency_score": 0.0-1.0,
    "reasoning": "объяснение"
}}"""
            
            messages = [
                SystemMessage(content="Ты эксперт по проверке согласованности результатов разных AI-агентов."),
                HumanMessage(content=validation_prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Парсим JSON
            import json
            import re
            
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                validation_result = json.loads(json_match.group())
            else:
                validation_result = json.loads(response_text)
            
            passed = validation_result.get("passed", True)
            conflicts = validation_result.get("conflicts", [])
            agreements = validation_result.get("agreements", [])
            consistency_score = float(validation_result.get("consistency_score", 0.8))
            reasoning = validation_result.get("reasoning", "No reasoning provided")
            
            return CrossAgentValidation(
                passed=passed,
                agent_name=agent_name,
                related_agents=related_agents,
                conflicts=conflicts,
                agreements=agreements,
                consistency_score=consistency_score,
                reasoning=reasoning
            )
            
        except Exception as e:
            logger.error(f"Error in cross-agent validation: {e}", exc_info=True)
            return CrossAgentValidation(
                passed=False,
                agent_name=agent_name,
                related_agents=[],
                conflicts=[],
                agreements=[],
                consistency_score=0.0,
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

