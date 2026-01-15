"""LangGraph graph for document template workflow"""
from langgraph.graph import StateGraph, END, START
from app.services.langchain_agents.template_state import TemplateState
from app.services.document_template_service import DocumentTemplateService
from app.services.document_editor_service import DocumentEditorService
from app.models.case import File as FileModel
from sqlalchemy.orm import Session
import logging
import os
import json

logger = logging.getLogger(__name__)


def _safe_debug_log(data: dict) -> None:
    """Безопасное логирование в debug.log с обработкой ошибок"""
    try:
        # Пытаемся найти путь к debug.log относительно корня проекта
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        log_path = os.path.join(base_dir, '.cursor', 'debug.log')
        
        # Создаем директорию если не существует
        log_dir = os.path.dirname(log_path)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        # Записываем лог
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(data) + '\n')
    except Exception:
        # Игнорируем ошибки логирования - это не критично
        pass


def create_template_graph(db: Session) -> StateGraph:
    """
    Создать LangGraph для работы с шаблонами документов
    
    Граф выполняет:
    1. Поиск в кэше
    2. Если не найдено - поиск в Гаранте
    3. Сохранение найденного шаблона
    4. Адаптация шаблона под запрос
    5. Создание документа
    """
    graph = StateGraph(TemplateState)
    
    # Создаем узлы с замыканием для передачи db
    def make_load_template_file_node():
        async def node(state: TemplateState) -> TemplateState:
            return await load_template_file_node(state, db)
        return node
    
    def make_get_case_context_node():
        async def node(state: TemplateState) -> TemplateState:
            return await get_case_context_node(state, db)
        return node
    
    def make_search_cache_node():
        async def node(state: TemplateState) -> TemplateState:
            return await search_cache_node(state, db)
        return node
    
    def make_search_garant_node():
        async def node(state: TemplateState) -> TemplateState:
            return await search_garant_node(state, db)
        return node
    
    def make_save_template_node():
        async def node(state: TemplateState) -> TemplateState:
            return await save_template_node(state, db)
        return node
    
    def make_adapt_template_node():
        async def node(state: TemplateState) -> TemplateState:
            return await adapt_template_node(state, db)
        return node
    
    def make_create_document_node():
        async def node(state: TemplateState) -> TemplateState:
            return await create_document_node(state, db)
        return node
    
    # Добавляем узлы
    graph.add_node("load_template_file", make_load_template_file_node())
    graph.add_node("get_case_context", make_get_case_context_node())
    graph.add_node("search_cache", make_search_cache_node())
    graph.add_node("search_garant", make_search_garant_node())
    graph.add_node("save_template", make_save_template_node())
    graph.add_node("adapt_template", make_adapt_template_node())
    graph.add_node("create_document", make_create_document_node())
    
    # Новый flow:
    # START -> load_template_file -> get_case_context -> check_has_template
    #   -> has_template: adapt_template -> create_document -> END
    #   -> no_template: search_cache -> ...
    
    graph.add_edge(START, "load_template_file")
    graph.add_edge("load_template_file", "get_case_context")
    
    graph.add_conditional_edges(
        "get_case_context",
        check_has_template_file,
        {
            "has_template": "adapt_template",
            "no_template": "search_cache"
        }
    )
    
    graph.add_conditional_edges(
        "search_cache",
        check_template_found,
        {
            "found": "adapt_template",  # Если найден в кэше - сразу адаптируем
            "not_found": "search_garant"  # Если нет - ищем в Гаранте
        }
    )
    
    graph.add_conditional_edges(
        "search_garant",
        check_garant_result,
        {
            "found": "save_template",
            "not_found": "adapt_template"  # Если не найден в Гаранте, все равно пытаемся адаптировать (LLM создаст с нуля)
        }
    )
    graph.add_edge("save_template", "adapt_template")
    graph.add_edge("adapt_template", "create_document")
    graph.add_edge("create_document", END)
    
    return graph.compile()


def check_template_found(state: TemplateState) -> str:
    """Проверка: найден ли шаблон в кэше"""
    if state.get("cached_template"):
        return "found"
    return "not_found"


def check_has_template_file(state: TemplateState) -> str:
    """Проверка: есть ли файл-шаблон от пользователя"""
    if state.get("template_file_content"):
        return "has_template"
    return "no_template"


def check_garant_result(state: TemplateState) -> str:
    """Проверка: найден ли шаблон в Гаранте"""
    if state.get("garant_template"):
        return "found"
    # Если не найден, не добавляем ошибку - LLM создаст документ с нуля
    return "not_found"


async def load_template_file_node(state: TemplateState, db: Session) -> TemplateState:
    """Узел: загрузка и конвертация файла-шаблона пользователя
    
    Поддерживает два варианта:
    1. Локальный файл: template_file_content уже заполнен (из временной загрузки)
    2. Файл из БД: template_file_id указан, нужно загрузить и конвертировать
    """
    # Проверяем, есть ли уже готовый HTML контент (локальный файл)
    template_file_content = state.get("template_file_content")
    if template_file_content:
        logger.info("Template file content already provided (local file), using it directly")
        state["template_source"] = "user_file"
        return state
    
    # Если контента нет, пытаемся загрузить из БД по template_file_id
    template_file_id = state.get("template_file_id")
    if not template_file_id:
        logger.info("No template_file_id provided, skipping file load")
        return state
    
    try:
        # Получить файл из БД с проверкой принадлежности к делу
        file = db.query(FileModel).filter(
            FileModel.id == template_file_id,
            FileModel.case_id == state["case_id"]  # Безопасность: проверяем принадлежность к делу
        ).first()
        if not file:
            logger.warning(f"Template file {template_file_id} not found or doesn't belong to case {state['case_id']}")
            state["errors"].append(f"Файл-шаблон не найден или не принадлежит данному делу")
            return state
        
        # Получить content
        file_content = file.file_content
        if not file_content and file.file_path:
            # Загрузить с диска
            from app.config import config
            if os.path.isabs(file.file_path):
                file_full_path = file.file_path
            else:
                file_full_path = os.path.join(config.UPLOAD_DIR, file.file_path)
            
            if os.path.exists(file_full_path):
                with open(file_full_path, 'rb') as f:
                    file_content = f.read()
            else:
                logger.warning(f"Template file path {file_full_path} does not exist")
                state["errors"].append(f"Файл-шаблон не найден по пути: {file_full_path}")
                return state
        
        if not file_content:
            logger.warning(f"Template file {template_file_id} has no content")
            state["errors"].append(f"Файл-шаблон {template_file_id} не содержит данных")
            return state
        
        # Конвертировать в HTML
        from app.services.document_converter_service import DocumentConverterService
        converter = DocumentConverterService()
        html_content = converter.convert_to_html(
            file_content=file_content,
            filename=file.filename,
            file_type=file.file_type
        )
        
        state["template_file_content"] = html_content
        state["template_source"] = "user_file"
        logger.info(f"Successfully loaded and converted template file {template_file_id} ({file.filename})")
        
    except Exception as e:
        logger.error(f"Error loading template file {template_file_id}: {e}", exc_info=True)
        state["errors"].append(f"Ошибка при загрузке файла-шаблона: {str(e)}")
    
    return state


async def get_case_context_node(state: TemplateState, db: Session) -> TemplateState:
    """Узел: получение контекста дела через RAG"""
    try:
        from app.services.rag_service import RAGService
        
        rag = RAGService()
        
        # Извлечь ключевые факты для адаптации шаблона
        context_query = """Извлеки ключевую информацию для составления документа:
        - Стороны (имена, названия организаций)
        - Даты (заключения, сроки)
        - Суммы и реквизиты
        - Предмет спора/договора
        - Ключевые условия"""
        
        documents = rag.retrieve_context(
            case_id=state["case_id"],
            query=context_query,
            k=10,
            retrieval_strategy="multi_query",
            db=db
        )
        
        if documents:
            context = rag.format_sources_for_prompt(documents)
            state["case_context"] = context
            logger.info(f"Retrieved case context: {len(documents)} documents")
        else:
            logger.warning("No documents found for case context")
            state["case_context"] = ""
        
    except Exception as e:
        logger.error(f"Error getting case context: {e}", exc_info=True)
        state["case_context"] = ""
        # Не добавляем ошибку - контекст опционален
    
    return state


async def search_cache_node(state: TemplateState, db: Session) -> TemplateState:
    """Узел: поиск шаблона в локальном кэше"""
    template_service = DocumentTemplateService(db)
    
    cached_template = await template_service.find_similar_template(
        query=state["user_query"],
        user_id=state.get("user_id")
    )
    
    if cached_template:
        state["cached_template"] = cached_template.to_dict()
        state["template_source"] = "cache"
        logger.info(f"Found template in cache: {cached_template.title}")
    else:
        logger.info("Template not found in cache")
    
    return state


async def search_garant_node(state: TemplateState, db: Session) -> TemplateState:
    """Узел: поиск шаблона в Гаранте
    
    ВРЕМЕННО ОТКЛЮЧЕНО: не используем Гарант для составления шаблонов в режиме draft
    Вместо этого создаем документ через AI без шаблона
    """
    # #region agent log
    import time
    _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"template_graph.py:121","message":"search_garant_node called (DISABLED)","data":{"user_query":state.get("user_query")},"timestamp":int(time.time()*1000)})
    # #endregion
    
    # ВРЕМЕННО ОТКЛЮЧЕНО: пропускаем поиск в Гаранте
    logger.info("Garant search temporarily disabled - will create document via AI instead")
    
    # Не добавляем ошибку, просто возвращаем состояние без garant_template
    # Это позволит adapt_template_node создать документ через AI без шаблона
    return state


async def save_template_node(state: TemplateState, db: Session) -> TemplateState:
    """Узел: сохранение шаблона из Гаранта в кэш"""
    if not state.get("garant_template"):
        return state
    
    template_service = DocumentTemplateService(db)
    garant_data = state["garant_template"]
    
    template = await template_service.save_template(
        title=garant_data["title"],
        content=garant_data["content"],
        source="garant",
        source_doc_id=garant_data.get("doc_id"),
        query=state["user_query"],
        user_id=state.get("user_id"),
        garant_metadata=garant_data.get("metadata", {})
    )
    
    state["cached_template"] = template.to_dict()
    logger.info(f"Saved template to cache: {template.title}")
    
    return state


async def adapt_template_node(state: TemplateState, db: Session) -> TemplateState:
    """Узел: адаптация шаблона под запрос пользователя с помощью ИИ"""
    # #region agent log
    import time
    _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"template_graph.py:181","message":"adapt_template_node called","data":{"has_template_file":state.get("template_file_content") is not None,"has_cached_template":state.get("cached_template") is not None,"has_garant_template":state.get("garant_template") is not None},"timestamp":int(time.time()*1000)})
    # #endregion
    
    # Приоритет: файл-шаблон > кэш > garant
    template_html = state.get("template_file_content")
    template_data = None
    
    if template_html:
        # Используем файл-шаблон от пользователя
        template_data = {
            "content": template_html,
            "title": "Шаблон из файла",
            "source": "user_file"
        }
        logger.info("Using template from user file")
    else:
        # Используем шаблон из кэша или Гаранта
        template_data = state.get("cached_template") or state.get("garant_template")
        if template_data:
            template_html = template_data.get("content", "")
    
    if not template_html:
        # #region agent log
        import time
        _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"template_graph.py:193","message":"No template data found, creating from scratch","data":{"template_file_content":state.get("template_file_content"),"cached_template":state.get("cached_template"),"garant_template":state.get("garant_template")},"timestamp":int(time.time()*1000)})
        # #endregion
        # Создаем документ с нуля через LLM
        try:
            from app.services.llm_factory import create_legal_llm
            from langchain_core.messages import SystemMessage, HumanMessage
            
            llm = create_legal_llm(temperature=0.3)
            case_context = state.get("case_context", "")
            
            system_prompt = """Ты - опытный юрист, специализирующийся на создании юридических документов.
Создай документ на основе запроса пользователя и контекста дела.
Верни документ в формате HTML с правильной структурой."""
            
            user_prompt = f"""Запрос пользователя: {state['user_query']}

КОНТЕКСТ ДЕЛА (используй для заполнения):
{case_context[:3000] if case_context else "Контекст дела не предоставлен"}

Создай полный юридический документ в формате HTML."""
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = llm.invoke(messages)
            adapted_content = response.content if hasattr(response, 'content') else str(response)
            
            state["adapted_content"] = adapted_content
            logger.info("Document created from scratch via LLM")
            return state
        except Exception as e:
            logger.error(f"Error creating document from scratch: {e}", exc_info=True)
            state["errors"].append(f"Ошибка при создании документа: {str(e)}")
            return state
    
    # Если адаптация не нужна, используем шаблон как есть
    if not state.get("should_adapt", False):
        state["final_template"] = template_data
        state["adapted_content"] = template_html
        logger.info("Using template as-is (no adaptation)")
        return state
    
    # Адаптация с учетом контекста дела
    try:
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import SystemMessage, HumanMessage
        
        llm = create_legal_llm(temperature=0.3)
        case_context = state.get("case_context", "")
        
        system_prompt = """Ты - опытный юрист, специализирующийся на адаптации юридических документов.
Адаптируй предоставленный шаблон документа под запрос пользователя и контекст дела.
Сохрани структуру и юридическую корректность, но адаптируй содержание под конкретный запрос.
Замени placeholder'ы данными из контекста дела.
Если данных нет - оставь понятные [ЗАПОЛНИТЬ: что именно].
Верни адаптированный документ в формате HTML."""
        
        # Ограничиваем размер шаблона для промпта
        template_preview = template_html[:5000] if len(template_html) > 5000 else template_html
        
        user_prompt = f"""Адаптируй шаблон документа под запрос пользователя и контекст дела.

ЗАПРОС: {state['user_query']}

КОНТЕКСТ ДЕЛА (используй для заполнения):
{case_context[:3000] if case_context else "Контекст дела не предоставлен"}

ШАБЛОН:
{template_preview}

Требования:
1. Сохрани структуру шаблона
2. Замени placeholder'ы данными из контекста дела
3. Если данных нет - оставь понятные [ЗАПОЛНИТЬ: что именно]
4. Верни полный адаптированный HTML документ"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        adapted_content = response.content if hasattr(response, 'content') else str(response)
        
        state["final_template"] = template_data
        state["adapted_content"] = adapted_content
        logger.info("Template adapted successfully with case context")
    except Exception as e:
        logger.error(f"Error adapting template: {e}", exc_info=True)
        # Fallback: используем шаблон как есть
        state["final_template"] = template_data
        state["adapted_content"] = template_html
        state["errors"].append(f"Ошибка адаптации, использован оригинальный шаблон: {str(e)}")
    
    return state


async def create_document_node(state: TemplateState, db: Session) -> TemplateState:
    """Узел: создание или обновление документа из адаптированного шаблона"""
    # #region agent log
    import time
    _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"template_graph.py:249","message":"create_document_node called","data":{"has_adapted_content":state.get("adapted_content") is not None,"adapted_content_length":len(state.get("adapted_content","")) if state.get("adapted_content") else 0},"timestamp":int(time.time()*1000)})
    # #endregion
    
    if not state.get("adapted_content"):
        # #region agent log
        import time
        _safe_debug_log({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"template_graph.py:257","message":"No adapted_content","data":{"state_keys":list(state.keys()),"adapted_content":state.get("adapted_content"),"final_template":state.get("final_template")},"timestamp":int(time.time()*1000)})
        # #endregion
        state["errors"].append("Нет содержимого для создания документа")
        return state
    
    editor_service = DocumentEditorService(db)
    
    # Определяем название документа
    template_title = (state.get("final_template") or {}).get("title", "Новый документ")
    document_title = state.get("document_title") or template_title
    
    try:
        existing_document_id = state.get("document_id")
        
        # Если есть document_id, обновляем существующий документ
        if existing_document_id:
            try:
                # Проверяем, существует ли документ
                document = editor_service.get_document(existing_document_id, state["user_id"])
                if document:
                    # Обновляем существующий документ
                    document = editor_service.update_document(
                        document_id=existing_document_id,
                        user_id=state["user_id"],
                        content=state["adapted_content"],
                        title=document_title,
                        create_version=True
                    )
                    logger.info(f"Updated document: {document.id}")
                    state["document_id"] = document.id
                else:
                    # Документ не найден, создаем новый
                    raise ValueError("Document not found, creating new one")
            except Exception as update_error:
                logger.warning(f"Error updating document, creating new: {update_error}")
                # Создаем новый документ
                document = editor_service.create_document(
                    case_id=state["case_id"],
                    user_id=state["user_id"],
                    title=document_title,
                    content=state["adapted_content"],
                    metadata={
                        "template_id": state.get("cached_template", {}).get("id"),
                        "template_source": state.get("template_source"),
                        "template_file_id": state.get("template_file_id"),
                        "original_query": state["user_query"]
                    }
                )
                state["document_id"] = document.id
                logger.info(f"Created new document: {document.id}")
        else:
            # Создаем новый документ
            document = editor_service.create_document(
                case_id=state["case_id"],
                user_id=state["user_id"],
                title=document_title,
                content=state["adapted_content"],
                metadata={
                    "template_id": state.get("cached_template", {}).get("id"),
                    "template_source": state.get("template_source"),
                    "template_file_id": state.get("template_file_id"),
                    "original_query": state["user_query"]
                }
            )
            state["document_id"] = document.id
            logger.info(f"Created document: {document.id}")
    except Exception as e:
        logger.error(f"Error creating/updating document: {e}", exc_info=True)
        state["errors"].append(f"Ошибка при создании/обновлении документа: {str(e)}")
    
    return state

