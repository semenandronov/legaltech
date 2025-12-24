"""Timeline agent node for LangGraph"""
from typing import Dict, Any
from app.services.yandex_llm import ChatYandexGPT
from app.services.langchain_agents.agent_factory import create_legal_agent
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService
from sqlalchemy.orm import Session
from app.models.analysis import TimelineEvent
import logging
import json

logger = logging.getLogger(__name__)


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
        
        # Initialize tools if needed
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
        
        # Get tools for timeline agent
        tools = get_all_tools()
        
        # Initialize LLM with temperature=0 for deterministic extraction
        # Только YandexGPT, без fallback
        if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN) or not config.YANDEX_FOLDER_ID:
            raise ValueError("YANDEX_API_KEY/YANDEX_IAM_TOKEN и YANDEX_FOLDER_ID должны быть настроены")
        
        # YandexGPT не поддерживает инструменты, используем прямой RAG подход
        if not rag_service:
            raise ValueError("RAG service required for timeline extraction")
        
        # Используем helper для прямого вызова LLM с RAG
        from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag, extract_json_from_response
        
        prompt = get_agent_prompt("timeline")
        user_query = f"Извлеки все даты и события из документов дела {case_id}. Верни результат в формате JSON массива событий с полями: date, event_type, description, source_document, source_page."
        
        response_text = direct_llm_call_with_rag(
            case_id=case_id,
            system_prompt=prompt,
            user_query=user_query,
            rag_service=rag_service,
            db=db,
            k=20,
            temperature=0.1
        )
        
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
                            # Создаем запись в таблице timelines (в той же транзакции)
                            # В таблице timelines есть только колонка id (без created_at)
                            db.execute(text("""
                                INSERT INTO timelines (id)
                                VALUES (:case_id)
                                ON CONFLICT (id) DO NOTHING
                            """), {"case_id": case_id})
                            logger.info(f"Created timeline record for case {case_id} in same transaction")
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
                                        # Создаем запись и коммитим отдельно
                                        # В таблице timelines есть только колонка id (без created_at)
                                        db.execute(text("""
                                            INSERT INTO timelines (id)
                                            VALUES (:case_id)
                                            ON CONFLICT (id) DO NOTHING
                                        """), {"case_id": case_id})
                                        db.commit()  # Коммитим создание записи в timelines
                                        logger.info(f"Created and committed timeline record for case {case_id}")
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
