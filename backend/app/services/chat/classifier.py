"""
Request Classifier - Классификатор запросов пользователя

Определяет тип запроса:
- task: требует выполнения агентов (анализ, извлечение, таблицы)
- question: простой вопрос для RAG-ответа

Использует:
1. Rule-based проверки (fast path)
2. Кэширование результатов
3. LLM классификацию с structured output
"""
from typing import Optional, Literal
from pydantic import BaseModel, Field
import hashlib
import re
import logging

logger = logging.getLogger(__name__)


class ClassificationResult(BaseModel):
    """Результат классификации запроса"""
    label: Literal["task", "question"] = Field(..., description="Метка: task или question")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность (0-1)")
    rationale: Optional[str] = Field(None, description="Обоснование")
    
    @property
    def is_task(self) -> bool:
        """Является ли запрос задачей"""
        return self.label == "task"
    
    @property
    def is_question(self) -> bool:
        """Является ли запрос вопросом"""
        return self.label == "question"


class RequestClassifier:
    """
    Классификатор запросов пользователя.
    
    Определяет, нужен ли для запроса агент (task) или достаточно RAG (question).
    
    Использует трёхуровневую стратегию:
    1. Rule-based (паттерны) - мгновенно
    2. Кэш - быстро
    3. LLM - точно, но медленно
    """
    
    # Паттерны для запросов статей кодексов - всегда QUESTION
    ARTICLE_PATTERNS = [
        r'статья\s+\d+\s+(гпк|гк|апк|ук|нк|тк|ск|жк|зкпп|кас)',
        r'\d+\s+статья\s+(гпк|гк|апк|ук|нк|тк|ск|жк|зкпп|кас)',
        r'статья\s+\d+\s+(гражданск|арбитраж|уголовн|налогов|трудов|семейн|жилищн|земельн|конституционн)',
        r'пришли\s+статью',
        r'покажи\s+статью',
        r'найди\s+статью',
        r'текст\s+статьи',
    ]
    
    # Паттерны для приветствий - всегда QUESTION
    GREETING_PATTERNS = [
        r'^(привет|здравствуй|здравствуйте|добрый\s+(день|вечер|утро)|hello|hi)',
    ]
    
    # Паттерны для задач - скорее всего TASK
    TASK_PATTERNS = [
        r'извлеки\s+(все\s+)?(даты|сроки|суммы|имена|организации)',
        r'найди\s+(все\s+)?противоречия',
        r'проанализируй\s+риски',
        r'создай\s+(резюме|таблицу|отчёт|отчет)',
        r'составь\s+таблицу',
        r'сравни\s+документы',
        r'классифицируй\s+документ',
    ]
    
    def __init__(self, llm=None, cache=None, confidence_threshold: float = 0.6):
        """
        Инициализация классификатора
        
        Args:
            llm: LLM для классификации (опционально)
            cache: Менеджер кэша (опционально)
            confidence_threshold: Порог уверенности для принятия решения
        """
        self.llm = llm
        self.cache = cache
        self.confidence_threshold = confidence_threshold
    
    @staticmethod
    def normalize_text(text: str) -> str:
        """Нормализует текст: lower, strip, убирает лишние пробелы"""
        return " ".join(text.lower().strip().split())
    
    @staticmethod
    def make_cache_key(question: str) -> str:
        """Создаёт cache key для результата классификации"""
        normalized = RequestClassifier.normalize_text(question)
        key_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        return f"classification:{key_hash}"
    
    def _check_rule_based(self, question: str) -> Optional[ClassificationResult]:
        """
        Rule-based классификация (fast path)
        
        Returns:
            ClassificationResult если паттерн найден, иначе None
        """
        question_lower = question.lower()
        
        # Проверяем паттерны статей кодексов → QUESTION
        for pattern in self.ARTICLE_PATTERNS:
            if re.search(pattern, question_lower):
                logger.info(f"Rule-based: '{question[:50]}…' → QUESTION (article pattern)")
                return ClassificationResult(
                    label="question",
                    confidence=0.99,
                    rationale=f"Matches article request pattern: {pattern}"
                )
        
        # Проверяем приветствия → QUESTION
        for pattern in self.GREETING_PATTERNS:
            if re.search(pattern, question_lower):
                logger.info(f"Rule-based: '{question[:50]}…' → QUESTION (greeting)")
                return ClassificationResult(
                    label="question",
                    confidence=0.99,
                    rationale="Matches greeting pattern"
                )
        
        # Проверяем паттерны задач → TASK
        for pattern in self.TASK_PATTERNS:
            if re.search(pattern, question_lower):
                logger.info(f"Rule-based: '{question[:50]}…' → TASK (task pattern)")
                return ClassificationResult(
                    label="task",
                    confidence=0.90,
                    rationale=f"Matches task pattern: {pattern}"
                )
        
        return None
    
    def _check_cache(self, question: str) -> Optional[ClassificationResult]:
        """
        Проверяет кэш
        
        Returns:
            ClassificationResult если найден в кэше, иначе None
        """
        if not self.cache:
            return None
        
        normalized = self.normalize_text(question)
        cached = self.cache.get("classification", normalized)
        
        if cached:
            logger.info(f"Cache hit: '{question[:50]}…' → {cached.get('label')}")
            return ClassificationResult(
                label=cached.get("label", "question"),
                confidence=cached.get("confidence", 1.0),
                rationale=cached.get("rationale", "From cache")
            )
        
        return None
    
    async def _classify_with_llm(self, question: str) -> ClassificationResult:
        """
        Классификация через LLM
        
        Returns:
            ClassificationResult
        """
        if not self.llm:
            logger.warning("LLM not available, defaulting to QUESTION")
            return ClassificationResult(
                label="question",
                confidence=0.5,
                rationale="LLM not available"
            )
        
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        
        # Получаем список доступных агентов
        try:
            from app.services.langchain_agents.legacy_stubs import AVAILABLE_ANALYSES
            agents_list = []
            for agent_name, agent_info in AVAILABLE_ANALYSES.items():
                description = agent_info["description"]
                keywords = ", ".join(agent_info["keywords"][:3])
                agents_list.append(f"- {agent_name}: {description} (ключевые слова: {keywords})")
            agents_text = "\n".join(agents_list)
        except Exception:
            agents_text = "- timeline: Анализ хронологии\n- risk: Анализ рисков\n- discrepancy: Поиск противоречий"
        
        # Few-shot примеры
        few_shot_examples = [
            (HumanMessage(content="Запрос: Извлеки все даты из документов"), 
             AIMessage(content='{"label": "task", "confidence": 0.95, "rationale": "Требует выполнения агента entity_extraction"}')),
            (HumanMessage(content="Запрос: Какие ключевые сроки важны в этом деле?"), 
             AIMessage(content='{"label": "question", "confidence": 0.98, "rationale": "Информационный вопрос для RAG чата"}')),
            (HumanMessage(content="Запрос: Пришли статью 135 ГПК"), 
             AIMessage(content='{"label": "question", "confidence": 0.99, "rationale": "Запрос на получение текста статьи кодекса"}')),
            (HumanMessage(content="Запрос: Найди противоречия между документами"), 
             AIMessage(content='{"label": "task", "confidence": 0.92, "rationale": "Требует выполнения агента discrepancy"}')),
            (HumanMessage(content="Запрос: Что говорится в договоре о сроках?"), 
             AIMessage(content='{"label": "question", "confidence": 0.96, "rationale": "Вопрос о содержании документов для RAG"}')),
        ]
        
        system_content = f"""Ты классификатор запросов в системе анализа юридических документов.

Доступные агенты:
{agents_text}

Определи тип запроса:

ЗАДАЧА (task) - если требует выполнения агентов:
- Извлечение данных (даты, суммы, имена)
- Поиск противоречий
- Анализ рисков
- Создание таблиц/отчётов
- Примеры: "Извлеки все даты", "Найди противоречия", "Составь таблицу"

ВОПРОС (question) - если это вопрос для RAG:
- Вопросы "какие", "что", "где", "когда"
- Запросы статей кодексов
- Вопросы о содержании документов
- Примеры: "Что говорится в договоре?", "Пришли статью 135 ГПК"

Возвращай JSON:
{{"label": "task" или "question", "confidence": 0.0-1.0, "rationale": "краткое объяснение"}}"""
        
        messages = [SystemMessage(content=system_content)]
        for human_msg, ai_msg in few_shot_examples:
            messages.append(human_msg)
            messages.append(ai_msg)
        messages.append(HumanMessage(content=f"Запрос: {question}"))
        
        try:
            # Пробуем structured output
            if hasattr(self.llm, 'with_structured_output'):
                try:
                    structured_llm = self.llm.with_structured_output(ClassificationResult, include_raw=True)
                    response = structured_llm.invoke(messages)
                    
                    if hasattr(response, 'parsed') and response.parsed:
                        return response.parsed
                    elif isinstance(response, dict) and 'parsed' in response and response['parsed']:
                        return response['parsed']
                    elif isinstance(response, ClassificationResult):
                        return response
                except Exception as e:
                    logger.warning(f"Structured output failed: {e}, falling back to JSON parsing")
            
            # Fallback на парсинг JSON
            response = self.llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            import json
            json_match = re.search(r'\{[^}]+\}', response_text)
            if json_match:
                result_dict = json.loads(json_match.group())
                return ClassificationResult(
                    label=result_dict.get("label", "question"),
                    confidence=float(result_dict.get("confidence", 0.5)),
                    rationale=result_dict.get("rationale", "")
                )
            
            # Последний fallback
            response_lower = response_text.lower()
            if "task" in response_lower:
                return ClassificationResult(label="task", confidence=0.5, rationale="Fallback parsing")
            return ClassificationResult(label="question", confidence=0.5, rationale="Fallback parsing")
            
        except Exception as e:
            logger.error(f"LLM classification error: {e}", exc_info=True)
            return ClassificationResult(
                label="question",
                confidence=0.5,
                rationale=f"Error: {str(e)[:50]}"
            )
    
    async def classify(self, question: str) -> ClassificationResult:
        """
        Классифицирует запрос пользователя
        
        Args:
            question: Текст запроса
            
        Returns:
            ClassificationResult с меткой и уверенностью
        """
        # 1. Rule-based (fast path)
        rule_result = self._check_rule_based(question)
        if rule_result:
            return rule_result
        
        # 2. Кэш
        cached_result = self._check_cache(question)
        if cached_result:
            return cached_result
        
        # 3. LLM классификация
        llm_result = await self._classify_with_llm(question)
        
        # Применяем порог уверенности
        if llm_result.confidence < self.confidence_threshold:
            logger.warning(f"Low confidence ({llm_result.confidence:.2f}), defaulting to QUESTION")
            llm_result = ClassificationResult(
                label="question",
                confidence=llm_result.confidence,
                rationale=f"Low confidence, fallback to question. Original: {llm_result.rationale}"
            )
        
        # Сохраняем в кэш
        if self.cache:
            normalized = self.normalize_text(question)
            self.cache.set("classification", normalized, {
                "label": llm_result.label,
                "confidence": llm_result.confidence,
                "rationale": llm_result.rationale
            }, ttl=3600)
        
        logger.info(f"Classified: '{question[:50]}…' → {llm_result.label} ({llm_result.confidence:.2f})")
        return llm_result
    
    def classify_sync(self, question: str) -> ClassificationResult:
        """
        Синхронная версия classify (для использования в sync контексте)
        """
        import asyncio
        
        # Проверяем rule-based и кэш синхронно
        rule_result = self._check_rule_based(question)
        if rule_result:
            return rule_result
        
        cached_result = self._check_cache(question)
        if cached_result:
            return cached_result
        
        # Для LLM нужен async
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Если уже в async контексте, создаём новый loop в thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._classify_with_llm(question))
                    return future.result()
            else:
                return loop.run_until_complete(self._classify_with_llm(question))
        except Exception as e:
            logger.error(f"Sync classification error: {e}")
            return ClassificationResult(
                label="question",
                confidence=0.5,
                rationale=f"Sync error: {str(e)[:50]}"
            )


