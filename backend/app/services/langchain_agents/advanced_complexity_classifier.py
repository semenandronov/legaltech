"""Advanced Complexity Classifier - улучшенная классификация запросов с поддержкой hybrid пути"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Literal, Union
import re
import hashlib
import logging
from datetime import datetime
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from app.services.langchain_agents.complexity_classifier import normalize_text

logger = logging.getLogger(__name__)

# Try to import LangGraph Command (для будущей интеграции)
try:
    from langgraph.types import Command
    COMMAND_AVAILABLE = True
except ImportError:
    COMMAND_AVAILABLE = False
    Command = None


class EnhancedClassificationResult(BaseModel):
    """Расширенный результат классификации с поддержкой hybrid пути"""
    label: Literal["simple", "complex", "hybrid"] = Field(
        ..., 
        description="Тип запроса: simple (RAG), complex (Agent), hybrid (RAG + Agent)"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность в классификации (0.0-1.0)")
    rationale: str = Field(..., description="Объяснение решения")
    recommended_path: Literal["rag", "agent", "hybrid"] = Field(
        ..., 
        description="Рекомендуемый путь: rag, agent или hybrid"
    )
    
    # Дополнительные поля для LangGraph routing
    requires_clarification: bool = Field(
        False, 
        description="Требует ли уточнения от пользователя (низкая уверенность)"
    )
    suggested_agents: List[str] = Field(
        default_factory=list,
        description="Предлагаемые агенты для выполнения (если complex/hybrid)"
    )
    rag_queries: List[str] = Field(
        default_factory=list,
        description="Запросы для RAG (если simple/hybrid)"
    )
    estimated_complexity: Literal["low", "medium", "high"] = Field(
        "medium",
        description="Оценка сложности задачи"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Дополнительные метаданные для роутинга"
    )


def make_classification_cache_key(question: str, context: Optional[Dict[str, Any]] = None) -> str:
    """
    Создает cache key для результата классификации
    
    Args:
        question: Входной вопрос
        context: Опциональный контекст
        
    Returns:
        Cache key (хеш нормализованного текста + контекста)
    """
    normalized = normalize_text(question)
    key_data = normalized
    if context and context.get("case_id"):
        key_data += f":{context['case_id']}"
    key_hash = hashlib.sha256(key_data.encode('utf-8')).hexdigest()
    return f"classification:{key_hash}"


class AdvancedComplexityClassifier:
    """
    Продвинутый классификатор, использующий максимум возможностей LangGraph:
    
    1. State-based классификация - учитывает контекст из state
    2. Многоуровневая классификация - simple/complex/hybrid
    3. Поддержка Command для динамической маршрутизации (для будущей интеграции)
    4. Interrupts для человеческой обратной связи (через requires_clarification)
    5. Кэширование и оптимизация
    """
    
    def __init__(self, llm, cache=None, confidence_threshold: float = 0.7):
        """
        Инициализация AdvancedComplexityClassifier
        
        Args:
            llm: LLM для классификации
            cache: Опциональный кэш для результатов классификации
            confidence_threshold: Порог уверенности для interrupts (ниже -> требует уточнения)
        """
        self.llm = llm
        self.cache = cache
        self.confidence_threshold = confidence_threshold
    
    def classify_from_state(
        self,
        state: Dict[str, Any],
        use_command: bool = False
    ) -> Union[EnhancedClassificationResult, 'Command']:
        """
        Классификация на основе state (LangGraph паттерн)
        
        Извлекает запрос из messages в state и классифицирует с учетом:
        - Контекста дела (case_id, workspace_path)
        - История предыдущих запросов
        - Результаты предыдущих анализов
        - Метаданные состояния
        
        Args:
            state: Текущее состояние графа LangGraph (AnalysisState)
            use_command: Использовать Command для маршрутизации (LangGraph 1.0+)
            
        Returns:
            EnhancedClassificationResult или Command для conditional edges
        """
        # Извлекаем последнее сообщение пользователя
        messages = state.get("messages", [])
        user_query = self._extract_user_query(messages)
        
        if not user_query:
            # Fallback: считаем простым вопросом
            result = EnhancedClassificationResult(
                label="simple",
                confidence=0.5,
                rationale="Не удалось извлечь запрос пользователя",
                recommended_path="rag",
                rag_queries=["Общий запрос"]
            )
            return self._wrap_as_command(result, use_command) if use_command else result
        
        # Классифицируем с учетом контекста state
        context = self._build_context_from_state(state)
        classification = self.classify(
            query=user_query,
            context=context
        )
        
        # Проверяем, требуется ли уточнение (низкая уверенность)
        if classification.confidence < self.confidence_threshold:
            classification.requires_clarification = True
            logger.info(
                f"Low confidence classification ({classification.confidence:.2f} < {self.confidence_threshold}): "
                f"'{user_query[:50]}...' -> requires_clarification=True"
            )
        
        return self._wrap_as_command(classification, use_command) if use_command else classification
    
    def classify(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> EnhancedClassificationResult:
        """
        Классифицировать запрос на simple/complex/hybrid
        
        Args:
            query: Запрос пользователя
            context: Опциональный контекст (case_id, workspace_files, previous_results, и т.д.)
            
        Returns:
            EnhancedClassificationResult с детальной информацией
        """
        # 1. Нормализация
        normalized_query = normalize_text(query)
        query_lower = normalized_query.lower()
        
        # 2. Rule-based проверка (fast path)
        fast_result = self._rule_based_classify(query, query_lower, context)
        if fast_result:
            return fast_result
        
        # 3. Проверка кэша
        if self.cache:
            cache_key = make_classification_cache_key(normalized_query, context)
            cached = self.cache.get("classification", cache_key)
            if cached:
                logger.info(f"Cache hit for classification: '{query[:50]}...'")
                try:
                    return EnhancedClassificationResult(**cached)
                except Exception as e:
                    logger.warning(f"Failed to parse cached result: {e}, recalculating")
        
        # 4. LLM классификация с учетом контекста
        result = self._llm_classify_with_context(query, normalized_query, context)
        
        # 5. Постобработка: определяем suggested_agents и rag_queries
        result = self._enrich_classification(result, query, context)
        
        # 6. Сохраняем в кэш
        if self.cache:
            cache_key = make_classification_cache_key(normalized_query, context)
            self.cache.set(
                "classification",
                cache_key,
                result.dict(),
                ttl=3600  # 1 час
            )
        
        return result
    
    def _rule_based_classify(
        self,
        query: str,
        query_lower: str,
        context: Optional[Dict[str, Any]]
    ) -> Optional[EnhancedClassificationResult]:
        """Rule-based классификация (fast path для очевидных случаев)"""
        
        # Паттерны для статей кодексов - всегда SIMPLE
        article_patterns = [
            r'статья\s+\d+\s+(гпк|гк|апк|ук|нк|тк|ск|жк|зкпп|кас)',
            r'\d+\s+статья\s+(гпк|гк|апк|ук|нк|тк|ск|жк|зкпп|кас)',
            r'пришли\s+статью|покажи\s+статью|найди\s+статью|текст\s+статьи',
        ]
        
        if any(re.search(pattern, query_lower) for pattern in article_patterns):
            return EnhancedClassificationResult(
                label="simple",
                confidence=0.99,
                rationale="Запрос на получение текста статьи кодекса - простой вопрос для RAG",
                recommended_path="rag",
                rag_queries=[query],
                estimated_complexity="low"
            )
        
        # Паттерны для приветствий - SIMPLE
        if re.search(r'^(привет|здравствуй|hello|hi)', query_lower):
            return EnhancedClassificationResult(
                label="simple",
                confidence=0.95,
                rationale="Приветствие - простой вопрос для RAG",
                recommended_path="rag",
                estimated_complexity="low"
            )
        
        # Паттерны для сложных задач - COMPLEX
        task_verbs = r'(извлеки|извлечь|найди|найти|проанализируй|проанализировать|составь|составить|создай|создать|классифицируй|классифицировать)'
        task_objects = r'(таблиц|таблица|отчет|отчёт|резюме|анализ|противоречи|риск|даты|сущности)'
        
        if re.search(task_verbs, query_lower) and re.search(task_objects, query_lower):
            # Определяем агентов по ключевым словам
            suggested_agents = self._extract_suggested_agents(query_lower)
            
            return EnhancedClassificationResult(
                label="complex",
                confidence=0.90,
                rationale="Запрос содержит команды на выполнение анализа - требует агентной оркестрации",
                recommended_path="agent",
                suggested_agents=suggested_agents,
                estimated_complexity="high" if len(suggested_agents) > 2 else "medium"
            )
        
        return None
    
    def _llm_classify_with_context(
        self,
        query: str,
        normalized_query: str,
        context: Optional[Dict[str, Any]]
    ) -> EnhancedClassificationResult:
        """LLM классификация с учетом контекста state"""
        
        # Получаем список доступных агентов
        from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
        
        agents_list = []
        for agent_name, agent_info in AVAILABLE_ANALYSES.items():
            description = agent_info["description"]
            keywords = ", ".join(agent_info["keywords"][:3])
            agents_list.append(f"- {agent_name}: {description} (ключевые слова: {keywords})")
        
        agents_text = "\n".join(agents_list)
        
        # Формируем контекстную информацию
        context_info = ""
        if context:
            if context.get("workspace_files"):
                file_count = len(context.get("workspace_files", []))
                context_info += f"\nДоступные файлы в workspace: {file_count} файлов\n"
            if context.get("previous_results"):
                prev_results = list(context.get("previous_results", {}).keys())
                context_info += f"\nПредыдущие результаты анализа: {', '.join(prev_results)}\n"
            if context.get("case_id"):
                context_info += f"\nДело: {context['case_id']}\n"
        
        # Enhanced промпт с поддержкой hybrid
        system_content = f"""Ты продвинутый классификатор запросов в системе анализа юридических документов.

В системе доступны следующие агенты:
{agents_text}

{context_info}

Определи тип запроса:

SIMPLE (simple) - простые вопросы для RAG:
- Вопросы с "какие", "что", "где", "когда", "кто", "почему"
- Разговорные фразы
- Запросы на получение информации (статьи кодексов, тексты документов)
- Требует немедленного ответа на основе документов
- Примеры: "Какие ключевые сроки?", "Что в договоре?", "Пришли статью 135 ГПК"

COMPLEX (complex) - сложные задачи для агентной оркестрации:
- Команды на выполнение анализа (извлеки, найди, проанализируй, составь)
- Требует запуска фонового анализа через агентов
- Многошаговые задачи с зависимостями
- Примеры: "Извлеки все даты", "Найди противоречия", "Составь таблицу с судьями"

HYBRID (hybrid) - комбинированные запросы:
- Сначала RAG для контекста, затем агенты для анализа
- Запросы типа "Что говорит договор о сроках и найди все нарушения"
- Требует и информационного ответа, и выполнения анализа
- Примеры: "Покажи статью 123 ГК и проанализируй риски", "Что в договоре и найди противоречия"

Оцени также:
- estimated_complexity: "low" (1 агент), "medium" (2-3 агента), "high" (4+ агента или многошаговая задача)
- suggested_agents: список агентов, которые могут понадобиться (если complex/hybrid), например ["entity_extraction", "risk"]
- rag_queries: список запросов для RAG (если simple/hybrid), например ["статья 123 ГК"]

Возвращай строго JSON с полями:
- label: "simple", "complex" или "hybrid"
- confidence: число от 0.0 до 1.0
- rationale: краткое объяснение (1-2 предложения)
- recommended_path: "rag", "agent" или "hybrid"
- estimated_complexity: "low", "medium" или "high"
- suggested_agents: [] (массив строк, если complex/hybrid)
- rag_queries: [] (массив строк, если simple/hybrid)
- requires_clarification: false (по умолчанию)
- metadata: {{}} (пустой объект, по умолчанию)

Отвечай ТОЛЬКО валидным JSON, без дополнительного текста."""
        
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=f"Запрос: {query}")
        ]
        
        try:
            # Используем structured output
            if hasattr(self.llm, 'with_structured_output'):
                try:
                    structured_llm = self.llm.with_structured_output(EnhancedClassificationResult, include_raw=True)
                    response = structured_llm.invoke(messages)
                    
                    if hasattr(response, 'parsed') and response.parsed:
                        return response.parsed
                    elif isinstance(response, EnhancedClassificationResult):
                        return response
                    else:
                        # Fallback parsing
                        return self._parse_json_response(messages)
                except Exception as e:
                    logger.warning(f"Structured output failed, falling back to JSON parsing: {e}")
                    return self._parse_json_response(messages)
            else:
                return self._parse_json_response(messages)
                
        except Exception as e:
            logger.error(f"Error in LLM classification: {e}", exc_info=True)
            # Fallback
            return EnhancedClassificationResult(
                label="simple",
                confidence=0.5,
                rationale=f"Ошибка классификации: {str(e)}",
                recommended_path="rag",
                rag_queries=[query]
            )
    
    def _enrich_classification(
        self,
        result: EnhancedClassificationResult,
        query: str,
        context: Optional[Dict[str, Any]]
    ) -> EnhancedClassificationResult:
        """Обогащает классификацию: определяет suggested_agents и rag_queries"""
        
        query_lower = query.lower()
        
        # Если не определились агенты, пытаемся извлечь из запроса
        if not result.suggested_agents and result.label in ["complex", "hybrid"]:
            result.suggested_agents = self._extract_suggested_agents(query_lower)
        
        # Если не определились RAG запросы, используем исходный запрос
        if not result.rag_queries and result.label in ["simple", "hybrid"]:
            result.rag_queries = [query]
        
        return result
    
    def _extract_suggested_agents(self, query_lower: str) -> List[str]:
        """Извлекает предполагаемых агентов из запроса по ключевым словам"""
        from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
        
        suggested = []
        agent_keywords = {
            "entity_extraction": ["даты", "дата", "сущности", "имена", "организации", "суммы", "извлеки"],
            "discrepancy": ["противоречи", "несоответств", "расхождени", "конфликт"],
            "risk": ["риск", "риски", "опасност"],
            "timeline": ["хронологи", "последовательность", "временная линия", "timeline"],
            "key_facts": ["ключевые факты", "важные факты", "основные факты"],
            "summary": ["резюме", "краткое содержание", "суммар"],
            "document_classifier": ["классифицир", "тип документа"],
            "privilege_check": ["привилеги", "конфиденциал", "тайна"],
            "relationship": ["связи", "отношения", "граф"],
        }
        
        for agent_name, keywords in agent_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                suggested.append(agent_name)
        
        return suggested
    
    def _build_context_from_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Строит контекст из state для классификации"""
        context = {
            "case_id": state.get("case_id"),
            "workspace_files": state.get("workspace_files", []),
            "previous_results": {},
        }
        
        # Собираем информацию о предыдущих результатах
        result_keys = [
            "timeline_result", "key_facts_result", "discrepancy_result",
            "risk_result", "summary_result", "classification_result",
            "entities_result", "privilege_result", "relationship_result"
        ]
        
        for key in result_keys:
            if state.get(key) is not None:
                agent_name = key.replace("_result", "")
                context["previous_results"][agent_name] = True
        
        # Метаданные
        metadata = state.get("metadata", {})
        context.update(metadata)
        
        return context
    
    def _extract_user_query(self, messages: List) -> Optional[str]:
        """Извлекает последний запрос пользователя из messages"""
        from langchain_core.messages import HumanMessage
        
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                content = msg.content
                if isinstance(content, str):
                    return content
                elif isinstance(content, list):
                    # Если content - список (например, с изображениями)
                    text_parts = [item for item in content if isinstance(item, dict) and item.get("type") == "text"]
                    if text_parts:
                        return text_parts[0].get("text", "")
        
        return None
    
    def _wrap_as_command(
        self,
        result: EnhancedClassificationResult,
        use_command: bool
    ) -> Union[EnhancedClassificationResult, 'Command']:
        """Оборачивает результат в Command для LangGraph conditional edges"""
        if not use_command or not COMMAND_AVAILABLE:
            return result
        
        # Определяем следующий узел на основе recommended_path
        next_node = {
            "rag": "rag_node",
            "agent": "supervisor",  # Или "understand" если LEGORA workflow
            "hybrid": "hybrid_start"  # Специальный узел для hybrid пути
        }.get(result.recommended_path, "rag_node")
        
        # Если требуется уточнение, используем interrupt
        if result.requires_clarification:
            # Возвращаем Command с информацией для interrupt
            return Command(
                goto="clarification_needed",  # Специальный узел для уточнения
                update={
                    "metadata": {
                        "classification": result.dict(),
                        "requires_clarification": True,
                        "classification_timestamp": datetime.now().isoformat()
                    }
                }
            )
        
        # Обычный Command для маршрутизации
        return Command(
            goto=next_node,
            update={
                "metadata": {
                    "classification": result.dict(),
                    "classification_timestamp": datetime.now().isoformat(),
                    "routing_path": result.recommended_path
                }
            }
        )
    
    def _parse_json_response(self, messages) -> EnhancedClassificationResult:
        """Парсинг JSON ответа от LLM (fallback)"""
        response = self.llm.invoke(messages)
        content = response.content if hasattr(response, 'content') else str(response)
        
        import json
        import re
        
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = content
        
        try:
            data = json.loads(json_str)
            # Убеждаемся, что все поля присутствуют
            if "suggested_agents" not in data:
                data["suggested_agents"] = []
            if "rag_queries" not in data:
                data["rag_queries"] = []
            if "estimated_complexity" not in data:
                data["estimated_complexity"] = "medium"
            if "requires_clarification" not in data:
                data["requires_clarification"] = False
            if "metadata" not in data:
                data["metadata"] = {}
            
            return EnhancedClassificationResult(**data)
        except Exception as e:
            logger.warning(f"Failed to parse JSON response: {e}, content: {content[:200]}")
            return EnhancedClassificationResult(
                label="simple",
                confidence=0.5,
                rationale="Не удалось распарсить ответ LLM",
                recommended_path="rag",
                rag_queries=[messages[-1].content if isinstance(messages[-1], HumanMessage) else ""]
            )

