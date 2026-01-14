"""LangGraph graph for document template workflow"""
from langgraph.graph import StateGraph, END, START
from app.services.langchain_agents.template_state import TemplateState
from app.services.document_template_service import DocumentTemplateService
from app.services.document_editor_service import DocumentEditorService
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


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
    graph.add_node("search_cache", make_search_cache_node())
    graph.add_node("search_garant", make_search_garant_node())
    graph.add_node("save_template", make_save_template_node())
    graph.add_node("adapt_template", make_adapt_template_node())
    graph.add_node("create_document", make_create_document_node())
    
    # Определяем связи
    graph.add_edge(START, "search_cache")
    
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
            "not_found": END  # Если не найден в Гаранте, завершаем с ошибкой
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


def check_garant_result(state: TemplateState) -> str:
    """Проверка: найден ли шаблон в Гаранте"""
    if state.get("garant_template"):
        return "found"
    # Если не найден, добавляем ошибку и завершаем
    if "Шаблон не найден в Гаранте" not in state.get("errors", []):
        state["errors"].append("Шаблон не найден в Гаранте")
    return "not_found"


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
    """Узел: поиск шаблона в Гаранте"""
    # #region agent log
    import json
    with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"template_graph.py:104","message":"search_garant_node called","data":{"user_query":state.get("user_query")},"timestamp":int(__import__('time').time()*1000)}) + '\n')
    # #endregion
    
    template_service = DocumentTemplateService(db)
    
    # Передаем запрос пользователя как есть - поиск теперь работает по смыслу
    # Гарант сам найдет релевантные документы по смыслу запроса
    user_query = state["user_query"]
    
    logger.info(f"Searching in Garant with natural language query: '{user_query}'")
    
    garant_result = await template_service.search_in_garant(
        query=user_query
    )
    
    # #region agent log
    with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"template_graph.py:112","message":"search_garant_node result","data":{"garant_result_found":garant_result is not None,"garant_result_title":garant_result.get("title") if garant_result else None},"timestamp":int(__import__('time').time()*1000)}) + '\n')
    # #endregion
    
    if garant_result:
        state["garant_template"] = garant_result
        state["template_source"] = "garant"
        logger.info(f"Found template in Garant: {garant_result.get('title')}")
    else:
        state["errors"].append("Шаблон не найден в Гаранте")
        logger.warning("Template not found in Garant")
    
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
    import json
    with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"template_graph.py:121","message":"adapt_template_node called","data":{"has_cached_template":state.get("cached_template") is not None,"has_garant_template":state.get("garant_template") is not None},"timestamp":int(__import__('time').time()*1000)}) + '\n')
    # #endregion
    
    # Определяем какой шаблон использовать
    template_data = state.get("cached_template") or state.get("garant_template")
    
    if not template_data:
        # #region agent log
        with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"template_graph.py:128","message":"No template data found","data":{"cached_template":state.get("cached_template"),"garant_template":state.get("garant_template")},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        # #endregion
        state["errors"].append("Нет шаблона для адаптации")
        return state
    
    # Если адаптация не нужна, используем шаблон как есть
    if not state.get("should_adapt", False):
        state["final_template"] = template_data
        state["adapted_content"] = template_data["content"]
        logger.info("Using template as-is (no adaptation)")
        return state
    
    # Здесь можно использовать LLM для адаптации шаблона
    # Пока просто используем шаблон как есть
    # TODO: Добавить адаптацию через LLM
    try:
        from app.services.llm_factory import create_legal_llm
        from langchain_core.messages import SystemMessage, HumanMessage
        
        llm = create_legal_llm(temperature=0.3)
        
        system_prompt = """Ты - опытный юрист, специализирующийся на адаптации юридических документов.
Адаптируй предоставленный шаблон документа под запрос пользователя.
Сохрани структуру и юридическую корректность, но адаптируй содержание под конкретный запрос.
Верни адаптированный документ в формате HTML."""
        
        user_prompt = f"""Запрос пользователя: {state['user_query']}

Шаблон документа (HTML):
{template_data['content'][:5000]}

Адаптируй этот шаблон под запрос пользователя. Верни полный адаптированный HTML документ."""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        
        response = llm.invoke(messages)
        adapted_content = response.content if hasattr(response, 'content') else str(response)
        
        state["final_template"] = template_data
        state["adapted_content"] = adapted_content
        logger.info("Template adapted successfully")
    except Exception as e:
        logger.error(f"Error adapting template: {e}", exc_info=True)
        # Fallback: используем шаблон как есть
        state["final_template"] = template_data
        state["adapted_content"] = template_data["content"]
        state["errors"].append(f"Ошибка адаптации, использован оригинальный шаблон: {str(e)}")
    
    return state


async def create_document_node(state: TemplateState, db: Session) -> TemplateState:
    """Узел: создание или обновление документа из адаптированного шаблона"""
    # #region agent log
    import json
    with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
        f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"template_graph.py:179","message":"create_document_node called","data":{"has_adapted_content":state.get("adapted_content") is not None,"adapted_content_length":len(state.get("adapted_content","")) if state.get("adapted_content") else 0},"timestamp":int(__import__('time').time()*1000)}) + '\n')
    # #endregion
    
    if not state.get("adapted_content"):
        # #region agent log
        with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"F","location":"template_graph.py:184","message":"No adapted_content","data":{"state_keys":list(state.keys()),"adapted_content":state.get("adapted_content"),"final_template":state.get("final_template")},"timestamp":int(__import__('time').time()*1000)}) + '\n')
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
                    "original_query": state["user_query"]
                }
            )
            state["document_id"] = document.id
            logger.info(f"Created document: {document.id}")
    except Exception as e:
        logger.error(f"Error creating/updating document: {e}", exc_info=True)
        state["errors"].append(f"Ошибка при создании/обновлении документа: {str(e)}")
    
    return state

