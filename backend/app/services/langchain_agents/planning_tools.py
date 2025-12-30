"""Planning tools for Planning Agent"""
from typing import Dict, Any, List, Optional
from langchain_core.tools import tool
import json
import logging

logger = logging.getLogger(__name__)

# Global instances for document analysis tools
_rag_service = None
_document_processor = None


def initialize_document_analysis_tools(rag_service, document_processor):
    """Initialize global instances for document analysis tools"""
    global _rag_service, _document_processor
    _rag_service = rag_service
    _document_processor = document_processor


# Определение доступных анализов и их зависимостей
AVAILABLE_ANALYSES = {
    "timeline": {
        "name": "timeline",
        "description": "Извлечение хронологии событий из документов (даты, события, временная линия)",
        "keywords": ["даты", "события", "хронология", "timeline", "timeline событий", "временная линия"],
        "dependencies": []
    },
    "key_facts": {
        "name": "key_facts",
        "description": "Извлечение ключевых фактов из документов (стороны, суммы, важные детали)",
        "keywords": ["факты", "ключевые факты", "key facts", "основные моменты", "важные детали"],
        "dependencies": []
    },
    "discrepancy": {
        "name": "discrepancy",
        "description": "Поиск противоречий и несоответствий между документами",
        "keywords": ["противоречия", "несоответствия", "discrepancy", "расхождения", "конфликты"],
        "dependencies": []
    },
    "risk": {
        "name": "risk",
        "description": "Анализ рисков на основе найденных противоречий",
        "keywords": ["риски", "risk", "анализ рисков", "оценка рисков", "риск-анализ"],
        "dependencies": ["discrepancy"]  # Требует discrepancy
    },
    "summary": {
        "name": "summary",
        "description": "Генерация резюме дела на основе ключевых фактов",
        "keywords": ["резюме", "summary", "краткое содержание", "сводка", "краткое резюме"],
        "dependencies": ["key_facts"]  # Требует key_facts
    }
}


@tool
def get_available_analyses_tool() -> str:
    """
    Возвращает список доступных типов анализов с описаниями и ключевыми словами.
    
    Используй этот инструмент для понимания, какие анализы доступны и что они делают.
    
    Returns:
        JSON строка с информацией о доступных анализах
    """
    try:
        analyses_info = {}
        for analysis_type, info in AVAILABLE_ANALYSES.items():
            analyses_info[analysis_type] = {
                "description": info["description"],
                "keywords": info["keywords"],
                "dependencies": info["dependencies"]
            }
        
        result = json.dumps(analyses_info, ensure_ascii=False, indent=2)
        logger.debug("get_available_analyses_tool: Returning available analyses")
        return result
    except Exception as e:
        logger.error(f"Error in get_available_analyses_tool: {e}")
        return json.dumps({"error": str(e)})


@tool
def check_analysis_dependencies_tool(analysis_type: str) -> str:
    """
    Проверяет зависимости для указанного типа анализа.
    
    Некоторые анализы требуют выполнения других анализов первыми.
    Например, risk требует discrepancy, summary требует key_facts.
    
    Args:
        analysis_type: Тип анализа для проверки (timeline, key_facts, discrepancy, risk, summary)
    
    Returns:
        JSON строка с информацией о зависимостях
    """
    try:
        analysis_info = AVAILABLE_ANALYSES.get(analysis_type)
        if not analysis_info:
            return json.dumps({
                "analysis_type": analysis_type,
                "error": f"Unknown analysis type: {analysis_type}",
                "available_types": list(AVAILABLE_ANALYSES.keys())
            })
        
        dependencies = analysis_info["dependencies"]
        
        result = {
            "analysis_type": analysis_type,
            "dependencies": dependencies,
            "requires_dependencies": len(dependencies) > 0,
            "message": f"Analysis '{analysis_type}' requires: {', '.join(dependencies) if dependencies else 'none'}"
        }
        
        logger.debug(f"check_analysis_dependencies_tool: {analysis_type} -> {dependencies}")
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in check_analysis_dependencies_tool: {e}")
        return json.dumps({"error": str(e)})


@tool
def validate_analysis_plan_tool(analysis_types: str) -> str:
    """
    Валидирует план анализа и добавляет недостающие зависимости.
    
    Этот инструмент проверяет, что все необходимые зависимости включены в план.
    Если план включает анализ с зависимостями, они будут автоматически добавлены.
    
    Args:
        analysis_types: JSON строка или список типов анализов для валидации
    
    Returns:
        JSON строка с валидированным планом, включающим все зависимости
    """
    try:
        # Парсим входные данные
        if isinstance(analysis_types, str):
            try:
                types_list = json.loads(analysis_types)
            except json.JSONDecodeError:
                # Если не JSON, пытаемся разобрать как список строк через запятую
                types_list = [t.strip() for t in analysis_types.split(",")]
        else:
            types_list = analysis_types
        
        if not isinstance(types_list, list):
            return json.dumps({"error": "analysis_types must be a list"})
        
        # Валидируем и добавляем зависимости
        validated_types = []
        seen = set()
        
        def add_with_dependencies(analysis_type: str):
            """Рекурсивно добавляет анализ с его зависимостями"""
            if analysis_type in seen:
                return
            
            analysis_info = AVAILABLE_ANALYSES.get(analysis_type)
            if not analysis_info:
                logger.warning(f"Unknown analysis type: {analysis_type}")
                return
            
            # Сначала добавляем зависимости
            for dep in analysis_info["dependencies"]:
                add_with_dependencies(dep)
            
            # Затем добавляем сам анализ
            validated_types.append(analysis_type)
            seen.add(analysis_type)
        
        # Добавляем все анализы с зависимостями
        for analysis_type in types_list:
            if isinstance(analysis_type, str):
                add_with_dependencies(analysis_type)
        
        result = {
            "original_types": types_list,
            "validated_types": validated_types,
            "added_dependencies": list(set(validated_types) - set(types_list)),
            "message": f"Validated plan: {validated_types}"
        }
        
        logger.debug(f"validate_analysis_plan_tool: {types_list} -> {validated_types}")
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in validate_analysis_plan_tool: {e}")
        return json.dumps({"error": str(e)})


@tool
def analyze_document_structure_tool(case_id: str) -> str:
    """
    Анализирует структуру документов в деле для понимания контекста.
    
    Этот инструмент помогает понять:
    - Какие типы документов есть в деле
    - Общий объем информации
    - Ключевые темы и категории документов
    
    Используй этот инструмент ПЕРЕД планированием, чтобы лучше понять контекст дела.
    
    Args:
        case_id: Идентификатор дела
    
    Returns:
        JSON строка с информацией о структуре документов
    """
    global _rag_service, _document_processor
    
    try:
        from app.utils.database import SessionLocal
        db = SessionLocal()
        
        try:
            # Получаем список файлов
            from app.models.case import File as FileModel
            files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
            
            if not files:
                return json.dumps({
                    "case_id": case_id,
                    "file_count": 0,
                    "message": "No documents found in case"
                })
            
            # Анализируем типы файлов
            file_types = {}
            total_size = 0
            for file in files:
                file_type = file.file_type or "unknown"
                file_types[file_type] = file_types.get(file_type, 0) + 1
                total_size += file.file_size or 0
            
            # Получаем образцы документов для понимания содержания
            sample_docs = []
            for file in files[:5]:  # Первые 5 файлов
                try:
                    # Если RAG service доступен, получаем релевантные chunks
                    if _rag_service:
                        chunks = _rag_service.retrieve_context(
                            case_id=case_id,
                            query=f"содержание документа {file.filename}",
                            k=3,
                            db=db
                        )
                        if chunks:
                            sample_docs.append({
                                "filename": file.filename,
                                "type": file.file_type,
                                "preview": chunks[0].get("content", "")[:200] if chunks else ""
                            })
                    else:
                        # Fallback: только метаданные файла
                        sample_docs.append({
                            "filename": file.filename,
                            "type": file.file_type,
                            "preview": "RAG service not available for content preview"
                        })
                except Exception as e:
                    logger.debug(f"Error analyzing file {file.filename}: {e}")
                    # Добавляем файл без preview
                    sample_docs.append({
                        "filename": file.filename,
                        "type": file.file_type,
                        "preview": "Error retrieving content"
                    })
            
            result = {
                "case_id": case_id,
                "file_count": len(files),
                "file_types": file_types,
                "total_size_bytes": total_size,
                "sample_documents": sample_docs,
                "message": f"Found {len(files)} documents in case"
            }
            
            logger.info(f"analyze_document_structure_tool: Analyzed {len(files)} documents for case {case_id}")
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error in analyze_document_structure_tool: {e}")
        return json.dumps({"error": str(e)})


@tool
def classify_case_type_tool(case_id: str) -> str:
    """
    Классифицирует тип дела на основе документов.
    
    Определяет тип юридического дела (договорное право, судебное разбирательство, 
    корпоративное право, и т.д.) для лучшего планирования анализа.
    
    Args:
        case_id: Идентификатор дела
    
    Returns:
        JSON строка с классификацией типа дела
    """
    global _rag_service
    
    try:
        from app.utils.database import SessionLocal
        db = SessionLocal()
        
        try:
            # Если RAG service доступен, используем его для классификации
            if _rag_service:
                # Получаем общий контекст дела
                context_docs = _rag_service.retrieve_context(
                    case_id=case_id,
                    query="тип дела суть спора предмет договора",
                    k=10,
                    db=db
                )
                
                if not context_docs:
                    return json.dumps({
                        "case_id": case_id,
                        "case_type": "unknown",
                        "confidence": 0.0,
                        "message": "Insufficient documents for classification"
                    })
                
                # Анализируем ключевые слова для классификации
                content_text = " ".join([doc.get("content", "") for doc in context_docs[:5]])
                content_lower = content_text.lower()
            else:
                # Fallback: классификация на основе имен файлов
                from app.models.case import File as FileModel
                files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
                
                if not files:
                    return json.dumps({
                        "case_id": case_id,
                        "case_type": "unknown",
                        "confidence": 0.0,
                        "message": "No documents found in case"
                    })
                
                # Анализируем имена файлов для классификации
                filenames_text = " ".join([f.filename or "" for f in files[:10]])
                content_lower = filenames_text.lower()
            
            # Определяем тип дела по ключевым словам
            case_types = {
                "contract_dispute": ["договор", "контракт", "соглашение", "обязательство", "исполнение"],
                "litigation": ["иск", "суд", "судья", "заседание", "решение суда", "истец", "ответчик"],
                "corporate": ["акции", "доля", "учредитель", "устав", "общее собрание"],
                "labor": ["трудовой договор", "работник", "работодатель", "зарплата", "увольнение"],
                "tax": ["налог", "налоговая", "НДС", "прибыль", "декларация"]
            }
            
            detected_types = []
            for case_type, keywords in case_types.items():
                matches = sum(1 for keyword in keywords if keyword in content_lower)
                if matches >= 2:
                    detected_types.append({
                        "type": case_type,
                        "confidence": min(matches / len(keywords), 1.0),
                        "matches": matches
                    })
            
            # Сортируем по уверенности
            detected_types.sort(key=lambda x: x["confidence"], reverse=True)
            
            primary_type = detected_types[0]["type"] if detected_types else "general"
            confidence = detected_types[0]["confidence"] if detected_types else 0.5
            
            result = {
                "case_id": case_id,
                "case_type": primary_type,
                "confidence": confidence,
                "alternative_types": [dt["type"] for dt in detected_types[1:3]],
                "indicators": [doc.get("content", "")[:100] for doc in context_docs[:3]],
                "message": f"Classified as {primary_type} with {confidence:.0%} confidence"
            }
            
            logger.info(f"classify_case_type_tool: Classified case {case_id} as {primary_type}")
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error in classify_case_type_tool: {e}")
        return json.dumps({"error": str(e)})


def get_planning_tools() -> List:
    """Get all planning tools"""
    base_tools = [
        get_available_analyses_tool,
        check_analysis_dependencies_tool,
        validate_analysis_plan_tool,
    ]
    
    # Add document analysis tools if initialized
    if _rag_service and _document_processor:
        base_tools.extend([
            analyze_document_structure_tool,
            classify_case_type_tool,
        ])
    
    return base_tools
