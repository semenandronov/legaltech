"""
Sub-graph для извлечения данных из одного файла.

Используется в TabularGraph для параллельной обработки файлов
через Send API (MapReduce паттерн).

# АРХИТЕКТУРА
```
START
  ↓
load_file (загрузка содержимого файла)
  ↓
extract_columns (извлечение значений колонок)
  ↓
validate_results (проверка уверенности)
  ↓
END
```

# ИСПОЛЬЗОВАНИЕ С SEND API
```python
from langgraph.types import Send

def map_extract_node(state):
    return [
        Send("extract_single_file", {"file_id": fid, **shared_state})
        for fid in state["file_ids"]
    ]
```
"""
from typing import TypedDict, Optional, List, Dict, Any, Annotated
from langgraph.graph import StateGraph, END, START
from langchain_core.messages import BaseMessage, AIMessage
from sqlalchemy.orm import Session
import logging
import operator

logger = logging.getLogger(__name__)


# ============== State Definition ==============

class FileExtractionState(TypedDict):
    """
    Состояние sub-graph для извлечения из одного файла.
    
    Это изолированное состояние, не зависящее от основного TabularGraphState.
    """
    # Входные данные
    file_id: str
    case_id: str
    user_id: str
    columns: List[Dict[str, Any]]
    confidence_threshold: float
    
    # Промежуточные результаты
    file_content: Optional[str]
    file_metadata: Optional[Dict[str, Any]]
    
    # Результаты извлечения
    extraction_results: List[Dict[str, Any]]
    clarification_requests: List[Dict[str, Any]]
    
    # Метаданные
    errors: Optional[List[str]]


def create_initial_file_extraction_state(
    file_id: str,
    case_id: str,
    user_id: str,
    columns: List[Dict[str, Any]],
    confidence_threshold: float = 0.8
) -> FileExtractionState:
    """Создать начальное состояние для извлечения из файла."""
    return FileExtractionState(
        file_id=file_id,
        case_id=case_id,
        user_id=user_id,
        columns=columns,
        confidence_threshold=confidence_threshold,
        file_content=None,
        file_metadata=None,
        extraction_results=[],
        clarification_requests=[],
        errors=None
    )


# ============== Node Functions ==============

def load_file_node(state: FileExtractionState, db: Session = None) -> FileExtractionState:
    """
    Узел загрузки содержимого файла.
    """
    file_id = state["file_id"]
    logger.info(f"[FileExtraction] Loading file {file_id}")
    
    new_state = dict(state)
    
    try:
        if db:
            from app.models.case import File
            
            file_record = db.query(File).filter(File.id == file_id).first()
            
            if file_record:
                # Получаем содержимое
                content = ""
                if hasattr(file_record, 'file_content') and file_record.file_content:
                    content = file_record.file_content
                elif hasattr(file_record, 'html_content') and file_record.html_content:
                    # Извлекаем текст из HTML
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(file_record.html_content, 'html.parser')
                    content = soup.get_text(separator='\n', strip=True)
                
                new_state["file_content"] = content[:50000]  # Ограничиваем размер
                new_state["file_metadata"] = {
                    "filename": file_record.filename,
                    "file_type": file_record.file_type,
                    "page_count": getattr(file_record, 'page_count', None)
                }
                
                logger.info(f"[FileExtraction] Loaded {len(content)} chars from {file_record.filename}")
            else:
                new_state["errors"] = ["File not found"]
                logger.warning(f"[FileExtraction] File {file_id} not found")
        else:
            new_state["errors"] = ["No database connection"]
            
    except Exception as e:
        logger.error(f"[FileExtraction] Load error: {e}", exc_info=True)
        new_state["errors"] = [f"Load error: {str(e)}"]
    
    return new_state


def extract_columns_node(state: FileExtractionState) -> FileExtractionState:
    """
    Узел извлечения значений колонок из файла.
    """
    file_id = state["file_id"]
    file_content = state.get("file_content", "")
    columns = state.get("columns", [])
    confidence_threshold = state.get("confidence_threshold", 0.8)
    
    logger.info(f"[FileExtraction] Extracting {len(columns)} columns from file {file_id}")
    
    new_state = dict(state)
    
    if not file_content:
        new_state["errors"] = (new_state.get("errors") or []) + ["No file content"]
        return new_state
    
    try:
        from app.services.llm_factory import create_llm
        import json
        
        llm = create_llm()
        
        extraction_results = []
        clarification_requests = []
        
        for column in columns:
            col_id = column.get("id")
            col_label = column.get("label", col_id)
            col_type = column.get("column_type", "text")
            col_prompt = column.get("prompt", f"Извлеки {col_label}")
            
            # Формируем промпт для извлечения
            extraction_prompt = f"""Извлеки значение из документа.

ДОКУМЕНТ:
{file_content[:10000]}

ЗАДАЧА:
{col_prompt}

ТИП ЗНАЧЕНИЯ: {col_type}

Ответь в формате JSON:
{{
    "value": "извлечённое значение",
    "confidence": 0.0-1.0,
    "source_quote": "цитата из документа",
    "reasoning": "объяснение"
}}

Если значение не найдено, установи confidence=0 и value=null."""

            try:
                response = llm.invoke(extraction_prompt)
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Парсим JSON
                import re
                json_match = re.search(r'\{[\s\S]*\}', response_text)
                if json_match:
                    result = json.loads(json_match.group())
                else:
                    result = {"value": response_text, "confidence": 0.5}
                
                confidence = result.get("confidence", 0.5)
                
                extraction_result = {
                    "column_id": col_id,
                    "file_id": file_id,
                    "value": result.get("value"),
                    "confidence": confidence,
                    "source_quote": result.get("source_quote"),
                    "reasoning": result.get("reasoning")
                }
                
                if confidence >= confidence_threshold:
                    extraction_results.append(extraction_result)
                else:
                    # Нужно уточнение
                    clarification_requests.append({
                        **extraction_result,
                        "clarification_question": f"Подтвердите значение для '{col_label}': {result.get('value')}"
                    })
                    
            except Exception as e:
                logger.warning(f"[FileExtraction] Column {col_id} extraction error: {e}")
                clarification_requests.append({
                    "column_id": col_id,
                    "file_id": file_id,
                    "value": None,
                    "confidence": 0,
                    "clarification_question": f"Не удалось извлечь '{col_label}'. Укажите значение вручную."
                })
        
        new_state["extraction_results"] = extraction_results
        new_state["clarification_requests"] = clarification_requests
        
        logger.info(f"[FileExtraction] Extracted {len(extraction_results)} values, {len(clarification_requests)} need clarification")
        
    except Exception as e:
        logger.error(f"[FileExtraction] Extraction error: {e}", exc_info=True)
        new_state["errors"] = (new_state.get("errors") or []) + [f"Extraction error: {str(e)}"]
    
    return new_state


def validate_results_node(state: FileExtractionState) -> FileExtractionState:
    """
    Узел валидации результатов извлечения.
    """
    file_id = state["file_id"]
    extraction_results = state.get("extraction_results", [])
    clarification_requests = state.get("clarification_requests", [])
    columns = state.get("columns", [])
    
    logger.info(f"[FileExtraction] Validating results for file {file_id}")
    
    new_state = dict(state)
    
    # Проверяем, что все колонки обработаны
    processed_columns = set()
    for result in extraction_results:
        processed_columns.add(result.get("column_id"))
    for request in clarification_requests:
        processed_columns.add(request.get("column_id"))
    
    expected_columns = {col.get("id") for col in columns}
    missing_columns = expected_columns - processed_columns
    
    if missing_columns:
        logger.warning(f"[FileExtraction] Missing columns: {missing_columns}")
        # Добавляем missing columns в clarification_requests
        for col_id in missing_columns:
            col = next((c for c in columns if c.get("id") == col_id), {})
            new_state["clarification_requests"] = new_state.get("clarification_requests", []) + [{
                "column_id": col_id,
                "file_id": file_id,
                "value": None,
                "confidence": 0,
                "clarification_question": f"Укажите значение для '{col.get('label', col_id)}'"
            }]
    
    return new_state


# ============== Graph Builder ==============

def create_file_extraction_subgraph(db: Session = None):
    """
    Создать sub-graph для извлечения из одного файла.
    
    Args:
        db: Database session
    
    Returns:
        Compiled sub-graph
    """
    logger.info("[FileExtraction] Creating file extraction subgraph")
    
    graph = StateGraph(FileExtractionState)
    
    # Wrapper функции
    def load_file_wrapper(state):
        return load_file_node(state, db)
    
    # Добавляем узлы
    graph.add_node("load_file", load_file_wrapper)
    graph.add_node("extract_columns", extract_columns_node)
    graph.add_node("validate_results", validate_results_node)
    
    # Добавляем рёбра
    graph.add_edge(START, "load_file")
    graph.add_edge("load_file", "extract_columns")
    graph.add_edge("extract_columns", "validate_results")
    graph.add_edge("validate_results", END)
    
    # Компилируем без checkpointer (sub-graph не нуждается в нём)
    compiled = graph.compile()
    
    logger.info("[FileExtraction] Subgraph created successfully")
    return compiled

