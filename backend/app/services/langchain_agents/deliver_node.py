"""DELIVER node for LEGORA workflow - Phase 6: Final processing and formatting"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.tabular_review_service import TabularReviewService
from app.services.report_generator import ReportGenerator
from app.services.langchain_agents.table_creator_tool import initialize_table_creator, create_table_tool
from app.models.tabular_review import TabularReview, TabularColumn
from io import BytesIO
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def deliver_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    ФАЗА 6: DELIVER - финальная обработка и форматирование результатов
    
    Выполняет:
    1. Сбор всех результатов из state
    2. Создание таблиц через Table Creator
    3. Генерация отчетов через ReportGenerator
    4. Форматирование для вывода пользователю
    
    Args:
        state: Current analysis state с результатами всех агентов
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with delivery_result
    """
    case_id = state.get("case_id")
    
    try:
        logger.info(f"[DELIVER] Starting delivery phase for case {case_id}")
        
        if not db:
            logger.warning("[DELIVER] No database session provided, skipping table and report generation")
            state["delivery_result"] = {
                "status": "partial",
                "error": "No database session",
                "results": _format_results_for_delivery(state)
            }
            return state
        
        # Инициализируем Table Creator
        initialize_table_creator(db)
        
        # Собираем все результаты
        results = _collect_all_results(state)
        
        # 1. Создаем таблицы для каждого типа анализа
        table_results = {}
        # Получаем user_id из metadata или из case
        user_id = state.get("metadata", {}).get("user_id")
        if not user_id:
            # Попробуем получить user_id из case
            try:
                from app.models.case import Case
                case = db.query(Case).filter(Case.id == case_id).first()
                if case:
                    user_id = case.user_id
                else:
                    user_id = "system"
            except Exception as e:
                logger.warning(f"Failed to get user_id from case: {e}")
                user_id = "system"
        
        # Список типов анализов, для которых можно создать таблицы
        table_supported_types = ["timeline", "key_facts", "discrepancy", "risk"]
        
        # Get SSE callback from state metadata if available
        sse_callback = state.get("metadata", {}).get("sse_callback")
        
        for analysis_type in table_supported_types:
            result_key = f"{analysis_type}_result"
            if state.get(result_key):
                try:
                    table_id = create_table_tool.invoke({
                        "analysis_type": analysis_type,
                        "case_id": case_id,
                        "user_id": user_id,
                        "result_data": state.get(result_key)
                    })
                    table_results[analysis_type] = {
                        "table_id": table_id,
                        "status": "created"
                    }
                    logger.info(f"[DELIVER] Created table for {analysis_type}: {table_id}")
                    
                    # Send SSE event if callback is available
                    if sse_callback and callable(sse_callback):
                        try:
                            # Get table preview data
                            tabular_service = TabularReviewService(db)
                            review = db.query(TabularReview).filter(TabularReview.id == table_id).first()
                            if review:
                                columns = db.query(TabularColumn).filter(
                                    TabularColumn.tabular_review_id == table_id
                                ).order_by(TabularColumn.order_index).all()
                                
                                # Get preview data (first few rows)
                                preview_data = {
                                    "id": table_id,
                                    "name": review.name,
                                    "description": review.description,
                                    "columns_count": len(columns),
                                    "rows_count": len(review.selected_file_ids) if review.selected_file_ids else 0,
                                    "preview": {
                                        "columns": [col.column_label for col in columns[:4]],
                                        "rows": []  # Will be populated if needed
                                    }
                                }
                                
                                # Send table_created event
                                event_data = {
                                    "type": "table_created",
                                    "table_id": table_id,
                                    "case_id": case_id,
                                    "analysis_type": analysis_type,
                                    "table_data": preview_data
                                }
                                sse_callback(event_data)
                                logger.info(f"[DELIVER] Sent table_created SSE event for {analysis_type}: {table_id}")
                        except Exception as callback_error:
                            logger.warning(f"[DELIVER] Failed to send SSE event for table {table_id}: {callback_error}")
                except Exception as e:
                    logger.warning(f"[DELIVER] Failed to create table for {analysis_type}: {e}")
                    table_results[analysis_type] = {
                        "status": "failed",
                        "error": str(e)
                    }
        
        # 1.5. Создаем кастомные таблицы из плана (tables_to_create)
        # Проверяем наличие tables_to_create в metadata или в сохраненном плане
        custom_tables_to_create = state.get("metadata", {}).get("tables_to_create")
        if not custom_tables_to_create:
            # Попытка получить из plan_data если он есть в metadata
            plan_data = state.get("metadata", {}).get("plan_data")
            if plan_data and isinstance(plan_data, dict):
                custom_tables_to_create = plan_data.get("tables_to_create")
        
        if custom_tables_to_create and isinstance(custom_tables_to_create, list):
            logger.info(f"[DELIVER] Found {len(custom_tables_to_create)} custom tables to create from plan")
            try:
                from app.routes.review_table import ReviewTableColumn
                
                tabular_service = TabularReviewService(db)
                
                for table_spec in custom_tables_to_create:
                    if not isinstance(table_spec, dict):
                        continue
                    
                    table_name = table_spec.get("table_name", "Данные из документов")
                    columns_spec = table_spec.get("columns", [])
                    
                    if not columns_spec:
                        logger.warning(f"[DELIVER] Table {table_name} has no columns, skipping")
                        continue
                    
                    # Преобразуем columns_spec в ReviewTableColumn
                    review_columns = []
                    for col in columns_spec:
                        if not isinstance(col, dict):
                            continue
                        review_columns.append(ReviewTableColumn(
                            label=col.get("label", ""),
                            question=col.get("question", ""),
                            column_type=col.get("type", "text")
                        ))
                    
                    if not review_columns:
                        logger.warning(f"[DELIVER] Table {table_name} has no valid columns, skipping")
                        continue
                    
                    # Создаем TabularReview
                    try:
                        review = tabular_service.create_tabular_review(
                            case_id=case_id,
                            user_id=user_id,
                            name=table_name,
                            description=f"Автоматически созданная таблица из плана: {table_name}"
                        )
                        
                        # Добавляем колонки
                        for review_col in review_columns:
                            tabular_service.add_column(
                                review_id=review.id,
                                column_label=review_col.label,
                                column_type=review_col.column_type,
                                prompt=review_col.question,
                                user_id=user_id
                            )
                        
                        # Запускаем извлечение данных в фоне (run_extraction - async метод)
                        # Таблица создана с колонками, извлечение будет выполнено отдельно
                        # или может быть запущено через API endpoint
                        logger.info(f"[DELIVER] Table '{table_name}' created with {len(review_columns)} columns, extraction can be run separately")
                        
                        # Сохраняем результат в table_results
                        table_key = f"custom_{table_name.lower().replace(' ', '_')}"
                        table_results[table_key] = {
                            "table_id": review.id,
                            "table_name": table_name,
                            "status": "created",
                            "type": "custom"
                        }
                        
                        logger.info(f"[DELIVER] Created custom table '{table_name}' with id: {review.id}")
                        
                        # Send SSE event if callback is available
                        if sse_callback and callable(sse_callback):
                            try:
                                # Get preview data
                                columns = db.query(TabularColumn).filter(
                                    TabularColumn.tabular_review_id == review.id
                                ).order_by(TabularColumn.order_index).all()
                                
                                preview_data = {
                                    "id": review.id,
                                    "name": review.name,
                                    "description": review.description,
                                    "columns_count": len(columns),
                                    "rows_count": len(review.selected_file_ids) if review.selected_file_ids else 0,
                                    "preview": {
                                        "columns": [col.column_label for col in columns[:4]],
                                        "rows": []
                                    }
                                }
                                
                                # Send table_created event
                                event_data = {
                                    "type": "table_created",
                                    "table_id": review.id,
                                    "case_id": case_id,
                                    "analysis_type": "custom",
                                    "table_name": table_name,
                                    "table_data": preview_data
                                }
                                sse_callback(event_data)
                                logger.info(f"[DELIVER] Sent table_created SSE event for custom table '{table_name}': {review.id}")
                            except Exception as callback_error:
                                logger.warning(f"[DELIVER] Failed to send SSE event for custom table {review.id}: {callback_error}")
                        
                    except Exception as table_error:
                        logger.error(f"[DELIVER] Failed to create custom table '{table_name}': {table_error}", exc_info=True)
                        table_key = f"custom_{table_name.lower().replace(' ', '_')}"
                        table_results[table_key] = {
                            "status": "failed",
                            "error": str(table_error),
                            "type": "custom"
                        }
                        
            except Exception as e:
                logger.error(f"[DELIVER] Error creating custom tables: {e}", exc_info=True)
        
        state["table_results"] = table_results
        
        # 2. Генерируем отчеты
        report_results = {}
        report_generator = ReportGenerator(db)
        
        # Executive Summary
        try:
            summary_text = ""
            if state.get("summary_result"):
                summary_data = state["summary_result"]
                if isinstance(summary_data, dict):
                    summary_text = summary_data.get("summary", "") or summary_data.get("text", "")
                elif isinstance(summary_data, str):
                    summary_text = summary_data
            
            key_facts_data = state.get("key_facts_result", {})
            if isinstance(key_facts_data, dict):
                key_facts = key_facts_data
            else:
                key_facts = {}
            
            risk_analysis_text = ""
            if state.get("risk_result"):
                risk_data = state["risk_result"]
                if isinstance(risk_data, dict):
                    risk_analysis_text = risk_data.get("analysis", "") or risk_data.get("text", "")
                elif isinstance(risk_data, str):
                    risk_analysis_text = risk_data
            
            if summary_text or key_facts:
                executive_summary = report_generator.generate_executive_summary(
                    case_id=case_id,
                    summary=summary_text or "Резюме не доступно",
                    key_facts=key_facts,
                    risk_analysis=risk_analysis_text
                )
                
                # Сохраняем отчет (в реальной системе можно сохранить в файловую систему или S3)
                report_path = _save_report(executive_summary, case_id, "executive_summary")
                report_results["executive_summary"] = {
                    "path": report_path,
                    "format": "word",
                    "status": "created"
                }
                logger.info(f"[DELIVER] Created executive summary report: {report_path}")
        except Exception as e:
            logger.warning(f"[DELIVER] Failed to create executive summary: {e}")
            report_results["executive_summary"] = {
                "status": "failed",
                "error": str(e)
            }
        
        # Detailed Analysis
        try:
            timeline_data = state.get("timeline_result", {})
            if isinstance(timeline_data, dict):
                timeline_list = timeline_data.get("events", []) or timeline_data.get("timeline", [])
            else:
                timeline_list = []
            
            discrepancy_data = state.get("discrepancy_result", {})
            if isinstance(discrepancy_data, dict):
                discrepancies_list = discrepancy_data.get("discrepancies", []) or discrepancy_data.get("items", [])
            else:
                discrepancies_list = []
            
            if timeline_list or discrepancies_list or summary_text:
                detailed_analysis = report_generator.generate_detailed_analysis(
                    case_id=case_id,
                    timeline=timeline_list,
                    discrepancies=discrepancies_list,
                    key_facts=key_facts,
                    summary=summary_text or "",
                    risk_analysis=risk_analysis_text
                )
                
                report_path = _save_report(detailed_analysis, case_id, "detailed_analysis")
                report_results["detailed_analysis"] = {
                    "path": report_path,
                    "format": "word",
                    "status": "created"
                }
                logger.info(f"[DELIVER] Created detailed analysis report: {report_path}")
        except Exception as e:
            logger.warning(f"[DELIVER] Failed to create detailed analysis: {e}")
            report_results["detailed_analysis"] = {
                "status": "failed",
                "error": str(e)
            }
        
        # 3. Форматируем финальный результат
        delivery_result = {
            "status": "completed",
            "case_id": case_id,
            "tables": table_results,
            "reports": report_results,
            "results": _format_results_for_delivery(state),
            "summary": _generate_delivery_summary(state, table_results, report_results),
            "created_at": datetime.utcnow().isoformat()
        }
        
        state["delivery_result"] = delivery_result
        
        logger.debug(
            f"[DELIVER] Table results: {len(table_results)} tables, "
            f"delivery_result keys: {list(delivery_result.keys())}"
        )
        
        logger.info(
            f"[DELIVER] Delivery completed: {len(table_results)} tables, "
            f"{len([r for r in report_results.values() if r.get('status') == 'created'])} reports"
        )
        
        return state
        
    except Exception as e:
        logger.error(f"[DELIVER] Error in delivery phase for case {case_id}: {e}", exc_info=True)
        state["delivery_result"] = {
            "status": "failed",
            "error": str(e),
            "results": _format_results_for_delivery(state)
        }
        return state


def _collect_all_results(state: AnalysisState) -> Dict[str, Any]:
    """Собирает все результаты из state"""
    results = {}
    
    result_keys = [
        "timeline_result", "key_facts_result", "discrepancy_result",
        "risk_result", "summary_result", "classification_result",
        "entities_result", "privilege_result", "relationship_result"
    ]
    
    for key in result_keys:
        if state.get(key):
            analysis_type = key.replace("_result", "")
            results[analysis_type] = state[key]
    
    return results


def _format_results_for_delivery(state: AnalysisState) -> Dict[str, Any]:
    """Форматирует результаты для вывода пользователю"""
    formatted = {}
    
    result_keys = [
        ("timeline_result", "timeline"),
        ("key_facts_result", "key_facts"),
        ("discrepancy_result", "discrepancies"),
        ("risk_result", "risk_analysis"),
        ("summary_result", "summary"),
        ("classification_result", "classification"),
        ("entities_result", "entities"),
        ("privilege_result", "privilege"),
        ("relationship_result", "relationship")
    ]
    
    for result_key, display_name in result_keys:
        if state.get(result_key):
            formatted[display_name] = state[result_key]
    
    return formatted


def _generate_delivery_summary(
    state: AnalysisState,
    table_results: Dict[str, Any],
    report_results: Dict[str, Any]
) -> str:
    """Генерирует текстовое резюме delivery результата"""
    summary_parts = []
    
    # Подсчет успешных таблиц
    successful_tables = [k for k, v in table_results.items() if v.get("status") == "created"]
    if successful_tables:
        summary_parts.append(f"Создано таблиц: {len(successful_tables)} ({', '.join(successful_tables)})")
    
    # Подсчет успешных отчетов
    successful_reports = [k for k, v in report_results.items() if v.get("status") == "created"]
    if successful_reports:
        summary_parts.append(f"Создано отчетов: {len(successful_reports)} ({', '.join(successful_reports)})")
    
    # Информация о результатах
    result_count = len([k for k in [
        "timeline_result", "key_facts_result", "discrepancy_result",
        "risk_result", "summary_result"
    ] if state.get(k)])
    
    if result_count > 0:
        summary_parts.append(f"Обработано анализов: {result_count}")
    
    if not summary_parts:
        return "Delivery завершен, но результаты не найдены"
    
    return ". ".join(summary_parts) + "."


def _save_report(buffer: BytesIO, case_id: str, report_type: str) -> str:
    """
    Сохраняет отчет в файловую систему
    
    В production это должно быть сохранение в S3 или другое хранилище
    """
    # Создаем директорию для отчетов
    reports_dir = os.path.join("reports", case_id)
    os.makedirs(reports_dir, exist_ok=True)
    
    # Генерируем имя файла
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{report_type}_{case_id}_{timestamp}.docx"
    filepath = os.path.join(reports_dir, filename)
    
    # Сохраняем файл
    with open(filepath, "wb") as f:
        f.write(buffer.read())
    
    logger.info(f"Saved report to {filepath}")
    return filepath

