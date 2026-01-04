"""Complexity Classifier - классификация запросов на simple (RAG) vs complex (Agent)"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import re
import hashlib
import logging
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

logger = logging.getLogger(__name__)


class ClassificationResult(BaseModel):
    """Результат классификации запроса"""
    label: str = Field(..., description="Тип запроса: 'simple' (RAG) или 'complex' (Agent)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность в классификации (0.0-1.0)")
    rationale: str = Field(..., description="Объяснение решения")
    recommended_path: Optional[str] = Field(None, description="Рекомендуемый путь: 'rag' или 'agent'")


def normalize_text(text: str) -> str:
    """
    Нормализация текста для классификации
    
    Args:
        text: Исходный текст
        
    Returns:
        Нормализованный текст
    """
    # Удаляем лишние пробелы и приводим к нижнему регистру
    normalized = re.sub(r'\s+', ' ', text.strip().lower())
    return normalized


def make_classification_cache_key(question: str) -> str:
    """
    Создает cache key для результата классификации
    
    Args:
        question: Входной вопрос
        
    Returns:
        Cache key (хеш нормализованного текста)
    """
    normalized = normalize_text(question)
    key_hash = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    return f"classification:{key_hash}"


class ComplexityClassifier:
    """
    Классификатор сложности запросов:
    - simple: простые вопросы → RAG путь
    - complex: сложные задачи → Agent путь
    """
    
    def __init__(self, llm, cache=None):
        """
        Инициализация ComplexityClassifier
        
        Args:
            llm: LLM для классификации
            cache: Опциональный кэш для результатов классификации
        """
        self.llm = llm
        self.cache = cache
    
    def classify(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ClassificationResult:
        """
        Классифицировать запрос на simple/complex
        
        Args:
            query: Запрос пользователя
            context: Опциональный контекст (case_id, user_id, и т.д.)
            
        Returns:
            ClassificationResult с label, confidence, rationale, recommended_path
        """
        # 1. Нормализация входного текста
        normalized_question = normalize_text(query)
        question_lower = normalized_question.lower()
        
        # 2. Rule-based проверка (fast path)
        # Паттерны для запросов статей кодексов - всегда SIMPLE (RAG)
        article_patterns = [
            r'статья\s+\d+\s+(гпк|гк|апк|ук|нк|тк|ск|жк|зкпп|кас)',
            r'\d+\s+статья\s+(гпк|гк|апк|ук|нк|тк|ск|жк|зкпп|кас)',
            r'статья\s+\d+\s+(гражданск|арбитраж|уголовн|налогов|трудов|семейн|жилищн|земельн|конституционн)',
            r'пришли\s+статью',
            r'покажи\s+статью',
            r'найди\s+статью',
            r'текст\s+статьи',
        ]
        
        for pattern in article_patterns:
            if re.search(pattern, question_lower):
                logger.info(f"Pre-classified '{query[:50]}...' as SIMPLE (matches article request pattern)")
                return ClassificationResult(
                    label="simple",
                    confidence=0.99,
                    rationale="Запрос на получение текста статьи кодекса - простой вопрос для RAG",
                    recommended_path="rag"
                )
        
        # Паттерны для приветствий - всегда SIMPLE
        greeting_patterns = [
            r'^(привет|здравствуй|здравствуйте|добрый\s+(день|вечер|утро)|hello|hi)',
        ]
        
        for pattern in greeting_patterns:
            if re.search(pattern, question_lower):
                logger.info(f"Pre-classified '{query[:50]}...' as SIMPLE (matches greeting pattern)")
                return ClassificationResult(
                    label="simple",
                    confidence=0.95,
                    rationale="Приветствие - простой вопрос для RAG",
                    recommended_path="rag"
                )
        
        # Паттерны для сложных задач - всегда COMPLEX
        task_patterns = [
            r'(извлеки|извлечь|найди|найти|проанализируй|проанализировать|составь|составить|создай|создать)',
            r'(таблиц|таблица|отчет|отчёт|резюме|анализ|противоречи|риск)',
            r'(классифицируй|классифицировать|проверь|проверить)',
        ]
        
        # Проверяем наличие паттернов задач И отсутствие простых вопросов
        has_task_pattern = any(re.search(pattern, question_lower) for pattern in task_patterns)
        simple_question_words = ['что', 'какие', 'где', 'когда', 'кто', 'сколько', 'какой', 'почему']
        has_simple_question = any(word in question_lower for word in simple_question_words)
        
        if has_task_pattern and not has_simple_question and len(query.split()) > 5:
            logger.info(f"Pre-classified '{query[:50]}...' as COMPLEX (matches task pattern)")
            return ClassificationResult(
                label="complex",
                confidence=0.90,
                rationale="Запрос содержит команды на выполнение анализа - требует агентной оркестрации",
                recommended_path="agent"
            )
        
        # 3. Проверка кэша
        if self.cache:
            cache_key = make_classification_cache_key(query)
            cached_result = self.cache.get("classification", normalized_question)
            
            if cached_result:
                label = cached_result.get("label", "simple")
                cached_confidence = cached_result.get("confidence", 1.0)
                rationale = cached_result.get("rationale", "From cache")
                logger.info(f"Cache hit for classification: '{query[:50]}...' -> {label} (confidence: {cached_confidence:.2f})")
                return ClassificationResult(
                    label=label,
                    confidence=cached_confidence,
                    rationale=rationale,
                    recommended_path="rag" if label == "simple" else "agent"
                )
        
        # 4. LLM классификация с structured output
        return self._llm_classify(query, normalized_question)
    
    def _llm_classify(self, query: str, normalized_question: str) -> ClassificationResult:
        """
        Классификация через LLM с structured output
        
        Args:
            query: Оригинальный запрос
            normalized_question: Нормализованный запрос
            
        Returns:
            ClassificationResult
        """
        # Получаем список доступных агентов для промпта
        from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
        
        agents_list = []
        for agent_name, agent_info in AVAILABLE_ANALYSES.items():
            description = agent_info["description"]
            keywords = ", ".join(agent_info["keywords"][:3])
            agents_list.append(f"- {agent_name}: {description} (ключевые слова: {keywords})")
        
        agents_text = "\n".join(agents_list)
        
        # Few-shot примеры для классификации
        few_shot_examples = [
            (HumanMessage(content="Запрос: Извлеки все даты из документов"), 
             AIMessage(content='{"label": "complex", "confidence": 0.95, "rationale": "Требует выполнения агента entity_extraction"}')),
            (HumanMessage(content="Запрос: Какие ключевые сроки важны в этом деле?"), 
             AIMessage(content='{"label": "simple", "confidence": 0.98, "rationale": "Информационный вопрос для RAG чата"}')),
            (HumanMessage(content="Запрос: Пришли статью 135 ГПК"), 
             AIMessage(content='{"label": "simple", "confidence": 0.99, "rationale": "Запрос на получение текста статьи кодекса"}')),
            (HumanMessage(content="Запрос: Найди противоречия между документами"), 
             AIMessage(content='{"label": "complex", "confidence": 0.92, "rationale": "Требует выполнения агента discrepancy"}')),
            (HumanMessage(content="Запрос: Что говорится в договоре о сроках?"), 
             AIMessage(content='{"label": "simple", "confidence": 0.96, "rationale": "Вопрос о содержании документов для RAG"}')),
            (HumanMessage(content="Запрос: Составь таблицу с судьями и судами"), 
             AIMessage(content='{"label": "complex", "confidence": 0.94, "rationale": "Требует создания структурированной таблицы через агентов"}')),
        ]
        
        system_content = f"""Ты классификатор запросов пользователя в системе анализа юридических документов.

В системе доступны следующие агенты для выполнения задач:

{agents_text}

Определи тип запроса:

SIMPLE (simple) - простые вопросы для RAG чата:
- Вопросы с "какие", "что", "где", "когда", "кто", "почему"
- Разговорные фразы: "как дела", "привет"
- Запросы на получение информации (статьи кодексов, норм права, текстов документов)
- Требует немедленного ответа на основе уже загруженных документов или юридических источников
- Примеры: "Какие ключевые сроки важны в этом деле?", "Что говорится в договоре о сроках?", "Пришли статью 135 ГПК"

COMPLEX (complex) - сложные задачи для агентной оркестрации:
- Запрос относится к функциям агентов (извлечение дат, поиск противоречий, анализ рисков и т.д.)
- Требует запуска фонового анализа через агентов
- Многошаговые задачи с зависимостями
- Примеры: "Извлеки все даты из документов", "Найди противоречия", "Проанализируй риски", "Создай резюме дела", "составь таблицу с судьями и судами"

Возвращай строго JSON с полями:
- label: "simple" или "complex"
- confidence: число от 0.0 до 1.0 (уверенность в классификации)
- rationale: краткое объяснение решения (1-2 предложения)
- recommended_path: "rag" для simple, "agent" для complex

Отвечай ТОЛЬКО валидным JSON, без дополнительного текста."""
        
        # Создаем промпт с few-shot примерами
        messages = [SystemMessage(content=system_content)]
        for human_msg, ai_msg in few_shot_examples:
            messages.append(human_msg)
            messages.append(ai_msg)
        messages.append(HumanMessage(content=f"Запрос: {query}"))
        
        try:
            # Используем structured output если поддерживается
            if hasattr(self.llm, 'with_structured_output'):
                try:
                    structured_llm = self.llm.with_structured_output(ClassificationResult, include_raw=True)
                    response = structured_llm.invoke(messages)
                    
                    if hasattr(response, 'parsed') and response.parsed:
                        classification = response.parsed
                    elif isinstance(response, ClassificationResult):
                        classification = response
                    else:
                        # Fallback: парсим из raw
                        raw_content = getattr(response, 'raw', {}).get('content', '{}') if hasattr(response, 'raw') else str(response)
                        import json
                        data = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
                        classification = ClassificationResult(**data)
                except Exception as e:
                    logger.warning(f"Structured output failed, falling back to JSON parsing: {e}")
                    classification = self._parse_json_response(messages)
            else:
                classification = self._parse_json_response(messages)
            
            # Сохраняем в кэш
            if self.cache:
                cache_key = make_classification_cache_key(query)
                self.cache.set(
                    "classification",
                    normalized_question,
                    {
                        "label": classification.label,
                        "confidence": classification.confidence,
                        "rationale": classification.rationale
                    },
                    ttl=3600  # 1 час
                )
            
            # Устанавливаем recommended_path на основе label
            if not classification.recommended_path:
                classification.recommended_path = "rag" if classification.label == "simple" else "agent"
            
            logger.info(f"Classified '{query[:50]}...' as {classification.label} (confidence: {classification.confidence:.2f}, path: {classification.recommended_path})")
            return classification
            
        except Exception as e:
            logger.error(f"Error in LLM classification: {e}", exc_info=True)
            # Fallback: считаем простым вопросом
            return ClassificationResult(
                label="simple",
                confidence=0.5,
                rationale=f"Ошибка классификации, fallback на simple: {str(e)}",
                recommended_path="rag"
            )
    
    def _parse_json_response(self, messages) -> ClassificationResult:
        """
        Парсинг JSON ответа от LLM (fallback метод)
        
        Args:
            messages: Сообщения для LLM
            
        Returns:
            ClassificationResult
        """
        response = self.llm.invoke(messages)
        content = response.content if hasattr(response, 'content') else str(response)
        
        # Извлекаем JSON из ответа
        import json
        import re
        
        # Пытаемся найти JSON в ответе
        json_match = re.search(r'\{[^{}]*"label"[^{}]*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = content
        
        try:
            data = json.loads(json_str)
            return ClassificationResult(**data)
        except Exception as e:
            logger.warning(f"Failed to parse JSON response: {e}, content: {content[:200]}")
            # Fallback
            return ClassificationResult(
                label="simple",
                confidence=0.5,
                rationale="Не удалось распарсить ответ LLM",
                recommended_path="rag"
            )

