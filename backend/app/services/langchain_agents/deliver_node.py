"""DELIVER node for LEGORA workflow - Phase 6: Final processing and formatting"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.tabular_review_service import TabularReviewService
from app.services.report_generator import ReportGenerator
from app.services.langchain_agents.table_creator_tool import initialize_table_creator, create_table_tool
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
        user_id = state.get("metadata", {}).get("user_id") or "system"
        
        # Список типов анализов, для которых можно создать таблицы
        table_supported_types = ["timeline", "key_facts", "discrepancy", "risk"]
        
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
                except Exception as e:
                    logger.warning(f"[DELIVER] Failed to create table for {analysis_type}: {e}")
                    table_results[analysis_type] = {
                        "status": "failed",
                        "error": str(e)
                    }
        
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

