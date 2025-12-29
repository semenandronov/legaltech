"""Table Creator Tool for DELIVER phase - creates tables from analysis results"""
from typing import Dict, Any, Optional
from langchain_core.tools import tool
from sqlalchemy.orm import Session
from app.services.tabular_review_service import TabularReviewService
import logging

logger = logging.getLogger(__name__)

# Global reference to db session (will be set by initialize_table_creator)
_db_session: Optional[Session] = None


def initialize_table_creator(db: Session):
    """Initialize table creator with database session"""
    global _db_session
    _db_session = db
    logger.info("Table creator initialized")


@tool
def create_table_tool(
    analysis_type: str,
    case_id: str,
    user_id: str,
    result_data: Optional[Dict[str, Any]] = None
) -> str:
    """
    Создает таблицу из результатов анализа
    
    Используется в DELIVER фазе для автоматического создания таблиц
    из результатов различных анализов (timeline, key_facts, discrepancy, risk).
    
    Args:
        analysis_type: Тип анализа (timeline, key_facts, discrepancy, risk)
        case_id: Идентификатор дела
        user_id: Идентификатор пользователя
        result_data: Данные результатов (опционально, если не указано, берется из БД)
    
    Returns:
        table_id или путь к таблице
    """
    if not _db_session:
        raise ValueError("Table creator not initialized. Call initialize_table_creator() first.")
    
    try:
        service = TabularReviewService(_db_session)
        
        if analysis_type == "timeline":
            # Создать таблицу из timeline результатов
            table = service.create_timeline_table_from_results(
                case_id=case_id,
                user_id=user_id,
                name="Хронология событий"
            )
            logger.info(f"Created timeline table: {table.id}")
            return table.id
        
        elif analysis_type == "key_facts":
            # Создать таблицу из key_facts результатов
            table = service.create_key_facts_table_from_results(
                case_id=case_id,
                user_id=user_id,
                name="Ключевые факты"
            )
            logger.info(f"Created key_facts table: {table.id}")
            return table.id
        
        elif analysis_type == "discrepancy":
            # Создать таблицу из discrepancy результатов
            table = service.create_discrepancies_table_from_results(
                case_id=case_id,
                user_id=user_id,
                name="Противоречия"
            )
            logger.info(f"Created discrepancy table: {table.id}")
            return table.id
        
        elif analysis_type == "risk":
            # Создать таблицу из risk результатов
            table = service.create_risks_table_from_results(
                case_id=case_id,
                user_id=user_id,
                name="Анализ рисков"
            )
            logger.info(f"Created risk table: {table.id}")
            return table.id
        
        else:
            logger.warning(f"Unknown analysis_type for table creation: {analysis_type}")
            return f"Table creation not supported for {analysis_type}"
            
    except Exception as e:
        logger.error(f"Error creating table for {analysis_type}: {e}", exc_info=True)
        return f"Error creating table: {str(e)}"

