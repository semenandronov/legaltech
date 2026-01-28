"""Review Table routes - Harvey-style Review Query functionality"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.iterative_rag_service import IterativeRAGService
from app.services.document_processor import DocumentProcessor
from app.services.llm_factory import create_llm
from langchain_core.messages import HumanMessage, SystemMessage
import logging
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter()

# Lazy initialization for services (to allow app startup without Yandex credentials)
_rag_service = None
_document_processor = None
_iterative_rag = None


def get_rag_service() -> RAGService:
    """Get or initialize RAG service (lazy initialization)"""
    global _rag_service
    if _rag_service is None:
        try:
            _rag_service = RAGService()
        except Exception as e:
            logger.error(f"Failed to initialize RAG service: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"RAG service недоступен: {str(e)}. Убедитесь, что YANDEX_API_KEY или YANDEX_IAM_TOKEN настроены."
            )
    return _rag_service


def get_document_processor() -> DocumentProcessor:
    """Get or initialize document processor (lazy initialization)"""
    global _document_processor
    if _document_processor is None:
        try:
            _document_processor = DocumentProcessor()
        except Exception as e:
            logger.error(f"Failed to initialize document processor: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"Document processor недоступен: {str(e)}. Убедитесь, что YANDEX_API_KEY или YANDEX_IAM_TOKEN настроены."
            )
    return _document_processor


def get_iterative_rag() -> IterativeRAGService:
    """Get or initialize iterative RAG service (lazy initialization)"""
    global _iterative_rag
    if _iterative_rag is None:
        rag_service = get_rag_service()
        _iterative_rag = IterativeRAGService(rag_service)
    return _iterative_rag


class ReviewTableColumn(BaseModel):
    """Column definition for Review Table"""
    label: str = Field(..., description="Column label")
    question: str = Field(..., description="Question to ask for each document")
    column_type: str = Field(default="text", description="Column type (text, date, number, boolean)")


class ReviewTableRequest(BaseModel):
    """Request model for Review Table Query"""
    case_id: str = Field(..., description="Case identifier")
    columns: List[ReviewTableColumn] = Field(..., min_items=1, description="List of columns/questions")
    selected_file_ids: Optional[List[str]] = Field(None, description="Optional: specific files to query (if None, all files)")


class ReviewTableResponse(BaseModel):
    """Response model for Review Table Query"""
    case_id: str
    columns: List[Dict[str, Any]]
    rows: List[Dict[str, Any]]
    total_documents: int
    processed_documents: int
    processing_time: float


async def process_document_column(
    file: File,
    column: ReviewTableColumn,
    case_id: str,
    rag_service: RAGService,
    iterative_rag: IterativeRAGService
) -> Dict[str, Any]:
    """
    Process a single document-column combination
    
    Args:
        file: File model instance
        column: Column definition
        case_id: Case identifier
        rag_service: RAG service
        iterative_rag: Iterative RAG service
        
    Returns:
        Dictionary with file_id, column_label, and cell_value
    """
    try:
        # Use iterative RAG to get document context
        # Query: column question + document name
        query = f"{column.question} Документ: {file.name}"
        
        # Retrieve relevant chunks for this document
        documents = iterative_rag.retrieve_iteratively(
            case_id=case_id,
            query=query,
            max_iterations=2,  # Fewer iterations for speed
            initial_k=3,
            db=None  # Will use default session
        )
        
        # Filter documents to only this file
        file_documents = [
            doc for doc in documents 
            if doc.metadata.get("source_file") == file.name or 
               doc.metadata.get("file_id") == file.id
        ]
        
        # If no documents found for this file, try direct retrieval
        if not file_documents:
            file_documents = documents[:2]  # Use top 2 documents
        
        # Format context
        context = "\n\n".join([
            f"[{i+1}] {doc.page_content[:500]}..."
            for i, doc in enumerate(file_documents)
        ])
        
        # Generate answer using LLM
        llm = create_llm(temperature=0.1)
        
        prompt = f"""Ты эксперт по извлечению информации из юридических документов.

Документ: {file.name}

Контекст из документа:
{context}

Вопрос: {column.question}

ВАЖНО:
- Отвечай ТОЛЬКО на основе информации из этого документа
- Если информация не найдена, верни "Не найдено"
- Будь конкретным и точным
- Для дат используй формат ДД.ММ.ГГГГ
- Для сумм указывай валюту
- Верни только ответ, без пояснений

Ответ:"""
        
        messages = [
            SystemMessage(content="Ты эксперт по извлечению информации из юридических документов. Отвечай кратко и точно."),
            HumanMessage(content=prompt)
        ]
        
        response = llm.invoke(messages)
        answer = response.content.strip() if hasattr(response, 'content') else str(response).strip()
        
        # Если ответ слишком длинный, обрезаем
        if len(answer) > 500:
            answer = answer[:500] + "..."
        
        return {
            "file_id": file.id,
            "file_name": file.name,
            "column_label": column.label,
            "cell_value": answer,
            "column_type": column.column_type,
            "sources": [
                {
                    "file": doc.metadata.get("source_file", file.name),
                    "page": doc.metadata.get("source_page"),
                    "preview": doc.page_content[:200]
                }
                for doc in file_documents
            ]
        }
        
    except Exception as e:
        logger.error(f"Error processing document {file.id} column {column.label}: {e}", exc_info=True)
        return {
            "file_id": file.id,
            "file_name": file.name,
            "column_label": column.label,
            "cell_value": f"Ошибка: {str(e)[:100]}",
            "column_type": column.column_type,
            "error": str(e)
        }


@router.post("/query", response_model=ReviewTableResponse)
async def review_table_query(
    request: ReviewTableRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Review Query - вопросы ко всем документам (Harvey-style)
    
    Пользователь задает вопросы (колонки), и система отвечает на них
    для КАЖДОГО документа отдельно, возвращая результат в табличном формате.
    """
    start_time = datetime.now()
    
    try:
        # Verify case exists and belongs to user
        case = db.query(Case).filter(
            Case.id == request.case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(
                status_code=404,
                detail=f"Case {request.case_id} not found or access denied"
            )
        
        # Get files
        if request.selected_file_ids:
            files = db.query(File).filter(
                File.id.in_(request.selected_file_ids),
                File.case_id == request.case_id
            ).all()
            
            if len(files) != len(request.selected_file_ids):
                raise HTTPException(
                    status_code=400,
                    detail="Some selected files do not belong to this case"
                )
        else:
            # All files in case
            files = db.query(File).filter(File.case_id == request.case_id).all()
        
        if not files:
            raise HTTPException(
                status_code=400,
                detail="No files found for this case"
            )
        
        logger.info(
            f"Review Table Query: case {request.case_id}, "
            f"{len(files)} files, {len(request.columns)} columns"
        )
        
        # Get services (lazy initialization)
        rag_service = get_rag_service()
        iterative_rag = get_iterative_rag()
        
        # Create tasks for parallel processing
        tasks = []
        for file in files:
            for column in request.columns:
                task = process_document_column(
                    file=file,
                    column=column,
                    case_id=request.case_id,
                    rag_service=rag_service,
                    iterative_rag=iterative_rag
                )
                tasks.append(task)
        
        # Execute tasks in parallel
        logger.info(f"Processing {len(tasks)} document-column combinations in parallel")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        processed_count = 0
        error_count = 0
        
        # Group results by file
        rows_dict = {}
        for result in results:
            if isinstance(result, Exception):
                error_count += 1
                logger.error(f"Task failed: {result}")
                continue
            
            file_id = result.get("file_id")
            if file_id not in rows_dict:
                rows_dict[file_id] = {
                    "file_id": file_id,
                    "file_name": result.get("file_name", "unknown"),
                    "cells": {}
                }
            
            column_label = result.get("column_label")
            rows_dict[file_id]["cells"][column_label] = {
                "value": result.get("cell_value", ""),
                "type": result.get("column_type", "text"),
                "sources": result.get("sources", [])
            }
            
            processed_count += 1
        
        # Convert to list format
        rows = list(rows_dict.values())
        
        # Format columns
        columns = [
            {
                "label": col.label,
                "question": col.question,
                "type": col.column_type
            }
            for col in request.columns
        ]
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        logger.info(
            f"Review Table Query completed: {processed_count} cells processed, "
            f"{error_count} errors, {processing_time:.2f}s"
        )
        
        return ReviewTableResponse(
            case_id=request.case_id,
            columns=columns,
            rows=rows,
            total_documents=len(files),
            processed_documents=processed_count // len(request.columns) if request.columns else 0,
            processing_time=processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in Review Table Query: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при выполнении Review Query: {str(e)}"
        )

