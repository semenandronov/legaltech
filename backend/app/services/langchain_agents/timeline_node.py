"""Timeline agent node for LangGraph"""
from typing import Dict, Any, List
from datetime import datetime
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService
from app.services.regex_extractor import RegexExtractor
from app.services.citation_verifier import CitationVerifier
from sqlalchemy.orm import Session
from app.models.analysis import TimelineEvent
from langchain_core.messages import HumanMessage
from langchain_core.documents import Document
import logging
import json

logger = logging.getLogger(__name__)


def _merge_regex_and_llm_results(
    llm_events: List,
    regex_dates: List[Dict[str, Any]]
) -> List:
    """
    Объединяет результаты regex и LLM
    
    Args:
        llm_events: События, извлеченные LLM
        regex_dates: Даты, извлеченные regex
        
    Returns:
        Объединенный список событий с улучшенным confidence scoring
    """
    # Создаем словарь дат из regex для быстрого поиска
    regex_date_map = {}
    for date_info in regex_dates:
        date_key = date_info.get("date")
        if date_key:
            if date_key not in regex_date_map:
                regex_date_map[date_key] = []
            regex_date_map[date_key].append(date_info)
    
    # Обогащаем события LLM информацией из regex
    enriched_events = []
    for event in llm_events:
        # Получаем дату события (может быть в разных форматах)
        event_date = None
        if hasattr(event, 'date'):
            event_date = event.date
        elif isinstance(event, dict):
            event_date = event.get('date')
        
        # Нормализуем дату для поиска
        normalized_date = None
        if event_date:
            try:
                if isinstance(event_date, str):
                    # Пытаемся распарсить дату
                    try:
                        dt = datetime.strptime(event_date, "%Y-%m-%d")
                        normalized_date = dt.strftime("%Y-%m-%d")
                    except:
                        normalized_date = event_date
            except:
                pass
        
        # Если дата совпадает с regex - повышаем confidence
        if normalized_date and normalized_date in regex_date_map:
            matching_dates = regex_date_map[normalized_date]
            # Находим совпадение по документу если возможно
            source_match = False
            if hasattr(event, 'source_document'):
                event_source = event.source_document
                for regex_date in matching_dates:
                    if regex_date.get('source_document') == event_source:
                        source_match = True
                        break
            
            # Повышаем confidence если есть совпадение
            if hasattr(event, 'confidence'):
                # Если совпадение по документу - значительное повышение
                if source_match:
                    event.confidence = min(1.0, event.confidence + 0.15)
                else:
                    event.confidence = min(1.0, event.confidence + 0.1)
            elif isinstance(event, dict):
                if source_match:
                    event['confidence'] = min(1.0, event.get('confidence', 0.8) + 0.15)
                else:
                    event['confidence'] = min(1.0, event.get('confidence', 0.8) + 0.1)
        
        enriched_events.append(event)
    
    return enriched_events


def timeline_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Timeline agent node for extracting timeline events from documents
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with timeline_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Timeline agent: Starting extraction for case {case_id}")
        
        # Initialize FileSystemContext if not already initialized
        from app.services.langchain_agents.file_system_helper import get_file_system_context_from_state
        file_system_context = get_file_system_context_from_state(state)
        if file_system_context:
            from app.services.langchain_agents.file_system_tools import initialize_file_system_tools
            initialize_file_system_tools(file_system_context)
        else:
            # Try to auto-initialize with case_id (will be done when tools are called)
            logger.debug(f"FileSystemContext not in state, will auto-initialize when needed for case {case_id}")
        
        # Initialize tools if needed
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
        
        # Get tools for timeline agent
        tools = get_all_tools()
        
        # Initialize LLM через factory (GigaChat)
        llm = create_llm(temperature=0.1)
        
        # Проверяем, поддерживает ли LLM function calling
        use_tools = hasattr(llm, 'bind_tools')
        
        if use_tools and rag_service:
            # GigaChat с function calling - агент сам вызовет retrieve_documents_tool
            logger.info("Using GigaChat with function calling for timeline agent")
            
            prompt = get_agent_prompt("timeline")
            
            # Создаем агента с tools
            agent = create_legal_agent(llm, tools, system_prompt=prompt)
            
            # Создаем запрос для агента
            user_query = f"Извлеки все даты и события из документов дела {case_id}. Используй retrieve_documents_tool для поиска релевантных документов. Верни результат в формате JSON массива событий с полями: date, event_type, description, source_document, source_page."
            
            initial_message = HumanMessage(content=user_query)
            
            # Вызываем агента (он сам решит, когда вызывать tools)
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            callback = AnalysisCallbackHandler(agent_name="timeline")
            
            result = safe_agent_invoke(
                agent,
                llm,
                {
                    "messages": [initial_message],
                    "case_id": case_id
                },
                config={"recursion_limit": 15, "callbacks": [callback]}
            )
            
            # Извлекаем ответ
            if isinstance(result, dict):
                messages = result.get("messages", [])
                if messages:
                    response_message = messages[-1]
                    response_text = response_message.content if hasattr(response_message, 'content') else str(response_message)
                else:
                    response_text = str(result)
            else:
                response_text = str(result)
        else:
            # GigaChat без tools - используем прямой RAG подход
            if not rag_service:
                raise ValueError("RAG service required for timeline extraction")
            
            logger.info("Using direct RAG approach (GigaChat without tools)")
            
            # Используем helper для прямого вызова LLM с RAG
            from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag, extract_json_from_response
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            
            # Create callback for logging
            callback = AnalysisCallbackHandler(agent_name="timeline")
            
            prompt = get_agent_prompt("timeline")
            user_query = f"Извлеки все даты и события из документов дела {case_id}. Верни результат в формате JSON массива событий с полями: date, event_type, description, source_document, source_page."
            
            response_text = direct_llm_call_with_rag(
                case_id=case_id,
                system_prompt=prompt,
                user_query=user_query,
                rag_service=rag_service,
                db=db,
                k=30,  # Increased from 20 to 30 for better context
                temperature=0.1,
                callbacks=[callback]
            )
        
        # Извлекаем JSON из ответа
        from app.services.langchain_agents.llm_helper import extract_json_from_response
        
        # Извлекаем JSON из ответа и парсим события
        timeline_data = extract_json_from_response(response_text)
        
        if timeline_data:
            # Парсим события из JSON
            parsed_events = ParserService.parse_timeline_events(
                json.dumps(timeline_data) if isinstance(timeline_data, (list, dict)) else str(timeline_data)
            )
        else:
            # Если не удалось извлечь JSON, пробуем парсить весь текст
            logger.warning(f"Could not extract JSON from timeline response, trying to parse full text")
            parsed_events = ParserService.parse_timeline_events(response_text)
        
        # Объединяем результаты regex и LLM (опционально, если нужно предварительное извлечение дат)
        # Regex дает точные даты, LLM дает контекст событий
        # Примечание: основная работа выполняется LLM, regex может использоваться для предварительного извлечения
        
        # Validate dates
        if parsed_events:
            from app.services.date_validator import validate_date_sequence
            validation_errors = validate_date_sequence(parsed_events)
            if validation_errors:
                logger.warning(f"Date validation errors found: {validation_errors}")
        
        # Deduplicate events
        if parsed_events:
            from app.services.deduplication import deduplicate_timeline_events
            try:
                parsed_events = deduplicate_timeline_events(parsed_events, similarity_threshold=0.85)
                logger.info(f"After deduplication: {len(parsed_events)} events")
            except Exception as e:
                logger.warning(f"Error during deduplication: {e}, continuing with original events")
        
        # Save events to database
        saved_events = []
        if db and parsed_events:
            from datetime import datetime
            
            # Функция для создания записи в таблице timelines (если она существует)
            def ensure_timeline_record():
                try:
                    from sqlalchemy import text
                    # Проверяем, существует ли таблица timelines
                    result = db.execute(text("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables 
                            WHERE table_schema = 'public' AND table_name = 'timelines'
                        )
                    """))
                    timelines_exists = result.scalar()
                    
                    if timelines_exists:
                        # Проверяем, есть ли уже запись с таким ID
                        result = db.execute(text("""
                            SELECT EXISTS (
                                SELECT FROM timelines 
                                WHERE id = :case_id
                            )
                        """), {"case_id": case_id})
                        timeline_exists = result.scalar()
                        
                        if not timeline_exists:
                            # Получаем user_id и full_text из таблицы cases
                            result = db.execute(text("""
                                SELECT user_id, full_text FROM cases WHERE id = :case_id
                            """), {"case_id": case_id})
                            row = result.fetchone()
                            
                            if row is None:
                                logger.warning(f"Case {case_id} not found, cannot create timeline record")
                                return False
                            
                            user_id, source_text = row
                            
                            if user_id is None:
                                logger.warning(f"Case {case_id} has no user_id, cannot create timeline record")
                                return False
                            
                            # Создаем запись в таблице timelines (в той же транзакции)
                            # В таблице timelines есть обязательные поля: id, userId, sourceText и updatedAt
                            current_time = datetime.now()
                            db.execute(text("""
                                INSERT INTO timelines (id, "userId", "sourceText", "updatedAt")
                                VALUES (:case_id, :user_id, :source_text, :updated_at)
                                ON CONFLICT (id) DO NOTHING
                            """), {"case_id": case_id, "user_id": user_id, "source_text": source_text or "", "updated_at": current_time})
                            logger.info(f"Created timeline record for case {case_id} with user_id {user_id} in same transaction")
                            return True
                        else:
                            logger.debug(f"Timeline record already exists for case {case_id}")
                            return True
                    else:
                        logger.debug(f"Table 'timelines' does not exist, skipping timeline record creation")
                        return False
                except Exception as timeline_error:
                    # Если таблицы timelines нет или произошла ошибка, логируем и возвращаем False
                    # НЕ делаем rollback здесь, чтобы не прерывать транзакцию
                    logger.warning(f"Could not create timeline record (table may not exist or error): {timeline_error}")
                    return False
            
            # Создаем запись в timelines перед сохранением событий
            ensure_timeline_record()
            
            for idx, event_model in enumerate(parsed_events):
                try:
                    # Parse date
                    date_str = event_model.date
                    try:
                        event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    except:
                        # Try other date formats or use current date
                        event_date = datetime.now().date()
                    
                    # Create timeline event with reasoning and confidence
                    event = TimelineEvent(
                        case_id=case_id,
                        timelineId=case_id,  # Заполняем timelineId значением case_id, так как в БД поле NOT NULL
                        date=event_date,
                        event_type=event_model.event_type,
                        description=event_model.description,
                        source_document=event_model.source_document,
                        source_page=event_model.source_page,
                        source_line=event_model.source_line,
                        order=idx,  # Заполняем поле order для сортировки событий
                        event_metadata={
                            "parsed_from_agent": True,
                            "reasoning": event_model.reasoning,
                            "confidence": event_model.confidence
                        }
                    )
                    db.add(event)
                    saved_events.append(event)
                except Exception as e:
                    logger.warning(f"Ошибка при сохранении события: {e}, event: {event_model}")
                    continue
            
            if saved_events:
                try:
                    db.commit()
                    logger.info(f"Timeline agent: Successfully saved {len(saved_events)} events for case {case_id}")
                except Exception as commit_error:
                    logger.error(f"Ошибка при коммите событий: {commit_error}")
                    try:
                        db.rollback()
                        
                        # Если ошибка связана с внешним ключом, создаем запись в timelines в НОВОЙ транзакции
                        if "timeline_events_timelineId_fkey" in str(commit_error) or "timelines" in str(commit_error) or "InFailedSqlTransaction" in str(commit_error):
                            logger.info(f"Foreign key or transaction error detected, creating timeline record in new transaction")
                            try:
                                from sqlalchemy import text
                                # Сначала проверяем, существует ли таблица
                                result = db.execute(text("""
                                    SELECT EXISTS (
                                        SELECT FROM information_schema.tables 
                                        WHERE table_schema = 'public' AND table_name = 'timelines'
                                    )
                                """))
                                timelines_exists = result.scalar()
                                
                                if timelines_exists:
                                    # Проверяем, есть ли уже запись
                                    result = db.execute(text("""
                                        SELECT EXISTS (
                                            SELECT FROM timelines 
                                            WHERE id = :case_id
                                        )
                                    """), {"case_id": case_id})
                                    timeline_exists = result.scalar()
                                    
                                    if not timeline_exists:
                                        # Получаем user_id и full_text из таблицы cases
                                        result = db.execute(text("""
                                            SELECT user_id, full_text FROM cases WHERE id = :case_id
                                        """), {"case_id": case_id})
                                        row = result.fetchone()
                                        
                                        if row is None:
                                            logger.warning(f"Case {case_id} not found, cannot create timeline record")
                                        else:
                                            user_id, source_text = row
                                            
                                            if user_id is None:
                                                logger.warning(f"Case {case_id} has no user_id, cannot create timeline record")
                                            else:
                                                # Создаем запись и коммитим отдельно
                                                # В таблице timelines есть обязательные поля: id, userId, sourceText и updatedAt
                                                current_time = datetime.now()
                                                db.execute(text("""
                                                    INSERT INTO timelines (id, "userId", "sourceText", "updatedAt")
                                                    VALUES (:case_id, :user_id, :source_text, :updated_at)
                                                    ON CONFLICT (id) DO NOTHING
                                                """), {"case_id": case_id, "user_id": user_id, "source_text": source_text or "", "updated_at": current_time})
                                                db.commit()  # Коммитим создание записи в timelines
                                                logger.info(f"Created and committed timeline record for case {case_id} with user_id {user_id}")
                                    else:
                                        logger.info(f"Timeline record already exists for case {case_id}")
                                else:
                                    logger.warning(f"Table 'timelines' does not exist")
                            except Exception as timeline_error:
                                logger.error(f"Failed to create timeline record: {timeline_error}")
                                db.rollback()
                        
                        # Теперь создаем НОВЫЕ объекты событий (старые привязаны к старой транзакции)
                        new_saved_events = []
                        for idx, event_model in enumerate(parsed_events):
                            try:
                                # Parse date
                                date_str = event_model.date
                                try:
                                    event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                                except:
                                    event_date = datetime.now().date()
                                
                                # Создаем НОВЫЙ объект события
                                event = TimelineEvent(
                                    case_id=case_id,
                                    timelineId=case_id,
                                    date=event_date,
                                    event_type=event_model.event_type,
                                    description=event_model.description,
                                    source_document=event_model.source_document,
                                    source_page=event_model.source_page,
                                    source_line=event_model.source_line,
                                    order=idx,
                                    event_metadata={
                                        "parsed_from_agent": True,
                                        "reasoning": event_model.reasoning,
                                        "confidence": event_model.confidence
                                    }
                                )
                                db.add(event)
                                new_saved_events.append(event)
                            except Exception as e:
                                logger.warning(f"Ошибка при создании нового события: {e}")
                                continue
                        
                        if new_saved_events:
                            db.commit()
                            saved_events = new_saved_events  # Обновляем список сохраненных событий
                            logger.info(f"Timeline agent: Successfully saved {len(saved_events)} events after retry for case {case_id}")
                        else:
                            logger.warning(f"No events were saved after retry")
                            saved_events = []
                    except Exception as retry_error:
                        logger.error(f"Ошибка при повторном сохранении событий: {retry_error}")
                        try:
                            db.rollback()
                        except:
                            pass
                        saved_events = []  # Очищаем список, если не удалось сохранить
        
        # Create result
        result_data = {
            "events": [
                {
                    "id": event.id if hasattr(event, 'id') else None,
                    "date": event.date.isoformat() if hasattr(event, 'date') and event.date else event_model.date,
                    "event_type": event.event_type if hasattr(event, 'event_type') else event_model.event_type,
                    "description": event.description if hasattr(event, 'description') else event_model.description,
                    "source_document": event.source_document if hasattr(event, 'source_document') else event_model.source_document,
                    "source_page": event.source_page if hasattr(event, 'source_page') else event_model.source_page,
                    "source_line": event.source_line if hasattr(event, 'source_line') else event_model.source_line,
                    "reasoning": (event.event_metadata.get("reasoning", "") if event.event_metadata else "") if hasattr(event, 'event_metadata') else (event_model.reasoning if hasattr(event_model, 'reasoning') else ""),
                    "confidence": (event.event_metadata.get("confidence", 0.0) if event.event_metadata else 0.0) if hasattr(event, 'event_metadata') else (event_model.confidence if hasattr(event_model, 'confidence') else 0.0)
                }
                for event, event_model in zip(saved_events, parsed_events) if saved_events
            ] or [
                {
                    "date": event.date,
                    "event_type": event.event_type,
                    "description": event.description,
                    "source_document": event.source_document,
                    "source_page": event.source_page,
                    "source_line": event.source_line,
                    "reasoning": (event.event_metadata.get("reasoning", "") if event.event_metadata else "") if hasattr(event, 'event_metadata') else "",
                    "confidence": (event.event_metadata.get("confidence", 0.0) if event.event_metadata else 0.0) if hasattr(event, 'event_metadata') else 0.0
                }
                for event in parsed_events
            ],
            "total_events": len(parsed_events)
        }
        
        logger.info(f"Timeline agent: Extracted {len(parsed_events)} events for case {case_id}")
        
        # Save context
        try:
            from app.services.langchain_agents.context_helper import save_agent_context
            save_agent_context(
                case_id=case_id,
                agent_name="timeline",
                result=result_data,
                metadata={"events_count": len(parsed_events)}
            )
        except Exception as ctx_error:
            logger.warning(f"Failed to save timeline context: {ctx_error}")
        
        # Save to file system (DeepAgents pattern)
        try:
            from app.services.langchain_agents.file_system_helper import save_agent_result_to_file
            save_agent_result_to_file(state, "timeline", result_data)
        except Exception as fs_error:
            logger.debug(f"Failed to save timeline result to file: {fs_error}")
        
        # Update state
        new_state = state.copy()
        new_state["timeline_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Timeline agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "timeline",
            "error": str(e)
        })
        new_state["timeline_result"] = None
        return new_state
