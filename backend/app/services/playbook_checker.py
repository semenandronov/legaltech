"""Playbook Checker Service - движок проверки контрактов против Playbooks"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.playbook import Playbook, PlaybookRule, PlaybookCheck
from app.models.case import File
from app.services.clause_extractor import ClauseExtractor, ExtractedClause, ClauseExtractionResult
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime
import logging
import json
import re
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class RuleCheckResult:
    """Result of checking a single rule"""
    rule_id: str
    rule_name: str
    rule_type: str  # red_line, fallback, no_go
    clause_category: str
    status: str  # passed, violation, not_found, error
    found_text: str = ""
    location: Dict[str, Any] = field(default_factory=dict)
    issue_description: str = ""
    suggested_fix: str = ""
    confidence: float = 0.0
    reasoning: str = ""


@dataclass
class PlaybookCheckResult:
    """Full result of playbook check"""
    check_id: str
    playbook_id: str
    document_id: str
    overall_status: str  # compliant, non_compliant, needs_review
    compliance_score: float
    red_line_violations: int
    fallback_issues: int
    no_go_violations: int
    passed_rules: int
    results: List[RuleCheckResult]
    redlines: List[Dict[str, Any]]
    extracted_clauses: List[ExtractedClause]
    processing_time_seconds: int = 0


# Промпт для проверки правила
RULE_CHECK_PROMPT = """Ты - эксперт по анализу юридических документов. Проверь соответствие пункта контракта правилу.

ПРАВИЛО:
- Название: {rule_name}
- Описание: {rule_description}
- Тип: {rule_type}
- Категория пункта: {clause_category}
- Тип условия: {condition_type}
- Конфигурация условия: {condition_config}

ИЗВЛЕЧЁННЫЙ ПУНКТ КОНТРАКТА:
{clause_text}

ЗАДАЧА:
1. Проверь, соответствует ли найденный пункт требованиям правила
2. Если есть нарушение, опиши его
3. Если нужно исправление, предложи текст

ТИПЫ УСЛОВИЙ:
- must_exist: Пункт должен присутствовать и содержать требуемые положения
- must_not_exist: Пункт НЕ должен содержать определённые положения
- value_check: Проверка значения (min_value, max_value)
- duration_check: Проверка срока (min_duration, max_duration)
- text_match: Текст должен содержать определённые фразы
- text_not_match: Текст НЕ должен содержать определённые фразы

Верни результат в формате JSON:
{{
    "status": "passed|violation|unclear",
    "confidence": 0.0-1.0,
    "issue_description": "описание проблемы если есть",
    "suggested_fix": "предложение по исправлению если есть",
    "reasoning": "обоснование решения",
    "extracted_value": null  // если value_check или duration_check - извлечённое значение
}}

ВАЖНО:
- Будь строгим при проверке
- Если пункт не содержит достаточно информации - статус "unclear"
- Всегда объясняй reasoning"""


class PlaybookChecker:
    """
    Движок проверки контрактов против Playbooks.
    
    Процесс проверки:
    1. Загрузить документ и playbook
    2. Извлечь пункты контракта (clause extraction)
    3. Для каждого правила:
       - Найти соответствующий пункт
       - Проверить соответствие условию
       - Если нарушение - сгенерировать redline
    4. Сформировать итоговый отчёт
    """
    
    def __init__(self, db: Session):
        """Initialize playbook checker"""
        self.db = db
        self.clause_extractor = ClauseExtractor()
        self.llm = None
        self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM"""
        try:
            # Use use_rate_limiting=False for LangChain | operator compatibility
            self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
            logger.info("PlaybookChecker: LLM initialized")
        except Exception as e:
            logger.warning(f"PlaybookChecker: Failed to initialize LLM: {e}")
            self.llm = None
    
    async def check_document(
        self,
        document_id: str,
        playbook_id: str,
        user_id: str,
        case_id: Optional[str] = None
    ) -> PlaybookCheckResult:
        """
        Check document against a playbook
        
        Args:
            document_id: Document (file) ID
            playbook_id: Playbook ID
            user_id: User ID
            case_id: Optional case ID
            
        Returns:
            PlaybookCheckResult with all check results
        """
        start_time = datetime.utcnow()
        
        # Load playbook with rules
        playbook = self.db.query(Playbook).filter(
            Playbook.id == playbook_id
        ).first()
        
        if not playbook:
            raise ValueError(f"Playbook {playbook_id} not found")
        
        # Check playbook access - user must own it, or it must be public/system
        if not (playbook.user_id == user_id or playbook.is_public or playbook.is_system):
            raise ValueError(f"Access denied to playbook {playbook_id}")
        
        # Load document
        file = self.db.query(File).filter(File.id == document_id).first()
        if not file:
            raise ValueError(f"Document {document_id} not found")
        
        # Check document access - user must have access to the case
        if file.case_id:
            from app.models.case import Case
            case = self.db.query(Case).filter(Case.id == file.case_id).first()
            if case and case.user_id != user_id:
                raise ValueError(f"Access denied to document {document_id}")
        
        document_text = file.original_text or ""
        if not document_text:
            raise ValueError(f"Document {document_id} has no text content")
        
        # Create check record
        check = PlaybookCheck(
            playbook_id=playbook_id,
            document_id=document_id,
            case_id=case_id,
            user_id=user_id,
            document_name=file.filename,
            document_hash=hashlib.sha256(document_text.encode()).hexdigest()[:64],
            overall_status="in_progress",
            started_at=start_time,
        )
        self.db.add(check)
        self.db.flush()
        
        try:
            # Extract clauses from document
            logger.info(f"Extracting clauses from document {document_id}")
            extraction_result = await self.clause_extractor.extract_all_clauses(document_text)
            
            # Check each rule
            results: List[RuleCheckResult] = []
            active_rules = [r for r in playbook.rules if r.is_active]
            
            for rule in active_rules:
                try:
                    result = await self._check_rule(rule, extraction_result, document_text)
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error checking rule {rule.id}: {e}")
                    results.append(RuleCheckResult(
                        rule_id=rule.id,
                        rule_name=rule.rule_name,
                        rule_type=rule.rule_type,
                        clause_category=rule.clause_category,
                        status="error",
                        issue_description=str(e)
                    ))
            
            # Calculate statistics
            red_line_violations = sum(1 for r in results if r.rule_type == "red_line" and r.status == "violation")
            fallback_issues = sum(1 for r in results if r.rule_type == "fallback" and r.status == "violation")
            no_go_violations = sum(1 for r in results if r.rule_type == "no_go" and r.status == "violation")
            passed_rules = sum(1 for r in results if r.status == "passed")
            
            # Determine overall status
            if no_go_violations > 0:
                overall_status = "non_compliant"
            elif red_line_violations > 0:
                overall_status = "non_compliant"
            elif fallback_issues > 0:
                overall_status = "needs_review"
            else:
                overall_status = "compliant"
            
            # Calculate compliance score
            total_rules = len(results)
            if total_rules > 0:
                compliance_score = (passed_rules / total_rules) * 100
            else:
                compliance_score = 100.0
            
            # Generate redlines for violations
            redlines = []
            for result in results:
                if result.status == "violation" and result.suggested_fix:
                    redlines.append({
                        "rule_id": result.rule_id,
                        "rule_name": result.rule_name,
                        "original_text": result.found_text,
                        "suggested_text": result.suggested_fix,
                        "location": result.location,
                        "change_type": "replace" if result.found_text else "add",
                        "issue_description": result.issue_description,
                    })
            
            # Calculate processing time
            end_time = datetime.utcnow()
            processing_time = int((end_time - start_time).total_seconds())
            
            # Update check record
            check.overall_status = overall_status
            check.compliance_score = round(compliance_score, 2)
            check.red_line_violations = red_line_violations
            check.fallback_issues = fallback_issues
            check.no_go_violations = no_go_violations
            check.passed_rules = passed_rules
            check.results = [self._result_to_dict(r) for r in results]
            check.redlines = redlines
            check.extracted_clauses = [c.model_dump() for c in extraction_result.clauses]
            check.completed_at = end_time
            check.processing_time_seconds = processing_time
            
            self.db.commit()
            
            # Update playbook usage atomically to avoid race conditions
            Playbook.increment_usage_atomic(self.db, playbook_id)
            self.db.commit()
            
            logger.info(
                f"Completed playbook check {check.id}: "
                f"status={overall_status}, score={compliance_score:.1f}%, "
                f"violations={red_line_violations + no_go_violations}"
            )
            
            return PlaybookCheckResult(
                check_id=check.id,
                playbook_id=playbook_id,
                document_id=document_id,
                overall_status=overall_status,
                compliance_score=compliance_score,
                red_line_violations=red_line_violations,
                fallback_issues=fallback_issues,
                no_go_violations=no_go_violations,
                passed_rules=passed_rules,
                results=results,
                redlines=redlines,
                extracted_clauses=extraction_result.clauses,
                processing_time_seconds=processing_time
            )
            
        except Exception as e:
            logger.error(f"Error in playbook check: {e}", exc_info=True)
            check.overall_status = "failed"
            check.error_message = str(e)
            check.completed_at = datetime.utcnow()
            self.db.commit()
            raise
    
    async def _check_rule(
        self,
        rule: PlaybookRule,
        extraction_result: ClauseExtractionResult,
        document_text: str
    ) -> RuleCheckResult:
        """
        Check a single rule against extracted clauses
        
        Args:
            rule: PlaybookRule to check
            extraction_result: Extracted clauses
            document_text: Full document text
            
        Returns:
            RuleCheckResult
        """
        # Find matching clause by category
        matching_clause = None
        for clause in extraction_result.clauses:
            if clause.category == rule.clause_category:
                matching_clause = clause
                break
        
        # If no clause found, try to extract specifically
        if not matching_clause:
            matching_clause = await self.clause_extractor.extract_clause_by_category(
                document_text,
                rule.clause_category
            )
        
        # Check based on condition type
        if rule.condition_type == "must_exist":
            return await self._check_must_exist(rule, matching_clause)
        elif rule.condition_type == "must_not_exist":
            return await self._check_must_not_exist(rule, matching_clause, document_text)
        elif rule.condition_type == "value_check":
            return await self._check_value(rule, matching_clause)
        elif rule.condition_type == "duration_check":
            return await self._check_duration(rule, matching_clause)
        elif rule.condition_type == "text_match":
            return await self._check_text_match(rule, matching_clause, document_text)
        elif rule.condition_type == "text_not_match":
            return await self._check_text_not_match(rule, matching_clause, document_text)
        else:
            # Use LLM for general check
            return await self._check_with_llm(rule, matching_clause)
    
    async def _check_must_exist(
        self,
        rule: PlaybookRule,
        clause: Optional[ExtractedClause]
    ) -> RuleCheckResult:
        """Check must_exist condition"""
        if clause is None:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="violation",
                issue_description=f"Пункт категории '{rule.clause_category}' не найден в документе",
                suggested_fix=rule.suggested_clause_template or "",
                confidence=0.9,
                reasoning="Обязательный пункт отсутствует"
            )
        
        # Check if clause contains required elements (if specified in config)
        config = rule.condition_config or {}
        required_patterns = config.get("required_patterns", [])
        
        if required_patterns:
            clause_text_lower = clause.text.lower()
            missing_patterns = []
            for pattern in required_patterns:
                if pattern.lower() not in clause_text_lower:
                    missing_patterns.append(pattern)
            
            if missing_patterns:
                return RuleCheckResult(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    rule_type=rule.rule_type,
                    clause_category=rule.clause_category,
                    status="violation",
                    found_text=clause.text[:500],
                    location=clause.location,
                    issue_description=f"Пункт не содержит обязательные элементы: {', '.join(missing_patterns)}",
                    suggested_fix=rule.suggested_clause_template or "",
                    confidence=0.85,
                    reasoning=f"Найден пункт, но отсутствуют: {missing_patterns}"
                )
        
        return RuleCheckResult(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            clause_category=rule.clause_category,
            status="passed",
            found_text=clause.text[:500],
            location=clause.location,
            confidence=0.9,
            reasoning="Пункт найден и соответствует требованиям"
        )
    
    async def _check_must_not_exist(
        self,
        rule: PlaybookRule,
        clause: Optional[ExtractedClause],
        document_text: str
    ) -> RuleCheckResult:
        """Check must_not_exist condition"""
        config = rule.condition_config or {}
        forbidden_patterns = config.get("forbidden_patterns", [])
        
        # Search in full document text
        document_lower = document_text.lower()
        found_patterns = []
        
        for pattern in forbidden_patterns:
            if pattern.lower() in document_lower:
                found_patterns.append(pattern)
        
        if found_patterns:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="violation",
                found_text=clause.text[:500] if clause else "",
                location=clause.location if clause else {},
                issue_description=f"Документ содержит запрещённые положения: {', '.join(found_patterns)}",
                suggested_fix="Удалить указанные положения",
                confidence=0.9,
                reasoning=f"Найдены запрещённые паттерны: {found_patterns}"
            )
        
        return RuleCheckResult(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            clause_category=rule.clause_category,
            status="passed",
            confidence=0.9,
            reasoning="Запрещённые положения не найдены"
        )
    
    async def _check_value(
        self,
        rule: PlaybookRule,
        clause: Optional[ExtractedClause]
    ) -> RuleCheckResult:
        """Check value_check condition"""
        if clause is None:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="not_found",
                issue_description="Пункт не найден для проверки значения",
                confidence=0.8
            )
        
        config = rule.condition_config or {}
        min_value = config.get("min_value")
        max_value = config.get("max_value")
        
        # Try to extract value from clause
        extracted_value = clause.key_values.get("amount") or clause.key_values.get("value")
        
        if extracted_value is None:
            # Try regex extraction
            numbers = re.findall(r'[\d\s]+(?:[.,]\d+)?', clause.text)
            if numbers:
                try:
                    extracted_value = float(numbers[0].replace(" ", "").replace(",", "."))
                except ValueError:
                    pass
        
        if extracted_value is None:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="not_found",
                found_text=clause.text[:500],
                location=clause.location,
                issue_description="Не удалось извлечь числовое значение из пункта",
                confidence=0.6
            )
        
        # Check min/max
        violation = False
        issue = ""
        
        if min_value is not None and extracted_value < min_value:
            violation = True
            issue = f"Значение {extracted_value} меньше минимального {min_value}"
        
        if max_value is not None and extracted_value > max_value:
            violation = True
            issue = f"Значение {extracted_value} больше максимального {max_value}"
        
        if violation:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="violation",
                found_text=clause.text[:500],
                location=clause.location,
                issue_description=issue,
                suggested_fix=f"Изменить значение на допустимое (мин: {min_value}, макс: {max_value})",
                confidence=0.85,
                reasoning=f"Извлечённое значение: {extracted_value}"
            )
        
        return RuleCheckResult(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            clause_category=rule.clause_category,
            status="passed",
            found_text=clause.text[:500],
            location=clause.location,
            confidence=0.85,
            reasoning=f"Значение {extracted_value} в допустимых пределах"
        )
    
    async def _check_duration(
        self,
        rule: PlaybookRule,
        clause: Optional[ExtractedClause]
    ) -> RuleCheckResult:
        """Check duration_check condition"""
        if clause is None:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="not_found",
                issue_description="Пункт не найден для проверки срока",
                confidence=0.8
            )
        
        config = rule.condition_config or {}
        min_duration = config.get("min_duration")  # e.g., "3 years", "2 года"
        max_duration = config.get("max_duration")
        
        # Extract duration from clause
        duration_value = clause.key_values.get("duration")
        
        if duration_value is None:
            # Try regex extraction for common duration patterns
            duration_patterns = [
                r'(\d+)\s*(?:год|лет|года)',
                r'(\d+)\s*(?:месяц|месяцев)',
                r'(\d+)\s*(?:дней|день|дня)',
                r'(\d+)\s*years?',
                r'(\d+)\s*months?',
            ]
            
            for pattern in duration_patterns:
                match = re.search(pattern, clause.text, re.IGNORECASE)
                if match:
                    duration_value = match.group(0)
                    break
        
        if duration_value is None:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="not_found",
                found_text=clause.text[:500],
                location=clause.location,
                issue_description="Не удалось извлечь срок из пункта",
                confidence=0.6
            )
        
        # For now, just check if duration exists and return passed
        # Full duration comparison would require parsing both values
        return RuleCheckResult(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            clause_category=rule.clause_category,
            status="passed",
            found_text=clause.text[:500],
            location=clause.location,
            confidence=0.7,
            reasoning=f"Найден срок: {duration_value}. Требуется ручная проверка соответствия."
        )
    
    async def _check_text_match(
        self,
        rule: PlaybookRule,
        clause: Optional[ExtractedClause],
        document_text: str
    ) -> RuleCheckResult:
        """Check text_match condition"""
        config = rule.condition_config or {}
        patterns = config.get("patterns", [])
        match_type = config.get("match_type", "any")  # any, all
        
        search_text = clause.text if clause else document_text
        search_lower = search_text.lower()
        
        found_patterns = []
        missing_patterns = []
        
        for pattern in patterns:
            if pattern.lower() in search_lower:
                found_patterns.append(pattern)
            else:
                missing_patterns.append(pattern)
        
        if match_type == "all" and missing_patterns:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="violation",
                found_text=clause.text[:500] if clause else "",
                location=clause.location if clause else {},
                issue_description=f"Отсутствуют обязательные формулировки: {', '.join(missing_patterns)}",
                suggested_fix=rule.suggested_clause_template or "",
                confidence=0.85,
                reasoning=f"Найдено: {found_patterns}, Отсутствует: {missing_patterns}"
            )
        
        if match_type == "any" and not found_patterns:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="violation",
                found_text=clause.text[:500] if clause else "",
                location=clause.location if clause else {},
                issue_description=f"Не найдена ни одна из требуемых формулировок: {', '.join(patterns)}",
                suggested_fix=rule.suggested_clause_template or "",
                confidence=0.85
            )
        
        return RuleCheckResult(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            clause_category=rule.clause_category,
            status="passed",
            found_text=clause.text[:500] if clause else "",
            location=clause.location if clause else {},
            confidence=0.9,
            reasoning=f"Найдены требуемые формулировки: {found_patterns}"
        )
    
    async def _check_text_not_match(
        self,
        rule: PlaybookRule,
        clause: Optional[ExtractedClause],
        document_text: str
    ) -> RuleCheckResult:
        """Check text_not_match condition"""
        config = rule.condition_config or {}
        patterns = config.get("patterns", [])
        
        search_text = clause.text if clause else document_text
        search_lower = search_text.lower()
        
        found_forbidden = []
        
        for pattern in patterns:
            if pattern.lower() in search_lower:
                found_forbidden.append(pattern)
        
        if found_forbidden:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="violation",
                found_text=clause.text[:500] if clause else "",
                location=clause.location if clause else {},
                issue_description=f"Найдены запрещённые формулировки: {', '.join(found_forbidden)}",
                suggested_fix="Удалить или заменить указанные формулировки",
                confidence=0.9,
                reasoning=f"Запрещённые паттерны в тексте: {found_forbidden}"
            )
        
        return RuleCheckResult(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            clause_category=rule.clause_category,
            status="passed",
            found_text=clause.text[:500] if clause else "",
            location=clause.location if clause else {},
            confidence=0.9,
            reasoning="Запрещённые формулировки не найдены"
        )
    
    async def _check_with_llm(
        self,
        rule: PlaybookRule,
        clause: Optional[ExtractedClause]
    ) -> RuleCheckResult:
        """Check rule using LLM for complex conditions"""
        if not self.llm:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="error",
                issue_description="LLM не инициализирован для проверки"
            )
        
        if clause is None:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="not_found",
                issue_description="Соответствующий пункт не найден в документе",
                suggested_fix=rule.suggested_clause_template or ""
            )
        
        try:
            prompt = ChatPromptTemplate.from_template(RULE_CHECK_PROMPT)
            chain = prompt | self.llm
            
            response = await chain.ainvoke({
                "rule_name": rule.rule_name,
                "rule_description": rule.description or "",
                "rule_type": rule.rule_type,
                "clause_category": rule.clause_category,
                "condition_type": rule.condition_type,
                "condition_config": json.dumps(rule.condition_config or {}, ensure_ascii=False),
                "clause_text": clause.text,
            })
            
            # Parse response
            json_match = re.search(r'\{[\s\S]*\}', response.content)
            if json_match:
                result_data = json.loads(json_match.group())
                
                status = result_data.get("status", "unclear")
                if status == "unclear":
                    status = "not_found"
                
                return RuleCheckResult(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    rule_type=rule.rule_type,
                    clause_category=rule.clause_category,
                    status=status,
                    found_text=clause.text[:500],
                    location=clause.location,
                    issue_description=result_data.get("issue_description", ""),
                    suggested_fix=result_data.get("suggested_fix", "") or rule.suggested_clause_template or "",
                    confidence=result_data.get("confidence", 0.7),
                    reasoning=result_data.get("reasoning", "")
                )
            
        except Exception as e:
            logger.error(f"LLM check error: {e}")
        
        return RuleCheckResult(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            clause_category=rule.clause_category,
            status="error",
            found_text=clause.text[:500] if clause else "",
            issue_description="Ошибка при проверке с помощью LLM"
        )
    
    def _result_to_dict(self, result: RuleCheckResult) -> Dict[str, Any]:
        """Convert RuleCheckResult to dictionary"""
        return {
            "rule_id": result.rule_id,
            "rule_name": result.rule_name,
            "rule_type": result.rule_type,
            "clause_category": result.clause_category,
            "status": result.status,
            "found_text": result.found_text,
            "location": result.location,
            "issue_description": result.issue_description,
            "suggested_fix": result.suggested_fix,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }
    
    async def batch_check(
        self,
        document_ids: List[str],
        playbook_id: str,
        user_id: str,
        case_id: Optional[str] = None
    ) -> List[PlaybookCheckResult]:
        """
        Check multiple documents against a playbook
        
        Args:
            document_ids: List of document IDs
            playbook_id: Playbook ID
            user_id: User ID
            case_id: Optional case ID
            
        Returns:
            List of PlaybookCheckResults
        """
        results = []
        
        for document_id in document_ids:
            try:
                result = await self.check_document(
                    document_id=document_id,
                    playbook_id=playbook_id,
                    user_id=user_id,
                    case_id=case_id
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Error checking document {document_id}: {e}")
                # Add failed result
                results.append(PlaybookCheckResult(
                    check_id="",
                    playbook_id=playbook_id,
                    document_id=document_id,
                    overall_status="failed",
                    compliance_score=0,
                    red_line_violations=0,
                    fallback_issues=0,
                    no_go_violations=0,
                    passed_rules=0,
                    results=[],
                    redlines=[],
                    extracted_clauses=[]
                ))
        
        return results

