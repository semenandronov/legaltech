"""
ChatReActAgent - настоящий ReAct агент для страницы чата.

Это агент (не узел), потому что:
1. Принимает решения о следующем действии (какой tool вызвать)
2. Может вызывать tools в цикле (итеративное уточнение)
3. Имеет условную логику на основе режима (normal/deep_think/garant/draft)

Tools агента:
- rag_search: Поиск по документам дела
- garant_search: Поиск в правовой базе ГАРАНТ
- deep_analysis: Глубокий анализ с итерациями
- create_document: Создание документа (draft mode)
"""
from typing import List, Optional, Dict, Any, AsyncIterator, Literal
from dataclasses import dataclass
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool
from langchain_core.prompts import ChatPromptTemplate
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver
from app.services.llm_factory import create_llm, create_legal_llm
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from sqlalchemy.orm import Session
import logging
import json

logger = logging.getLogger(__name__)


# ============== Tool Definitions ==============

def create_rag_search_tool(case_id: str, rag_service: RAGService, db: Session) -> BaseTool:
    """Создать tool для поиска по документам дела."""
    
    @tool
    def rag_search(query: str) -> str:
        """
        Поиск информации в документах дела пользователя.
        
        Используй этот инструмент когда:
        - Вопрос про документы пользователя ("мой договор", "в иске")
        - Нужны факты из конкретного дела
        - Пользователь просит проанализировать загруженные документы
        
        Args:
            query: Поисковый запрос
        
        Returns:
            Найденные фрагменты документов с источниками
        """
        try:
            docs = rag_service.retrieve_context(
                case_id=case_id,
                query=query,
                k=5,
                retrieval_strategy="multi_query",
                db=db
            )
            
            if not docs:
                return "Релевантные документы не найдены по запросу."
            
            # Форматируем результаты
            results = []
            for i, doc in enumerate(docs, 1):
                source = doc.metadata.get("source", "Неизвестный источник")
                page = doc.metadata.get("page", "N/A")
                content = doc.page_content[:500] + "..." if len(doc.page_content) > 500 else doc.page_content
                results.append(f"[{i}] {source} (стр. {page}):\n{content}")
            
            return "\n\n".join(results)
            
        except Exception as e:
            logger.error(f"[RAGSearch] Error: {e}", exc_info=True)
            return f"Ошибка поиска: {str(e)}"
    
    return rag_search


def create_garant_search_tool() -> BaseTool:
    """Создать tool для поиска в ГАРАНТ."""
    
    @tool
    def garant_search(query: str, doc_type: str = "all") -> str:
        """
        Поиск в правовой базе ГАРАНТ (законы, кодексы, судебные решения).
        
        Используй этот инструмент когда:
        - Вопрос про статью кодекса (ГК, ГПК, АПК, УК)
        - Вопрос про закон или нормативный акт
        - Нужна судебная практика или решения судов
        - Нужен комментарий к норме права
        
        Args:
            query: Поисковый запрос
            doc_type: Тип документа (all, laws, court_decisions, comments)
        
        Returns:
            Найденные документы из ГАРАНТ
        """
        try:
            from app.services.langchain_agents.utils import get_garant_source
            
            garant_source = get_garant_source()
            if not garant_source or not garant_source.api_key:
                return "ГАРАНТ API недоступен. Попробуйте позже."
            
            # Синхронный вызов для tool
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Если уже в async контексте, используем run_coroutine_threadsafe
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run,
                            garant_source.search(query=query, max_results=5)
                        )
                        results = future.result(timeout=30)
                else:
                    results = loop.run_until_complete(
                        garant_source.search(query=query, max_results=5)
                    )
            except RuntimeError:
                results = asyncio.run(
                    garant_source.search(query=query, max_results=5)
                )
            
            if not results:
                return "Документы не найдены в ГАРАНТ по запросу."
            
            # Форматируем результаты
            formatted = []
            for i, result in enumerate(results[:5], 1):
                title = result.title or "Без названия"
                url = result.url or ""
                content = result.content[:400] + "..." if result.content and len(result.content) > 400 else (result.content or "")
                formatted.append(f"[{i}] {title}\nURL: {url}\n{content}")
            
            return "\n\n".join(formatted)
            
        except Exception as e:
            logger.error(f"[GarantSearch] Error: {e}", exc_info=True)
            return f"Ошибка поиска в ГАРАНТ: {str(e)}"
    
    return garant_search


def create_deep_analysis_tool(case_id: str, rag_service: RAGService, db: Session) -> BaseTool:
    """Создать tool для глубокого анализа."""
    
    @tool
    def deep_analysis(question: str, focus_areas: str = "") -> str:
        """
        Глубокий юридический анализ вопроса с итеративным уточнением.
        
        Используй этот инструмент когда:
        - Включён режим "Глубокое размышление"
        - Требуется комплексный анализ с несколькими аспектами
        - Нужно рассмотреть правовую базу, судебную практику и риски
        
        Args:
            question: Вопрос для глубокого анализа
            focus_areas: Области фокуса (через запятую): "нормы права, судебная практика, риски"
        
        Returns:
            Структурированный глубокий анализ
        """
        try:
            # Получаем контекст из документов
            docs = rag_service.retrieve_context(
                case_id=case_id,
                query=question,
                k=10,
                db=db
            )
            
            context = ""
            if docs:
                context = rag_service.format_sources_for_prompt(docs, max_context_chars=6000)
            
            # Создаём LLM для глубокого анализа (GigaChat Pro если доступен)
            llm = create_legal_llm(use_rate_limiting=False)
            
            # Структурированный промпт для глубокого анализа
            analysis_prompt = f"""Проведи глубокий юридический анализ вопроса.

ВОПРОС:
{question}

ОБЛАСТИ ФОКУСА:
{focus_areas or "нормы права, судебная практика, риски, рекомендации"}

КОНТЕКСТ ИЗ ДОКУМЕНТОВ ДЕЛА:
{context}

СТРУКТУРА ОТВЕТА:

## 📜 Правовая база
[Применимые нормы права, статьи кодексов, законы]

## 🏛️ Судебная практика
[Релевантные решения судов, позиции ВС РФ]

## ⚖️ Анализ позиций
[Аргументы за и против, сильные и слабые стороны]

## ⚠️ Риски
[Возможные проблемы и как их избежать]

## ✅ Рекомендации
[Конкретные шаги и действия]

Дай развёрнутый и структурированный ответ."""

            response = llm.invoke([HumanMessage(content=analysis_prompt)])
            return response.content if hasattr(response, 'content') else str(response)
            
        except Exception as e:
            logger.error(f"[DeepAnalysis] Error: {e}", exc_info=True)
            return f"Ошибка глубокого анализа: {str(e)}"
    
    return deep_analysis


def create_document_tool(case_id: str, user_id: str, db: Session) -> BaseTool:
    """Создать tool для создания документов (draft mode)."""
    
    @tool
    def create_document(description: str, document_type: str = "general") -> str:
        """
        Создание юридического документа на основе описания.
        
        Используй этот инструмент когда:
        - Включён режим "Draft"
        - Пользователь просит создать документ (договор, письмо, иск)
        - Нужно сгенерировать шаблон документа
        
        Args:
            description: Описание документа, который нужно создать
            document_type: Тип документа (contract, letter, claim, motion, general)
        
        Returns:
            ID созданного документа и краткое описание
        """
        try:
            from app.services.document_editor_service import DocumentEditorService
            from app.services.llm_factory import create_legal_llm
            
            # Генерируем название документа
            llm = create_legal_llm(use_rate_limiting=False)
            title_prompt = f"Извлеки краткое название документа (5-7 слов) из описания: {description}. Ответь только названием."
            title_response = llm.invoke([HumanMessage(content=title_prompt)])
            title = title_response.content.strip().replace('"', '').replace("'", "")[:255] if hasattr(title_response, 'content') else "Новый документ"
            
            # Генерируем содержимое документа
            content_prompt = f"""Создай юридический документ на основе описания.

ОПИСАНИЕ:
{description}

ТИП ДОКУМЕНТА:
{document_type}

Создай профессиональный юридический документ в формате HTML.
Используй стандартную структуру для данного типа документа.
Включи все необходимые разделы и поля для заполнения.
"""
            
            content_response = llm.invoke([HumanMessage(content=content_prompt)])
            content = content_response.content if hasattr(content_response, 'content') else ""
            
            # Сохраняем документ
            doc_service = DocumentEditorService(db)
            document = doc_service.create_document(
                case_id=case_id,
                user_id=user_id,
                title=title,
                content=content
            )
            
            return f"✅ Документ создан!\nID: {document.id}\nНазвание: {document.title}\n\nОткройте документ в редакторе для дальнейшего редактирования."
            
        except Exception as e:
            logger.error(f"[CreateDocument] Error: {e}", exc_info=True)
            return f"Ошибка создания документа: {str(e)}"
    
    return create_document


# ============== Agent Definition ==============

@dataclass
class ChatAgentConfig:
    """Конфигурация ChatReActAgent."""
    case_id: str
    user_id: str
    mode: Literal["normal", "deep_think", "garant", "draft"] = "normal"
    recursion_limit: int = 15
    enable_garant: bool = True
    enable_deep_analysis: bool = True
    enable_draft: bool = True


class ChatReActAgent:
    """
    ReAct агент для страницы чата.
    
    Поддерживает режимы:
    - normal: RAG поиск + ответы на вопросы
    - deep_think: Глубокий анализ с GigaChat Pro
    - garant: Поиск в правовой базе ГАРАНТ
    - draft: Создание документов
    """
    
    def __init__(
        self,
        config: ChatAgentConfig,
        rag_service: RAGService,
        db: Session,
        document_processor: DocumentProcessor = None
    ):
        """
        Инициализация агента.
        
        Args:
            config: Конфигурация агента
            rag_service: RAG service для поиска в документах
            db: Database session
            document_processor: Document processor (опционально)
        """
        self.config = config
        self.rag_service = rag_service
        self.db = db
        self.document_processor = document_processor
        
        # Создаём tools на основе режима
        self.tools = self._create_tools()
        
        # Создаём LLM
        self.llm = create_legal_llm(use_rate_limiting=False)
        
        # Создаём ReAct агент через LangGraph prebuilt
        self.agent = self._create_agent()
        
        logger.info(f"[ChatReActAgent] Initialized with mode={config.mode}, tools={[t.name for t in self.tools]}")
    
    def _create_tools(self) -> List[BaseTool]:
        """Создать tools на основе режима."""
        tools = []
        
        # RAG search всегда доступен
        tools.append(create_rag_search_tool(
            self.config.case_id,
            self.rag_service,
            self.db
        ))
        
        # ГАРАНТ search
        if self.config.enable_garant and self.config.mode in ["normal", "garant"]:
            tools.append(create_garant_search_tool())
        
        # Deep analysis
        if self.config.enable_deep_analysis and self.config.mode == "deep_think":
            tools.append(create_deep_analysis_tool(
                self.config.case_id,
                self.rag_service,
                self.db
            ))
        
        # Document creation
        if self.config.enable_draft and self.config.mode == "draft":
            tools.append(create_document_tool(
                self.config.case_id,
                self.config.user_id,
                self.db
            ))
        
        return tools
    
    def _get_system_prompt(self) -> str:
        """Получить системный промпт на основе режима."""
        base_prompt = """Ты - юридический AI-ассистент. Отвечай на вопросы пользователя, используя доступные инструменты.

ПРАВИЛА:
1. Используй инструменты для получения информации
2. Цитируй источники в формате [1], [2], [3]
3. Будь точным и профессиональным
4. Используй Markdown для форматирования
"""
        
        mode_prompts = {
            "normal": """
РЕЖИМ: Обычный
- Используй rag_search для поиска в документах дела
- Используй garant_search для поиска в законодательстве
- Отвечай кратко и по существу
""",
            "deep_think": """
РЕЖИМ: Глубокое размышление
- Используй deep_analysis для комплексного анализа
- Рассмотри все аспекты вопроса
- Дай развёрнутый структурированный ответ
- Включи правовую базу, судебную практику, риски и рекомендации
""",
            "garant": """
РЕЖИМ: ГАРАНТ
- Приоритет garant_search для поиска в законодательстве
- Цитируй статьи, законы, судебные решения
- Указывай ссылки на источники
""",
            "draft": """
РЕЖИМ: Создание документа
- Используй create_document для создания документа
- Уточни детали если нужно
- После создания предложи открыть документ в редакторе
"""
        }
        
        return base_prompt + mode_prompts.get(self.config.mode, mode_prompts["normal"])
    
    def _create_agent(self):
        """Создать ReAct агент."""
        # Используем LangGraph prebuilt create_react_agent
        agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            state_modifier=self._get_system_prompt()
        )
        
        return agent
    
    async def invoke(self, question: str) -> str:
        """
        Получить ответ на вопрос.
        
        Args:
            question: Вопрос пользователя
        
        Returns:
            Ответ агента
        """
        try:
            logger.info(f"[ChatReActAgent] Processing: {question[:100]}...")
            
            result = await self.agent.ainvoke(
                {"messages": [HumanMessage(content=question)]},
                config={"recursion_limit": self.config.recursion_limit}
            )
            
            # Извлекаем последний AIMessage
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    return msg.content
            
            return "Не удалось получить ответ."
            
        except Exception as e:
            logger.error(f"[ChatReActAgent] Error: {e}", exc_info=True)
            raise
    
    async def stream(self, question: str) -> AsyncIterator[str]:
        """
        Получить ответ в виде потока.
        
        Args:
            question: Вопрос пользователя
        
        Yields:
            Части ответа
        """
        try:
            logger.info(f"[ChatReActAgent] Streaming: {question[:100]}...")
            
            last_content = ""
            
            async for chunk in self.agent.astream(
                {"messages": [HumanMessage(content=question)]},
                config={"recursion_limit": self.config.recursion_limit}
            ):
                # Извлекаем контент из chunk
                if isinstance(chunk, dict):
                    messages = []
                    
                    if "messages" in chunk:
                        messages = chunk.get("messages", [])
                    else:
                        for node_data in chunk.values():
                            if isinstance(node_data, dict) and "messages" in node_data:
                                messages = node_data.get("messages", [])
                                break
                    
                    for msg in messages:
                        if isinstance(msg, AIMessage) and msg.content:
                            content = msg.content
                            if content != last_content:
                                # Извлекаем дельту
                                if last_content and content.startswith(last_content):
                                    delta = content[len(last_content):]
                                    if delta:
                                        yield delta
                                else:
                                    yield content
                                last_content = content
            
            if not last_content:
                logger.warning("[ChatReActAgent] No content received, using fallback")
                yield "Не удалось получить ответ. Попробуйте переформулировать вопрос."
                
        except Exception as e:
            logger.error(f"[ChatReActAgent] Stream error: {e}", exc_info=True)
            yield f"Ошибка: {str(e)}"



