"""Playbook Checker Service - движок проверки контрактов против Playbooks"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.playbook import Playbook, PlaybookRule, PlaybookCheck
from app.models.case import File
from app.models.document_editor import Document
from app.services.clause_extractor import ClauseExtractor, ExtractedClause, ClauseExtractionResult
from app.services.llm_factory import create_llm
from app.services.pgvector_store import CaseVectorStore
from langchain_core.prompts import ChatPromptTemplate
from datetime import datetime
import logging
import json
import math
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
    status: str  # passed, violation, warning, not_found, error
    found_text: str = ""
    location: Dict[str, Any] = field(default_factory=dict)
    issue_description: str = ""
    suggested_fix: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    # Harvey-style additions
    ui_status: str = ""  # acceptable | needs_review | not_acceptable
    guidance: str = ""
    suggested_options: List[Dict[str, Any]] = field(default_factory=list)
    # All phrase occurrences found in the document (for display)
    occurrences: List[Dict[str, Any]] = field(default_factory=list)
    # Full rule phrase lists (for display in UI)
    rule_standard_phrases: List[str] = field(default_factory=list)
    rule_fallback_phrases: List[str] = field(default_factory=list)
    rule_unacceptable_phrases: List[str] = field(default_factory=list)


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


# Промпт для проверки правила (общий, без Harvey-структуры)
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


# Harvey-подобный промпт с учётом стандартной позиции, fallback и недопустимых формулировок
HARVEY_RULE_PROMPT = """Ты - эксперт по анализу юридических документов.

Твоя задача — проанализировать, насколько приведённый пункт договора соответствует внутреннему правилу фирмы.

ПРАВИЛО:
- Название: {rule_name}
- Тип правила: {rule_type}  // red_line, fallback, no_go
- Категория пункта: {clause_category}
- Совет для пользователя (показывается юристу после проверки — НЕ является критерием классификации): {guidance}

СТАНДАРТНАЯ ПОЗИЦИЯ:
\"\"\"{standard_position}\"\"\"

ЗАПАСНЫЕ ВАРИАНТЫ (fallbacks):
{fallback_positions}

НЕДОПУСТИМЫЕ ФОРМУЛИРОВКИ:
{unacceptable_phrases}

ИЗВЛЕЧЁННЫЙ ПУНКТ КОНТРАКТА:
\"\"\"{clause_text}\"\"\"

ЗАДАЧА:
1. Определи, соответствует ли пункт стандартной позиции, одному из запасных вариантов или недопустимым формулировкам.
2. Если формулировка стандартная — это приемлемо.
3. Если формулировка попадает в запасные варианты — это допустимо, но лучше привести к стандарту.
4. Если формулировка попадает в недопустимые — это неприемлемо, нужно предложить изменения.
5. Если пункт по смыслу относится к правилу, но не совпадает ни со стандартом, ни с fallback, ни с недопустимыми — пометь как неподтверждённый вариант, требующий проверки.
6. Если соответствующий пункт в документе отсутствует — так и укажи.

ВАЖНО: «Совет для пользователя» — это подсказка для юриста, которая будет отображена ему после проверки.
НЕ используй её как критерий классификации. Классифицируй пункт ТОЛЬКО по его семантическому сходству
с текстом стандарта, запасных вариантов или недопустимых формулировок.
Запасные варианты (fallbacks) могут содержать пустые поля «_____» — это допустимо, если структура совпадает.

Верни результат ТОЛЬКО в виде одного JSON-объекта:
{{
  "classification": "standard|fallback|unacceptable|unknown|no_clause",
  "status": "passed|violation|warning|not_found",
  "confidence": 0.0,
  "found_excerpt": "ТОЧНАЯ цитата из текста пункта — самый короткий фрагмент (до 150 символов), который однозначно идентифицирует найденную формулировку. Например, ФИО, ключевая фраза или условие. НЕ копируй весь текст — только суть. Если пункт не найден — пустая строка.",
  "issue_description": "кратко, в чём проблема (или почему всё нормально)",
  "reasoning": "подробное логическое объяснение на русском языке"
}}

ТРЕБОВАНИЯ:
- Не добавляй никакого текста до или после JSON.
- found_excerpt — точная цитата из clause_text (не перефразировка), максимум 150 символов.
- Для имён: если в тексте "Абумова Евгения Геннадьевича", а стандарт "Абумов Е.Г." — это одно и то же лицо, классифицируй как "standard".
- Если текста пункта нет или он явно не относится к правилу — используй classification = "no_clause".
- Будь последовательным и консервативным: если есть сомнения, используй classification = "unknown" и status = "warning"."""


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
        self.vector_store: Optional[CaseVectorStore] = None
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

    def _init_vector_store(self):
        """
        Lazy initialization of PGVector store for semantic search.
        """
        if self.vector_store is not None:
            return
        try:
            self.vector_store = CaseVectorStore()
            logger.info("PlaybookChecker: PGVector store initialized for semantic rule search")
        except Exception as e:
            logger.warning(f"PlaybookChecker: Failed to initialize PGVector store: {e}")
            self.vector_store = None
    
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
        
        # Load document - try File first, then editor Document
        file = self.db.query(File).filter(File.id == document_id).first()
        editor_doc = None
        if not file:
            editor_doc = self.db.query(Document).filter(Document.id == document_id).first()

        if not file and not editor_doc:
            raise ValueError(f"Document {document_id} not found")

        # Determine effective case_id and check document access
        effective_case_id = case_id
        if file:
            if file.case_id:
                from app.models.case import Case
                case = self.db.query(Case).filter(Case.id == file.case_id).first()
                if case and case.user_id != user_id:
                    raise ValueError(f"Access denied to document {document_id}")
                effective_case_id = effective_case_id or file.case_id
            document_text = file.original_text or ""
            document_name = file.filename
        else:
            # Editor document
            from app.models.case import Case
            case = self.db.query(Case).filter(Case.id == editor_doc.case_id).first()
            if case and case.user_id != user_id:
                raise ValueError(f"Access denied to document {document_id}")
            effective_case_id = effective_case_id or editor_doc.case_id
            document_text = editor_doc.content_plain or ""
            if not document_text and editor_doc.content:
                # Strip HTML tags to get plain text
                document_text = re.sub(r'<[^>]+>', ' ', editor_doc.content)
                document_text = re.sub(r'\s+', ' ', document_text).strip()
            document_name = editor_doc.title

        if not document_text:
            raise ValueError(f"Document {document_id} has no text content")

        # Create check record
        check = PlaybookCheck(
            playbook_id=playbook_id,
            document_id=document_id,
            case_id=effective_case_id,
            user_id=user_id,
            document_name=document_name,
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
                    result = await self._check_rule(
                        rule,
                        extraction_result,
                        document_text,
                        file=file,
                        editor_doc=editor_doc,
                        case_id=effective_case_id,
                    )
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
        document_text: str,
        file: Optional[File] = None,
        editor_doc: Optional[Document] = None,
        case_id: Optional[str] = None,
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
        # Harvey-style semantic check when есть стандарт/запасные/недопустимые формулировки.
        # Используем для must_exist / text_match / text_not_match, чтобы вести себя как Harvey.
        has_harvey_config = bool(rule.suggested_clause_template or rule.fallback_options)
        matching_clause: Optional[ExtractedClause] = None

        # 1. Если есть Harvey-конфигурация, доступен case_id И документ — файл из дела
        #    (не editor-документ), пробуем семантический поиск по эмбеддингам с фильтром по file_id.
        #    Для editor-документов семантический поиск пропускаем, чтобы не возвращать чанки
        #    из других файлов того же дела.
        if has_harvey_config and case_id and file is not None:
            try:
                matching_clause = await self._find_semantic_clause_for_rule(
                    rule=rule,
                    case_id=case_id,
                    file_id=file.id,
                )
            except Exception as e:
                logger.warning(
                    "PlaybookChecker: semantic search failed for rule %s: %s",
                    rule.id,
                    e,
                    exc_info=True,
                )

        # 2. Если семантический поиск не дал результата — используем старую схему по категории.
        # Собираем ВСЕ пункты с нужной категорией (не только первый), чтобы проверить каждый.
        extra_category_clauses: List[ExtractedClause] = []
        if not matching_clause:
            category_clauses = [c for c in extraction_result.clauses if c.category == rule.clause_category]
            if category_clauses:
                matching_clause = category_clauses[0]
                extra_category_clauses = category_clauses[1:]  # Остальные для дополнительной проверки

        # 3. Если по категориям тоже не нашли — как крайний случай пробуем точечное извлечение по категории.
        # Используем rule_name как запасной идентификатор если clause_category пустой.
        if not matching_clause:
            category_for_extraction = rule.clause_category or rule.rule_name
            if category_for_extraction:
                matching_clause = await self.clause_extractor.extract_clause_by_category(
                    document_text,
                    category_for_extraction,
                )

        # Диспетчер проверки для одного пункта
        async def _run_single_check(clause: Optional[ExtractedClause]) -> RuleCheckResult:
            if has_harvey_config and rule.condition_type in {"must_exist", "text_match", "text_not_match"}:
                return await self._check_harvey_semantic(rule, clause, document_text)
            if rule.condition_type == "must_exist":
                return await self._check_must_exist(rule, clause)
            elif rule.condition_type == "must_not_exist":
                return await self._check_must_not_exist(rule, clause, document_text)
            elif rule.condition_type == "value_check":
                return await self._check_value(rule, clause)
            elif rule.condition_type == "duration_check":
                return await self._check_duration(rule, clause)
            elif rule.condition_type == "text_match":
                return await self._check_text_match(rule, clause, document_text)
            elif rule.condition_type == "text_not_match":
                return await self._check_text_not_match(rule, clause, document_text)
            else:
                return await self._check_with_llm(rule, clause)

        # Проверяем первый пункт
        primary_result = await _run_single_check(matching_clause)

        # Если есть дополнительные пункты с той же категорией — проверяем их тоже (до 2 дополнительных)
        # и возвращаем наихудший результат
        if extra_category_clauses:
            all_results = [primary_result]
            for extra_clause in extra_category_clauses[:2]:
                try:
                    extra_result = await _run_single_check(extra_clause)
                    all_results.append(extra_result)
                except Exception as e:
                    logger.warning("PlaybookChecker: error checking extra clause for rule %s: %s", rule.id, e)
            final_result = self._pick_worst_result(all_results)
        else:
            final_result = primary_result

        # Attach full rule phrase lists so the UI can show the complete rule definition
        if has_harvey_config:
            cfg = self._extract_harvey_config_from_rule(rule)
            sp = cfg.get("standard_position", "")
            final_result.rule_standard_phrases = [sp] if sp else []
            final_result.rule_fallback_phrases = [f for f in cfg.get("fallback_positions", []) if f]
            final_result.rule_unacceptable_phrases = [u for u in cfg.get("unacceptable_phrases", []) if u]

        return final_result

    def _pick_worst_result(self, results: List[RuleCheckResult]) -> RuleCheckResult:
        """Return the result with the worst (most severe) status."""
        status_priority = {"violation": 0, "error": 1, "not_found": 2, "warning": 3, "passed": 4, "not_applicable": 5}
        results_sorted = sorted(results, key=lambda r: status_priority.get(r.status, 99))
        return results_sorted[0]

    def _extract_harvey_config_from_rule(
        self,
        rule: PlaybookRule,
    ) -> Dict[str, Any]:
        """
        Унифицированное извлечение Harvey-конфигурации из PlaybookRule.
        Возвращает словарь с ключами:
        - standard_position
        - fallback_positions
        - unacceptable_phrases
        - guidance
        - mark_missing
        """
        standard_position = rule.suggested_clause_template or ""
        fallback_positions: List[str] = []
        unacceptable_phrases: List[str] = []
        guidance = ""
        mark_missing = False

        try:
            fo = None
            if isinstance(rule.fallback_options, list) and rule.fallback_options:
                fo = rule.fallback_options[0] or {}
            elif isinstance(rule.fallback_options, dict):
                fo = rule.fallback_options

            if fo:
                if not standard_position:
                    standard_position = fo.get("standard_position") or ""
                fallback_positions = list(fo.get("fallbacks") or [])
                unacceptable_phrases = list(fo.get("unacceptable") or [])
                guidance = fo.get("guidance") or ""
                mark_missing = bool(fo.get("mark_missing"))
        except Exception:
            # Не роняем проверку, даже если формат fallback_options неожиданен
            logger.warning("Unexpected fallback_options format for rule %s", rule.id, exc_info=True)

        if not guidance:
            guidance = rule.description or ""

        return {
            "standard_position": standard_position,
            "fallback_positions": fallback_positions,
            "unacceptable_phrases": unacceptable_phrases,
            "guidance": guidance,
            "mark_missing": mark_missing,
        }

    def _build_rule_query_text(self, rule: PlaybookRule) -> str:
        """
        Собирает текст запроса для эмбеддингового поиска по документу
        на основе имени правила, описания, стандартной позиции, fallback и недопустимых формулировок.
        """
        cfg = self._extract_harvey_config_from_rule(rule)
        parts: List[str] = []

        if rule.rule_name:
            parts.append(f"Найди в договоре пункт, относящийся к правилу: {rule.rule_name}.")
        if cfg["guidance"]:
            parts.append(f"Описание правила: {cfg['guidance']}.")
        if cfg["standard_position"]:
            parts.append(f"Предпочтительная формулировка (стандартная позиция): {cfg['standard_position']}.")
        if cfg["fallback_positions"]:
            fallbacks_text = " ".join(cfg["fallback_positions"])
            parts.append(f"Допустимые запасные формулировки: {fallbacks_text}.")
        if cfg["unacceptable_phrases"]:
            unacceptable_text = " ".join(cfg["unacceptable_phrases"])
            parts.append(f"Недопустимые формулировки: {unacceptable_text}.")

        # На всякий случай добавим тип правила
        if rule.rule_type:
            parts.append(f"Тип правила: {rule.rule_type}.")

        return "\n".join(parts).strip()

    async def _find_semantic_clause_for_rule(
        self,
        rule: PlaybookRule,
        case_id: str,
        file_id: Optional[str] = None,
        k: int = 5,
    ) -> Optional[ExtractedClause]:
        """
        Ищет релевантный фрагмент в документе через PGVector по смыслу правила.

        Возвращает искусственный ExtractedClause, чтобы дальше использовать общую Harvey-логику.
        """
        # Инициализируем vector store при первом обращении
        self._init_vector_store()
        if not self.vector_store:
            return None

        # Собираем текст запроса из правила
        query_text = self._build_rule_query_text(rule)
        if not query_text:
            return None

        try:
            # Фильтр по file_id используем только если он есть; для редакторских документов
            # ищем по всему делу без ограничения по файлу.
            search_filter: Dict[str, Any] = {}
            if file_id:
                search_filter["file_id"] = file_id

            # Ищем только внутри конкретного файла по case_id + file_id
            docs_with_scores = self.vector_store.similarity_search_with_score(
                query=query_text,
                case_id=case_id,
                k=k,
                filter=search_filter or None,
            )
        except Exception as e:
            logger.warning(
                "PlaybookChecker: similarity_search_with_score failed for rule %s: %s",
                rule.id,
                e,
                exc_info=True,
            )
            return None

        if not docs_with_scores:
            return None

        # Берём самый релевантный фрагмент
        best_doc, best_score = docs_with_scores[0]
        metadata = getattr(best_doc, "metadata", {}) or {}

        # Формируем location с привязкой к исходному тексту.
        # Дублируем char_start/char_end в start/end, чтобы фронт мог сразу подсветить диапазон.
        char_start = metadata.get("char_start")
        char_end = metadata.get("char_end")
        location: Dict[str, Any] = {
            "source": "semantic_embedding",
            "file_id": metadata.get("file_id") or file_id,
            "doc_id": metadata.get("doc_id"),
            "char_start": char_start,
            "char_end": char_end,
            "start": char_start,
            "end": char_end,
            "chunk_index": metadata.get("chunk_index"),
            "similarity_score": (lambda s: None if s is None or math.isnan(s) else s)(float(best_score) if best_score is not None else None),
            "source_file": metadata.get("source_file") or metadata.get("source"),
        }

        # Создаём упрощённый ExtractedClause для дальнейшей проверки
        return ExtractedClause(
            category=rule.clause_category or metadata.get("category", "other"),
            title=metadata.get("title", "") or rule.rule_name or "",
            text=best_doc.page_content or "",
            location=location,
            summary=metadata.get("summary", ""),
            key_values={},
        )

    def _find_all_name_variants(
        self,
        standard_position: str,
        document_text: str,
        already_found_starts: set,
        context_window: int = 60,
    ) -> List[Dict[str, Any]]:
        """Find all occurrences of a name/phrase by its key surname/word.

        Catches variants like "Абумов Е Г" (no dots) when standard is "Абумов Е.Г." (dots).
        Only returns occurrences not already in already_found_starts.
        """
        if not standard_position or not document_text:
            return []
        # Extract the longest significant keyword (e.g. surname "Абумов")
        keywords = sorted(
            [w.rstrip(".,;:()") for w in standard_position.split() if len(w.rstrip(".,;:()")) >= 4],
            key=len, reverse=True,
        )
        if not keywords:
            return []
        original_kw = keywords[0]
        # Only apply keyword scan for PROPER NOUNS (capitalized) — e.g. names and company names.
        # Skips common legal words like "оплаты", "расторжения" that would flood the results.
        if not original_kw[0].isupper():
            return []
        kw = original_kw.lower()
        doc_lower = document_text.lower()
        # If the keyword appears too often it's not a distinctive name — skip.
        if doc_lower.count(kw) > 8:
            return []
        raw_len = len(standard_position) + 30
        # How many whitespace-separated tokens the target phrase has.
        # E.g. "Абросимов Е.Г." → 2 tokens. In the document "Абросимова Е Г" has 3 tokens
        # because initials may lack dots. We capture expected_tokens + 1 to handle that case.
        expected_tokens = len(standard_position.split())
        additional: List[Dict[str, Any]] = []
        start = 0
        while True:
            pos = doc_lower.find(kw, start)
            if pos == -1:
                break
            # Skip positions already covered (within 3-char tolerance)
            if not any(abs(pos - fp) <= 3 for fp in already_found_starts):
                raw = document_text[pos:min(len(document_text), pos + raw_len)]
                # Capture only as many tokens as the target phrase (+ 1 for dot-less initials).
                # This prevents capturing trailing words like "без присмотра" when the keyword
                # matched as a substring (e.g. "абросимов" inside "Абросимова").
                raw_tokens = raw.split()
                phrase = " ".join(raw_tokens[:expected_tokens + 1]).rstrip(".,;: ")
                if not phrase:
                    phrase = document_text[pos:pos + len(kw)]
                ctx_start = max(0, pos - context_window)
                ctx_end = min(len(document_text), pos + len(phrase) + context_window)
                additional.append({
                    "type": "standard",
                    "phrase": phrase,
                    "char_start": pos,
                    "char_end": pos + len(phrase),
                    "context": document_text[ctx_start:ctx_end],
                })
                already_found_starts.add(pos)
            start = pos + len(kw)
        return additional

    @staticmethod
    def _get_blank_prefix_pos(phrase: str, doc_lower: str, min_prefix_len: int = 20) -> Optional[int]:
        """For template phrases containing ___ blanks, find position via prefix (text before first blanks).

        Returns position in doc_lower where the prefix starts, or None if not applicable/found.
        Useful when the phrase has blanks like "по адресу: _____________" but the document
        has a comma difference: "по адресу: _____________,".
        """
        m = re.search(r'_{2,}', phrase)
        if not m:
            return None
        prefix = phrase[:m.start()].strip().rstrip(".,;: ").lower()
        if len(prefix) < min_prefix_len:
            return None
        pos = doc_lower.find(prefix)
        return pos if pos != -1 else None

    def _scan_document_for_phrases(
        self,
        document_text: str,
        unacceptable_phrases: List[str],
        fallback_positions: List[str],
        standard_position: str,
        context_window: int = 60,
    ) -> Dict[str, Any]:
        """
        Scan the ENTIRE document text for all occurrences of configured phrases.
        Returns every match with character positions and surrounding context.
        """
        doc_lower = document_text.lower()
        found_unacceptable: List[Dict[str, Any]] = []
        found_fallbacks: List[Dict[str, Any]] = []
        found_standard: List[Dict[str, Any]] = []

        for phrase in unacceptable_phrases:
            if not phrase:
                continue
            # Strip trailing punctuation to match "Абумов Е.Г," or "Абумов Е.Г" in doc
            phrase_search = phrase.rstrip(".,;: ") or phrase
            phrase_lower = phrase_search.lower()
            start = 0
            while True:
                pos = doc_lower.find(phrase_lower, start)
                if pos == -1:
                    break
                ctx_start = max(0, pos - context_window)
                ctx_end = min(len(document_text), pos + len(phrase_search) + context_window)
                found_unacceptable.append({
                    "type": "unacceptable",
                    "phrase": document_text[pos:pos + len(phrase_search)],
                    "char_start": pos,
                    "char_end": pos + len(phrase_search),
                    "context": document_text[ctx_start:ctx_end],
                })
                start = pos + len(phrase_search)

        for phrase in fallback_positions:
            if not phrase:
                continue
            # Strip trailing punctuation to match "phrase," or "phrase." variants
            phrase_search = phrase.rstrip(".,;: ") or phrase
            phrase_lower = phrase_search.lower()
            start = 0
            found_any_exact = False
            while True:
                pos = doc_lower.find(phrase_lower, start)
                if pos == -1:
                    break
                found_any_exact = True
                ctx_start = max(0, pos - context_window)
                ctx_end = min(len(document_text), pos + len(phrase_search) + context_window)
                found_fallbacks.append({
                    "type": "fallback",
                    "phrase": document_text[pos:pos + len(phrase_search)],
                    "char_start": pos,
                    "char_end": pos + len(phrase_search),
                    "context": document_text[ctx_start:ctx_end],
                })
                start = pos + len(phrase_search)
            # If exact match failed, try blank-tolerant prefix match for template phrases
            if not found_any_exact:
                prefix_pos = self._get_blank_prefix_pos(phrase_search, doc_lower)
                if prefix_pos is not None:
                    # Capture actual document text from that position
                    cap_len = min(len(phrase_search) + 20, len(document_text) - prefix_pos)
                    phrase_found = document_text[prefix_pos:prefix_pos + cap_len]
                    # Trim at nearest sentence/clause end after a reasonable minimum
                    end_m = re.search(r'[.!?\n]', phrase_found[10:]) if len(phrase_found) > 10 else None
                    if end_m:
                        phrase_found = phrase_found[:10 + end_m.start() + 1]
                    ctx_start = max(0, prefix_pos - context_window)
                    ctx_end = min(len(document_text), prefix_pos + len(phrase_found) + context_window)
                    found_fallbacks.append({
                        "type": "fallback",
                        "phrase": phrase_found,
                        "char_start": prefix_pos,
                        "char_end": prefix_pos + len(phrase_found),
                        "context": document_text[ctx_start:ctx_end],
                    })

        if standard_position:
            # Strip trailing punctuation to match "Абумов Е.Г," when standard is "Абумов Е.Г."
            std_search = standard_position.rstrip(".,;: ") or standard_position
            std_lower = std_search.lower()
            start = 0
            while True:
                pos = doc_lower.find(std_lower, start)
                if pos == -1:
                    break
                ctx_start = max(0, pos - context_window)
                ctx_end = min(len(document_text), pos + len(std_search) + context_window)
                found_standard.append({
                    "type": "standard",
                    "phrase": document_text[pos:pos + len(std_search)],
                    "char_start": pos,
                    "char_end": pos + len(std_search),
                    "context": document_text[ctx_start:ctx_end],
                })
                start = pos + len(std_search)

        return {
            "unacceptable": found_unacceptable,
            "fallbacks": found_fallbacks,
            "standard": found_standard,
        }

    async def _check_harvey_semantic(
        self,
        rule: PlaybookRule,
        clause: Optional[ExtractedClause],
        document_text: str
    ) -> RuleCheckResult:
        """
        Harvey-style semantic check using standard position, fallbacks and unacceptable phrases.
        """
        cfg = self._extract_harvey_config_from_rule(rule)
        standard_position = cfg["standard_position"]
        fallback_positions = cfg["fallback_positions"]
        unacceptable_phrases = cfg["unacceptable_phrases"]
        guidance = cfg["guidance"]
        mark_missing = cfg["mark_missing"]

        # ---------------------------------------------------------------
        # Phase 0: Direct full-document scan for ALL configured phrases.
        # This finds every occurrence in the document, not just the best
        # semantic chunk — fixing the "stops after first match" bug.
        # ---------------------------------------------------------------
        has_any_phrases = bool(unacceptable_phrases or fallback_positions or standard_position)
        if has_any_phrases and document_text:
            scan = self._scan_document_for_phrases(
                document_text=document_text,
                unacceptable_phrases=unacceptable_phrases,
                fallback_positions=fallback_positions,
                standard_position=standard_position,
            )
            all_occurrences = scan["unacceptable"] + scan["fallbacks"] + scan["standard"]
            if all_occurrences:
                suggested_options: List[Dict[str, Any]] = []

                if scan["unacceptable"]:
                    # Violation: unacceptable phrase(s) found anywhere in document
                    status = "violation"
                    ui_status = "not_acceptable"
                    if standard_position:
                        suggested_options.append(
                            {"label": "Standard position", "type": "standard", "text": standard_position}
                        )
                    for idx, fb in enumerate(fallback_positions):
                        if fb:
                            suggested_options.append(
                                {"label": f"Fallback {idx + 1}", "type": "fallback", "text": fb}
                            )
                    issue_description = (
                        f"Найдено {len(scan['unacceptable'])} недопустимых формулировок в документе."
                    )
                    if scan["fallbacks"]:
                        issue_description += (
                            f" Также найдено {len(scan['fallbacks'])} запасных формулировок."
                        )
                    first_match = scan["unacceptable"][0]
                    reasoning = (
                        "Прямой поиск по всему документу нашёл недопустимые формулировки: "
                        + ", ".join(repr(m["phrase"]) for m in scan["unacceptable"][:3])
                    )
                elif scan["fallbacks"]:
                    # Warning: only fallback phrase(s) found
                    status = "warning"
                    ui_status = "needs_review"
                    if standard_position:
                        suggested_options.append(
                            {"label": "Standard position", "type": "standard", "text": standard_position}
                        )
                    issue_description = (
                        f"Найдено {len(scan['fallbacks'])} запасных формулировок. "
                        "Рекомендуется привести к стандартной позиции."
                    )
                    first_match = scan["fallbacks"][0]
                    reasoning = (
                        "Прямой поиск по всему документу нашёл запасные формулировки: "
                        + ", ".join(repr(m["phrase"]) for m in scan["fallbacks"][:3])
                    )
                else:
                    # Only standard position found — passed
                    status = "passed"
                    ui_status = "acceptable"
                    issue_description = ""
                    first_match = scan["standard"][0]
                    reasoning = "Найдена стандартная позиция в документе."

                main_fix = "" if status == "passed" else (
                    standard_position or (fallback_positions[0] if fallback_positions else "")
                )
                # Keyword-based scan to catch inflected/variant forms for ALL phrase types.
                # E.g. "Иванову Е.Г." (dative) found when fallback is "Иванов Е.Г."
                already_found = {occ["char_start"] for occ in all_occurrences}
                variants = self._find_all_name_variants(
                    standard_position, document_text, already_found
                )
                all_occurrences = all_occurrences + variants

                # Fallback keyword variants
                for fb in fallback_positions:
                    if not fb:
                        continue
                    fb_variants = self._find_all_name_variants(fb, document_text, already_found)
                    if fb_variants:
                        for v in fb_variants:
                            v["type"] = "fallback"
                        all_occurrences = all_occurrences + fb_variants
                        if status == "passed":
                            status = "warning"
                            ui_status = "needs_review"
                            issue_description = (
                                "Найдены стандартные и запасные формулировки. "
                                "Запасные рекомендуется привести к стандартной позиции."
                            )
                            if standard_position:
                                suggested_options = [
                                    {"label": "Standard position", "type": "standard", "text": standard_position}
                                ]

                # Unacceptable keyword variants
                for unac in unacceptable_phrases:
                    if not unac:
                        continue
                    unac_variants = self._find_all_name_variants(unac, document_text, already_found)
                    if unac_variants:
                        for v in unac_variants:
                            v["type"] = "unacceptable"
                        all_occurrences = all_occurrences + unac_variants
                        status = "violation"
                        ui_status = "not_acceptable"
                        issue_description = "Найдены недопустимые формулировки. Требуется замена."
                        if not suggested_options:
                            if standard_position:
                                suggested_options.append(
                                    {"label": "Standard position", "type": "standard", "text": standard_position}
                                )
                            for idx2, fb2 in enumerate(fallback_positions):
                                if fb2:
                                    suggested_options.append(
                                        {"label": f"Fallback {idx2 + 1}", "type": "fallback", "text": fb2}
                                    )

                return RuleCheckResult(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    rule_type=rule.rule_type,
                    clause_category=rule.clause_category,
                    status=status,
                    # found_text = EXACT phrase to replace (not the surrounding context).
                    # The context is stored in occurrences[N].context for display.
                    found_text=first_match["phrase"],
                    location={
                        "char_start": first_match["char_start"],
                        "char_end": first_match["char_end"],
                        "start": first_match["char_start"],
                        "end": first_match["char_end"],
                        "source": "direct_scan",
                    },
                    issue_description=issue_description,
                    suggested_fix=main_fix,
                    confidence=0.95,
                    reasoning=reasoning,
                    ui_status=ui_status,
                    guidance=guidance,
                    suggested_options=suggested_options,
                    occurrences=all_occurrences,
                )

            # Phase 0.5: keyword-based scan for ALL phrase types when exact scan found nothing.
            # Catches e.g. "Абросимова Е Г" (genitive / no-dots) when phrase is "Абросимов Е.Г."
            # Only applies to PROPER NOUNS (capitalized keywords) — see _find_all_name_variants.
            if not all_occurrences and has_any_phrases:
                p05_already: set = set()
                p05_unac: List[Dict[str, Any]] = []
                p05_fallbacks: List[Dict[str, Any]] = []
                p05_standard: List[Dict[str, Any]] = []

                for unac_phrase in unacceptable_phrases:
                    if not unac_phrase:
                        continue
                    vv = self._find_all_name_variants(unac_phrase, document_text, p05_already)
                    for v in vv:
                        v["type"] = "unacceptable"
                    p05_unac.extend(vv)
                    p05_already.update(v["char_start"] for v in vv)

                if standard_position:
                    vv = self._find_all_name_variants(standard_position, document_text, p05_already)
                    p05_standard.extend(vv)
                    p05_already.update(v["char_start"] for v in vv)

                for fb in fallback_positions:
                    if not fb:
                        continue
                    vv = self._find_all_name_variants(fb, document_text, p05_already)
                    for v in vv:
                        v["type"] = "fallback"
                    p05_fallbacks.extend(vv)
                    p05_already.update(v["char_start"] for v in vv)

                p05_all = p05_unac + p05_fallbacks + p05_standard
                if p05_all:
                    p05_suggested: List[Dict[str, Any]] = []
                    if p05_unac:
                        if standard_position:
                            p05_suggested.append(
                                {"label": "Standard position", "type": "standard", "text": standard_position}
                            )
                        for idx, fb in enumerate(fallback_positions):
                            if fb:
                                p05_suggested.append(
                                    {"label": f"Fallback {idx + 1}", "type": "fallback", "text": fb}
                                )
                        p05_status = "violation"
                        p05_ui = "not_acceptable"
                        p05_issue = f"Найдено {len(p05_unac)} недопустимых формулировок в документе."
                        p05_first = p05_unac[0]
                    elif p05_fallbacks:
                        if standard_position:
                            p05_suggested.append(
                                {"label": "Standard position", "type": "standard", "text": standard_position}
                            )
                        p05_status = "warning"
                        p05_ui = "needs_review"
                        p05_issue = (
                            f"Найдено {len(p05_fallbacks)} запасных формулировок. "
                            "Рекомендуется привести к стандартной позиции."
                        )
                        p05_first = p05_fallbacks[0]
                    else:
                        p05_status = "passed"
                        p05_ui = "acceptable"
                        p05_issue = ""
                        p05_first = p05_standard[0]

                    return RuleCheckResult(
                        rule_id=rule.id,
                        rule_name=rule.rule_name,
                        rule_type=rule.rule_type,
                        clause_category=rule.clause_category,
                        status=p05_status,
                        found_text=p05_first["phrase"],
                        location={
                            "char_start": p05_first["char_start"],
                            "char_end": p05_first["char_end"],
                            "start": p05_first["char_start"],
                            "end": p05_first["char_end"],
                            "source": "keyword_scan",
                        },
                        issue_description=p05_issue,
                        suggested_fix="" if p05_status == "passed" else (
                            standard_position or (fallback_positions[0] if fallback_positions else "")
                        ),
                        confidence=0.9,
                        reasoning="Поиск по ключевому слову из фразы нашёл вхождения.",
                        ui_status=p05_ui,
                        guidance=guidance,
                        suggested_options=p05_suggested,
                        occurrences=p05_all,
                    )

        # ---------------------------------------------------------------
        # Phase 1: No direct phrase matches (or no configured phrases).
        # Fall through to heuristic / LLM analysis on the semantic clause.
        # ---------------------------------------------------------------

        # Если LLM не инициализирован — делаем максимально простую эвристику
        if not self.llm:
            if clause is None:
                status = "violation" if mark_missing else "not_found"
                return RuleCheckResult(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    rule_type=rule.rule_type,
                    clause_category=rule.clause_category,
                    status=status,
                    issue_description="Соответствующий пункт не найден в документе",
                    suggested_fix=standard_position or "",
                    ui_status="not_acceptable" if status == "violation" else "needs_review",
                    guidance=guidance,
                )

            text_lower = clause.text.lower()
            std_lower = standard_position.lower()
            fallbacks_lower = [f.lower() for f in fallback_positions]
            unacc_lower = [u.lower() for u in unacceptable_phrases]

            if std_lower and std_lower in text_lower:
                return RuleCheckResult(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    rule_type=rule.rule_type,
                    clause_category=rule.clause_category,
                    status="passed",
                    found_text=clause.text[:1000],
                    location=clause.location,
                    confidence=0.8,
                    reasoning="Формулировка близка к стандартной позиции (по вхождению текста).",
                    ui_status="acceptable",
                    guidance=guidance,
                )

            if any(fb and fb in text_lower for fb in fallbacks_lower):
                # Fallback — допустимо, но лучше стандарт
                # Find the specific fallback phrase that matched (for accurate diff in UI)
                matched_fb = next(
                    (fb for fb in fallback_positions if fb and fb.lower() in text_lower), None
                )
                fb_idx = text_lower.find(matched_fb.lower()) if matched_fb else -1
                fb_context = ""
                if matched_fb and fb_idx != -1:
                    ctx_start = max(0, fb_idx - 80)
                    ctx_end = min(len(clause.text), fb_idx + len(matched_fb) + 80)
                    fb_context = clause.text[ctx_start:ctx_end]
                suggested_options: List[Dict[str, Any]] = []
                if standard_position:
                    suggested_options.append(
                        {"label": "Standard position", "type": "standard", "text": standard_position}
                    )
                fallback_occurrences = []
                if matched_fb and fb_idx != -1:
                    fallback_occurrences = [{
                        "type": "fallback",
                        "phrase": clause.text[fb_idx:fb_idx + len(matched_fb)],
                        "char_start": fb_idx,
                        "char_end": fb_idx + len(matched_fb),
                        "context": fb_context,
                    }]
                return RuleCheckResult(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    rule_type=rule.rule_type,
                    clause_category=rule.clause_category,
                    status="warning",
                    found_text=matched_fb or clause.text[:200],
                    location=clause.location,
                    issue_description="Формулировка соответствует запасному варианту. Лучше привести к стандарту.",
                    suggested_fix=standard_position or "",
                    confidence=0.7,
                    reasoning="Текст совпадает с одним из запасных вариантов (по вхождению текста).",
                    ui_status="needs_review",
                    guidance=guidance,
                    suggested_options=suggested_options,
                    occurrences=fallback_occurrences,
                )

            if any(ua and ua in text_lower for ua in unacc_lower):
                # Недопустимый текст — найти конкретную matched фразу
                matched_ua = next(
                    (ua for ua in unacceptable_phrases if ua and ua.lower() in text_lower), None
                )
                ua_idx = text_lower.find(matched_ua.lower()) if matched_ua else -1
                ua_context = ""
                if matched_ua and ua_idx != -1:
                    ctx_start = max(0, ua_idx - 80)
                    ctx_end = min(len(clause.text), ua_idx + len(matched_ua) + 80)
                    ua_context = clause.text[ctx_start:ctx_end]
                suggested_options: List[Dict[str, Any]] = []
                if standard_position:
                    suggested_options.append(
                        {"label": "Standard position", "type": "standard", "text": standard_position}
                    )
                for idx, fb in enumerate(fallback_positions):
                    if fb:
                        suggested_options.append(
                            {"label": f"Fallback {idx + 1}", "type": "fallback", "text": fb}
                        )
                unac_occurrences = []
                if matched_ua and ua_idx != -1:
                    unac_occurrences = [{
                        "type": "unacceptable",
                        "phrase": clause.text[ua_idx:ua_idx + len(matched_ua)],
                        "char_start": ua_idx,
                        "char_end": ua_idx + len(matched_ua),
                        "context": ua_context,
                    }]
                return RuleCheckResult(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    rule_type=rule.rule_type,
                    clause_category=rule.clause_category,
                    status="violation",
                    found_text=matched_ua or clause.text[:200],
                    location=clause.location,
                    issue_description="Формулировка относится к недопустимым. Требуется замена.",
                    suggested_fix=standard_position or (fallback_positions[0] if fallback_positions else ""),
                    confidence=0.8,
                    reasoning="Текст содержит одну из недопустимых формулировок (по вхождению текста).",
                    ui_status="not_acceptable",
                    guidance=guidance,
                    suggested_options=suggested_options,
                    occurrences=unac_occurrences,
                )

            # Не попали ни в одну категорию — требуется ручная проверка
            suggested_options: List[Dict[str, Any]] = []
            if standard_position:
                suggested_options.append(
                    {"label": "Standard position", "type": "standard", "text": standard_position}
                )
            for idx, fb in enumerate(fallback_positions):
                if fb:
                    suggested_options.append(
                        {"label": f"Fallback {idx + 1}", "type": "fallback", "text": fb}
                    )
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="warning",
                found_text=clause.text[:1000] if clause else "",
                location=clause.location if clause else {},
                issue_description="Формулировка не совпадает ни со стандартом, ни с fallback, ни с недопустимыми. Требуется проверка.",
                suggested_fix=standard_position or "",
                confidence=0.6,
                reasoning="Эвристическая проверка без LLM не смогла однозначно классифицировать формулировку.",
                ui_status="needs_review",
                guidance=guidance,
                suggested_options=suggested_options,
            )

        # Если LLM инициализирован — используем HARVEY_RULE_PROMPT
        if clause is None:
            # Конкретный пункт не найден — используем весь текст документа,
            # чтобы LLM сам нашёл нужный раздел и проверил правило.
            if document_text:
                doc_excerpt = document_text[:10000]
                clause = ExtractedClause(
                    category=rule.clause_category or "other",
                    title=f"Полный текст документа (раздел «{rule.rule_name}» не был выделен отдельно)",
                    text=doc_excerpt,
                    location={},
                )
            else:
                # Текст документа недоступен — возвращаем not_found
                status = "violation" if mark_missing else "not_found"
                ui_status = "not_acceptable" if status == "violation" else "needs_review"
                suggested_options: List[Dict[str, Any]] = []
                if standard_position:
                    suggested_options.append(
                        {"label": "Standard position", "type": "standard", "text": standard_position}
                    )
                for idx, fb in enumerate(fallback_positions):
                    if fb:
                        suggested_options.append(
                            {"label": f"Fallback {idx + 1}", "type": "fallback", "text": fb}
                        )
                return RuleCheckResult(
                    rule_id=rule.id,
                    rule_name=rule.rule_name,
                    rule_type=rule.rule_type,
                    clause_category=rule.clause_category,
                    status=status,
                    issue_description="Соответствующий пункт не найден в документе",
                    suggested_fix=standard_position or "",
                    confidence=0.8,
                    reasoning="Клаузу нужной категории не удалось извлечь из текста договора.",
                    ui_status=ui_status,
                    guidance=guidance,
                    suggested_options=suggested_options,
                )

        try:
            prompt = ChatPromptTemplate.from_template(HARVEY_RULE_PROMPT)
            chain = prompt | self.llm

            response = await chain.ainvoke(
                {
                    "rule_name": rule.rule_name,
                    "rule_type": rule.rule_type,
                    "clause_category": rule.clause_category,
                    "guidance": guidance,
                    "standard_position": standard_position,
                    "fallback_positions": json.dumps(fallback_positions, ensure_ascii=False),
                    "unacceptable_phrases": json.dumps(unacceptable_phrases, ensure_ascii=False),
                    "clause_text": clause.text,
                }
            )

            json_match = re.search(r"\{[\s\S]*\}", response.content)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = {}
        except Exception as e:
            logger.error("Harvey LLM check error for rule %s: %s", rule.id, e, exc_info=True)
            data = {}

        classification = data.get("classification", "unknown")
        status = data.get("status", "warning")
        confidence = float(data.get("confidence", 0.7) or 0.7)
        issue_description = data.get("issue_description") or ""
        reasoning = data.get("reasoning") or ""
        llm_found_excerpt = (data.get("found_excerpt") or "").strip()

        ui_status = ""
        suggested_options: List[Dict[str, Any]] = []

        # Подготовим список вариантов замены
        if standard_position:
            suggested_options.append(
                {"label": "Standard position", "type": "standard", "text": standard_position}
            )
        for idx, fb in enumerate(fallback_positions):
            if fb:
                suggested_options.append(
                    {"label": f"Fallback {idx + 1}", "type": "fallback", "text": fb}
                )

        if classification == "standard":
            status = "passed"
            ui_status = "acceptable"
            suggested_options = []  # правки не нужны
        elif classification == "fallback":
            status = "warning"
            ui_status = "needs_review"
            # оставляем только стандарт как целевую правку
            suggested_options = (
                [{"label": "Standard position", "type": "standard", "text": standard_position}]
                if standard_position
                else []
            )
            if not issue_description:
                issue_description = "Формулировка соответствует запасному варианту. Можно улучшить до стандартной позиции."
        elif classification == "unacceptable":
            status = "violation"
            ui_status = "not_acceptable"
            if not issue_description:
                issue_description = "Формулировка относится к списку недопустимых. Требуется замена."
        elif classification == "no_clause":
            if mark_missing:
                status = "violation"
                ui_status = "not_acceptable"
                if not issue_description:
                    issue_description = "Обязательный пункт отсутствует в документе."
            else:
                status = "not_found"
                ui_status = "needs_review"
                if not issue_description:
                    issue_description = "Похожий пункт не найден, возможно, он отсутствует или сформулирован иначе."
        else:  # unknown
            status = "warning"
            ui_status = "needs_review"
            if not issue_description:
                issue_description = "Формулировка не совпадает ни со стандартом, ни с fallback, ни с недопустимыми. Требуется проверка."

        # suggested_fix только для правил с нарушениями — для passed не нужна правка
        main_fix = "" if status == "passed" else (standard_position or (fallback_positions[0] if fallback_positions else ""))

        # found_text: prefer the LLM-extracted excerpt (precise quote from the doc).
        # Fall back to keyword search around the standard_position words.
        raw_clause_text = clause.text

        def _extract_short_excerpt(text: str, anchor: str, window: int = 80) -> str:
            """Find anchor word(s) in text and return a tight context window."""
            # Try each word of the anchor phrase, longest first
            words = [w.rstrip(".,;:()") for w in anchor.split() if len(w) > 2]
            words.sort(key=len, reverse=True)
            text_lower = text.lower()
            for word in words:
                pos = text_lower.find(word.lower())
                if pos != -1:
                    start = pos
                    end = min(len(text), pos + window)
                    return text[start:end].strip()
            return ""

        # Post-scan: find ALL occurrences of standard/fallback phrases in the full document,
        # using fuzzy match (strip trailing punctuation to catch "Абумов Е.Г," vs "Абумов Е.Г.")
        post_occurrences: List[Dict[str, Any]] = []
        if document_text:
            doc_lower = document_text.lower()
            phrases_to_scan = []
            if standard_position:
                phrases_to_scan.append(("standard", standard_position))
            for fb in fallback_positions:
                if fb:
                    phrases_to_scan.append(("fallback", fb))
            # Also scan for short form of LLM excerpt — catches document variants like
            # "Абумов Е Г" (no dots) when the standard is "Абумов Е.Г." (with dots).
            # Take text before the first comma/semicolon/newline as the short phrase.
            if llm_found_excerpt and 3 < len(llm_found_excerpt) <= 200:
                short_form = re.split(r'[,;\n]', llm_found_excerpt.strip())[0].strip()
                already_covered = {(p.rstrip(".,;: ")).lower() for _, p in phrases_to_scan}
                if 3 < len(short_form) <= 60 and short_form.lower() not in already_covered:
                    phrases_to_scan.append(("standard", short_form))
            for phrase_type, phrase in phrases_to_scan:
                stripped = phrase.rstrip(".,;: ")
                phrase_lower = stripped.lower()
                if not phrase_lower:
                    continue
                start = 0
                found_any_exact = False
                while True:
                    pos = doc_lower.find(phrase_lower, start)
                    if pos == -1:
                        break
                    found_any_exact = True
                    ctx_start = max(0, pos - 60)
                    ctx_end = min(len(document_text), pos + len(stripped) + 60)
                    post_occurrences.append({
                        "type": phrase_type,
                        "phrase": document_text[pos:pos + len(stripped)],
                        "char_start": pos,
                        "char_end": pos + len(stripped),
                        "context": document_text[ctx_start:ctx_end],
                    })
                    start = pos + len(stripped)
                # Blank-tolerant prefix match for template phrases (catches comma-after-blanks variants)
                if not found_any_exact and phrase_type == "fallback":
                    prefix_pos = self._get_blank_prefix_pos(stripped, doc_lower)
                    if prefix_pos is not None:
                        # Check not already covered by another occurrence
                        already_covered = {occ["char_start"] for occ in post_occurrences}
                        if not any(abs(prefix_pos - s) <= 5 for s in already_covered):
                            cap_len = min(len(stripped) + 20, len(document_text) - prefix_pos)
                            phrase_found = document_text[prefix_pos:prefix_pos + cap_len]
                            end_m = re.search(r'[.!?\n]', phrase_found[10:]) if len(phrase_found) > 10 else None
                            if end_m:
                                phrase_found = phrase_found[:10 + end_m.start() + 1]
                            ctx_start = max(0, prefix_pos - 60)
                            ctx_end = min(len(document_text), prefix_pos + len(phrase_found) + 60)
                            post_occurrences.append({
                                "type": phrase_type,
                                "phrase": phrase_found,
                                "char_start": prefix_pos,
                                "char_end": prefix_pos + len(phrase_found),
                                "context": document_text[ctx_start:ctx_end],
                            })

        # Keyword-based scan to catch standard name variants not found by exact phrase scan.
        # Only runs in Phase 1 (LLM path). Phase 0.5 handles the pre-LLM keyword scan.
        # If the keyword scan finds the standard phrase AND the LLM was uncertain or said
        # "no_clause" (possibly due to wrong semantic chunk), trust the keyword scan.
        if standard_position and document_text:
            already_found = {occ["char_start"] for occ in post_occurrences}
            variants = self._find_all_name_variants(standard_position, document_text, already_found)
            post_occurrences.extend(variants)
            if variants and classification in ("unknown", "no_clause") and status in ("warning", "not_found"):
                status = "passed"
                ui_status = "acceptable"
                issue_description = ""
                suggested_options = []

        # found_text: use exact phrase from first post-scan occurrence when available
        # (most precise — actual text in document, right length for scrollToText)
        if post_occurrences:
            found_text_for_result = post_occurrences[0]["phrase"]
        else:
            # Accept LLM excerpt only if it's a precise verbatim quote (not an abbreviation with ...)
            excerpt_is_precise = (
                llm_found_excerpt
                and 3 < len(llm_found_excerpt) <= 150
                and "..." not in llm_found_excerpt
                and "…" not in llm_found_excerpt
                and llm_found_excerpt.count("\n") <= 1
            )
            if excerpt_is_precise:
                found_text_for_result = llm_found_excerpt
            elif standard_position:
                found_text_for_result = (
                    _extract_short_excerpt(raw_clause_text, standard_position)
                    or _extract_short_excerpt(document_text, standard_position)
                    or raw_clause_text[:150]
                )
            else:
                found_text_for_result = raw_clause_text[:150]

        return RuleCheckResult(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            clause_category=rule.clause_category,
            status=status,
            found_text=found_text_for_result,
            location=clause.location,
            issue_description=issue_description,
            suggested_fix=main_fix,
            confidence=confidence,
            reasoning=reasoning,
            ui_status=ui_status,
            guidance=guidance,
            suggested_options=suggested_options,
            occurrences=post_occurrences,
        )
    
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
                    found_text=clause.text[:1000],
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
            found_text=clause.text[:1000],
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
                found_text=clause.text[:1000] if clause else "",
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
                found_text=clause.text[:1000],
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
                found_text=clause.text[:1000],
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
            found_text=clause.text[:1000],
            location=clause.location,
            confidence=0.85,
            reasoning=f"Значение {extracted_value} в допустимых пределах"
        )
    
    def _parse_duration_to_days(self, duration_str: str) -> Optional[float]:
        """Parse a duration string to number of days.
        Handles RU/EN: '3 года', '6 месяцев', '2 years', '30 дней', etc.
        Returns None if can't parse.
        """
        if not duration_str:
            return None
        s = str(duration_str).lower().strip()
        patterns = [
            (r'(\d+(?:[.,]\d+)?)\s*(?:лет|год|года|г\.)', 365),
            (r'(\d+(?:[.,]\d+)?)\s*(?:месяц|месяцев|месяца|мес\.?)', 30),
            (r'(\d+(?:[.,]\d+)?)\s*(?:недел[ьяи]|нед\.?)', 7),
            (r'(\d+(?:[.,]\d+)?)\s*(?:день|дней|дня|дн\.?)', 1),
            (r'(\d+(?:[.,]\d+)?)\s*years?', 365),
            (r'(\d+(?:[.,]\d+)?)\s*months?', 30),
            (r'(\d+(?:[.,]\d+)?)\s*weeks?', 7),
            (r'(\d+(?:[.,]\d+)?)\s*days?', 1),
        ]
        for pattern, multiplier in patterns:
            match = re.search(pattern, s, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1).replace(',', '.'))
                    return value * multiplier
                except ValueError:
                    continue
        return None

    async def _check_duration(
        self,
        rule: PlaybookRule,
        clause: Optional[ExtractedClause]
    ) -> RuleCheckResult:
        """Check duration_check condition with actual min/max comparison"""
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
        min_duration = config.get("min_duration")
        max_duration = config.get("max_duration")

        # Extract duration from clause key_values or via regex
        duration_value = clause.key_values.get("duration")

        if duration_value is None:
            duration_patterns = [
                r'(\d+(?:[.,]\d+)?)\s*(?:лет|год|года|г\.)',
                r'(\d+(?:[.,]\d+)?)\s*(?:месяц|месяцев|месяца|мес\.?)',
                r'(\d+(?:[.,]\d+)?)\s*(?:недел[ьяи]|нед\.?)',
                r'(\d+(?:[.,]\d+)?)\s*(?:день|дней|дня|дн\.?)',
                r'(\d+(?:[.,]\d+)?)\s*years?',
                r'(\d+(?:[.,]\d+)?)\s*months?',
                r'(\d+(?:[.,]\d+)?)\s*days?',
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
                found_text=clause.text[:1000],
                location=clause.location,
                issue_description="Не удалось извлечь срок из пункта",
                confidence=0.6
            )

        # Parse to days for comparison
        duration_days = self._parse_duration_to_days(str(duration_value))
        min_days = self._parse_duration_to_days(str(min_duration)) if min_duration else None
        max_days = self._parse_duration_to_days(str(max_duration)) if max_duration else None

        if duration_days is None:
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="passed",
                found_text=clause.text[:1000],
                location=clause.location,
                confidence=0.6,
                reasoning=f"Найден срок: {duration_value}. Не удалось привести к числу для сравнения."
            )

        violation = False
        issue = ""

        if min_days is not None and duration_days < min_days:
            violation = True
            issue = f"Срок {duration_value} меньше минимально допустимого ({min_duration})"

        if max_days is not None and duration_days > max_days:
            violation = True
            issue = f"Срок {duration_value} превышает максимально допустимый ({max_duration})"

        if violation:
            fix_parts = []
            if min_duration:
                fix_parts.append(f"минимум: {min_duration}")
            if max_duration:
                fix_parts.append(f"максимум: {max_duration}")
            return RuleCheckResult(
                rule_id=rule.id,
                rule_name=rule.rule_name,
                rule_type=rule.rule_type,
                clause_category=rule.clause_category,
                status="violation",
                found_text=clause.text[:1000],
                location=clause.location,
                issue_description=issue,
                suggested_fix=f"Изменить срок ({', '.join(fix_parts)})",
                confidence=0.85,
                reasoning=f"Найденный срок: {duration_value} (~{duration_days:.0f} дней)"
            )

        return RuleCheckResult(
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_type=rule.rule_type,
            clause_category=rule.clause_category,
            status="passed",
            found_text=clause.text[:1000],
            location=clause.location,
            confidence=0.85,
            reasoning=f"Срок {duration_value} в допустимых пределах"
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
                found_text=clause.text[:1000] if clause else "",
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
                found_text=clause.text[:1000] if clause else "",
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
            found_text=clause.text[:1000] if clause else "",
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
                found_text=clause.text[:1000] if clause else "",
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
            found_text=clause.text[:1000] if clause else "",
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
                    found_text=clause.text[:1000],
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
            found_text=clause.text[:1000] if clause else "",
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
            "ui_status": result.ui_status,
            "guidance": result.guidance,
            "suggested_options": result.suggested_options,
            "occurrences": result.occurrences,
            "rule_standard_phrases": result.rule_standard_phrases,
            "rule_fallback_phrases": result.rule_fallback_phrases,
            "rule_unacceptable_phrases": result.rule_unacceptable_phrases,
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

