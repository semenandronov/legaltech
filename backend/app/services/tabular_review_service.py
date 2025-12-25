"""Tabular Review service for Legal AI Vault"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.tabular_review import (
    TabularReview, TabularColumn, TabularCell, 
    TabularColumnTemplate, TabularDocumentStatus
)
from app.models.case import Case, File
from app.models.user import User
from app.services.yandex_llm import ChatYandexGPT
from app.config import config
import logging
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


class TabularReviewService:
    """Service for managing tabular reviews"""
    
    def __init__(self, db: Session):
        """Initialize tabular review service"""
        self.db = db
        # Initialize LLM for extraction
        if config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN:
            self.llm = ChatYandexGPT(
                model=config.YANDEX_GPT_MODEL or "yandexgpt-lite",
                temperature=0.1,  # Low temperature for deterministic extraction
            )
        else:
            self.llm = None
            logger.warning("YandexGPT not configured, extraction will not work")
    
    def create_tabular_review(
        self, 
        case_id: str, 
        user_id: str,
        name: str, 
        description: Optional[str] = None
    ) -> TabularReview:
        """Create a new tabular review"""
        # Verify case exists and belongs to user
        case = self.db.query(Case).filter(
            and_(Case.id == case_id, Case.user_id == user_id)
        ).first()
        
        if not case:
            raise ValueError(f"Case {case_id} not found or access denied")
        
        review = TabularReview(
            case_id=case_id,
            user_id=user_id,
            name=name,
            description=description,
            status="draft"
        )
        
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        
        logger.info(f"Created tabular review {review.id} for case {case_id}")
        return review
    
    def add_column(
        self,
        review_id: str,
        column_label: str,
        column_type: str,
        prompt: str,
        user_id: str
    ) -> TabularColumn:
        """Add a column to tabular review"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Get max order_index
        max_order = self.db.query(TabularColumn.order_index).filter(
            TabularColumn.tabular_review_id == review_id
        ).order_by(TabularColumn.order_index.desc()).first()
        
        order_index = (max_order[0] + 1) if max_order else 0
        
        column = TabularColumn(
            tabular_review_id=review_id,
            column_label=column_label,
            column_type=column_type,
            prompt=prompt,
            order_index=order_index
        )
        
        self.db.add(column)
        self.db.commit()
        self.db.refresh(column)
        
        logger.info(f"Added column {column.id} to review {review_id}")
        return column
    
    def get_table_data(self, review_id: str, user_id: str) -> Dict[str, Any]:
        """Get table data for tabular review"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Get files for the case
        files = self.db.query(File).filter(File.case_id == review.case_id).all()
        
        # Get columns
        columns = self.db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).order_by(TabularColumn.order_index).all()
        
        # Get all cells
        cells = self.db.query(TabularCell).filter(
            TabularCell.tabular_review_id == review_id
        ).all()
        
        # Get document statuses
        statuses = self.db.query(TabularDocumentStatus).filter(
            TabularDocumentStatus.tabular_review_id == review_id,
            TabularDocumentStatus.user_id == user_id
        ).all()
        
        # Build cell map for quick lookup
        cell_map = {}
        for cell in cells:
            key = (cell.file_id, cell.column_id)
            cell_map[key] = cell
        
        # Build status map
        status_map = {s.file_id: s for s in statuses}
        
        # Build table data structure
        table_rows = []
        for file in files:
            row = {
                "file_id": file.id,
                "file_name": file.filename,
                "file_type": file.file_type,
                "status": status_map.get(file.id, {}).status if file.id in status_map else "not_reviewed",
                "cells": {}
            }
            
            for column in columns:
                key = (file.id, column.id)
                cell = cell_map.get(key)
                row["cells"][column.id] = {
                    "cell_value": cell.cell_value if cell else None,
                    "verbatim_extract": cell.verbatim_extract if cell else None,
                    "reasoning": cell.reasoning if cell else None,
                    "confidence_score": float(cell.confidence_score) if cell and cell.confidence_score else None,
                    "source_page": cell.source_page if cell else None,
                    "source_section": cell.source_section if cell else None,
                    "status": cell.status if cell else "pending",
                }
            
            table_rows.append(row)
        
        return {
            "review": {
                "id": review.id,
                "name": review.name,
                "description": review.description,
                "status": review.status,
            },
            "columns": [
                {
                    "id": col.id,
                    "column_label": col.column_label,
                    "column_type": col.column_type,
                    "prompt": col.prompt,
                    "order_index": col.order_index,
                }
                for col in columns
            ],
            "rows": table_rows,
        }
    
    async def extract_cell_value(
        self,
        file: File,
        column: TabularColumn
    ) -> Dict[str, Any]:
        """Extract cell value for a specific file and column"""
        try:
            # Get document text
            document_text = file.original_text or ""
            if not document_text:
                logger.warning(f"File {file.id} has no text content")
                return {
                    "file_id": file.id,
                    "column_id": column.id,
                    "cell_value": None,
                    "error": "No text content"
                }
            
            # Limit text to avoid token limits (use first 8000 chars)
            limited_text = document_text[:8000]
            
            # Build prompt based on column type
            system_prompt = f"""Ты эксперт по извлечению информации из юридических документов.
Твоя задача - ответить на вопрос о документе.

Тип ответа: {column.column_type}
- text: свободный текст
- date: дата в формате YYYY-MM-DD
- currency: денежная сумма (число)
- number: число
- yes_no: только "Yes" или "No"
- tags: список тегов через запятую
- verbatim: точная цитата из документа

ВАЖНО: Если информация не найдена, верни "N/A".
Если тип yes_no и информации нет, верни "Unknown"."""

            user_prompt = f"""Вопрос: {column.prompt}

Документ:
{limited_text}

Ответь на вопрос согласно типу ответа {column.column_type}.
Если это verbatim, приведи точную цитату из документа."""
            
            if not self.llm:
                raise ValueError("LLM not configured")
            
            # Call LLM
            from langchain_core.messages import SystemMessage, HumanMessage
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = await self.llm.ainvoke(messages)
            
            cell_value = response.content.strip() if hasattr(response, 'content') else str(response).strip()
            
            # Format value based on type
            if column.column_type == "yes_no":
                if cell_value.lower() in ["yes", "да", "есть"]:
                    cell_value = "Yes"
                elif cell_value.lower() in ["no", "нет", "нету"]:
                    cell_value = "No"
                else:
                    cell_value = "Unknown"
            
            # Extract verbatim if type is verbatim
            verbatim_extract = cell_value if column.column_type == "verbatim" else None
            
            # Extract reasoning (simplified - in production use structured output)
            reasoning = f"Извлечено из документа '{file.filename}' на основе вопроса: {column.prompt}"
            
            return {
                "file_id": file.id,
                "column_id": column.id,
                "cell_value": cell_value,
                "verbatim_extract": verbatim_extract,
                "reasoning": reasoning,
                "confidence_score": 0.85,  # Default confidence
            }
            
        except Exception as e:
            logger.error(f"Error extracting cell value for file {file.id}, column {column.id}: {e}", exc_info=True)
            return {
                "file_id": file.id,
                "column_id": column.id,
                "cell_value": None,
                "error": str(e)
            }
    
    async def run_extraction(self, review_id: str, user_id: str) -> Dict[str, Any]:
        """Run parallel extraction for all documents and columns"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Update status
        review.status = "processing"
        self.db.commit()
        
        try:
            # Get files
            files = self.db.query(File).filter(File.case_id == review.case_id).all()
            
            # Get columns
            columns = self.db.query(TabularColumn).filter(
                TabularColumn.tabular_review_id == review_id
            ).order_by(TabularColumn.order_index).all()
            
            if not files:
                raise ValueError("No files found for this case")
            
            if not columns:
                raise ValueError("No columns defined for this review")
            
            # Create tasks for parallel processing
            tasks = []
            for file in files:
                for column in columns:
                    task = self.extract_cell_value(file, column)
                    tasks.append(task)
            
            # Execute tasks in parallel
            logger.info(f"Starting parallel extraction: {len(tasks)} tasks")
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Save results to database
            saved_count = 0
            error_count = 0
            
            for result in results:
                if isinstance(result, Exception):
                    error_count += 1
                    logger.error(f"Extraction task failed: {result}")
                    continue
                
                if result.get("error"):
                    error_count += 1
                    continue
                
                # Check if cell already exists
                existing_cell = self.db.query(TabularCell).filter(
                    and_(
                        TabularCell.file_id == result["file_id"],
                        TabularCell.column_id == result["column_id"]
                    )
                ).first()
                
                if existing_cell:
                    # Update existing cell
                    existing_cell.cell_value = result.get("cell_value")
                    existing_cell.verbatim_extract = result.get("verbatim_extract")
                    existing_cell.reasoning = result.get("reasoning")
                    existing_cell.confidence_score = result.get("confidence_score")
                    existing_cell.status = "completed"
                    existing_cell.updated_at = datetime.utcnow()
                else:
                    # Create new cell
                    cell = TabularCell(
                        tabular_review_id=review_id,
                        file_id=result["file_id"],
                        column_id=result["column_id"],
                        cell_value=result.get("cell_value"),
                        verbatim_extract=result.get("verbatim_extract"),
                        reasoning=result.get("reasoning"),
                        confidence_score=result.get("confidence_score"),
                        status="completed"
                    )
                    self.db.add(cell)
                
                saved_count += 1
            
            self.db.commit()
            
            # Update review status
            review.status = "completed"
            review.updated_at = datetime.utcnow()
            self.db.commit()
            
            logger.info(f"Extraction completed: {saved_count} cells saved, {error_count} errors")
            
            return {
                "status": "completed",
                "saved_count": saved_count,
                "error_count": error_count,
                "total_tasks": len(tasks)
            }
            
        except Exception as e:
            logger.error(f"Error during extraction: {e}", exc_info=True)
            review.status = "draft"
            self.db.commit()
            raise
    
    def mark_as_reviewed(
        self,
        review_id: str,
        file_id: str,
        user_id: str,
        status: str
    ) -> TabularDocumentStatus:
        """Mark document as reviewed"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Get or create status
        doc_status = self.db.query(TabularDocumentStatus).filter(
            and_(
                TabularDocumentStatus.tabular_review_id == review_id,
                TabularDocumentStatus.file_id == file_id,
                TabularDocumentStatus.user_id == user_id
            )
        ).first()
        
        if not doc_status:
            doc_status = TabularDocumentStatus(
                tabular_review_id=review_id,
                file_id=file_id,
                user_id=user_id,
                status=status
            )
            self.db.add(doc_status)
        else:
            doc_status.status = status
            doc_status.updated_at = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(doc_status)
        
        return doc_status
    
    def export_to_csv(self, review_id: str, user_id: str) -> str:
        """Export tabular review to CSV format"""
        import csv
        import io
        
        data = self.get_table_data(review_id, user_id)
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write header
        header = ["Document"] + [col["column_label"] for col in data["columns"]]
        writer.writerow(header)
        
        # Write rows
        for row in data["rows"]:
            csv_row = [row["file_name"]]
            for col in data["columns"]:
                cell = row["cells"].get(col["id"], {})
                csv_row.append(cell.get("cell_value") or "")
            writer.writerow(csv_row)
        
        return output.getvalue()
    
    def export_to_excel(self, review_id: str, user_id: str) -> bytes:
        """Export tabular review to Excel format"""
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, Alignment
            import io
            
            data = self.get_table_data(review_id, user_id)
            
            # Create workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Tabular Review"
            
            # Write header
            header = ["Document"] + [col["column_label"] for col in data["columns"]]
            for col_num, value in enumerate(header, start=1):
                cell = ws.cell(row=1, column=col_num, value=value)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center')
            
            # Write rows
            for row_num, row in enumerate(data["rows"], start=2):
                ws.cell(row=row_num, column=1, value=row["file_name"])
                for col_num, col in enumerate(data["columns"], start=2):
                    cell = row["cells"].get(col["id"], {})
                    ws.cell(row=row_num, column=col_num, value=cell.get("cell_value") or "")
            
            # Auto-adjust column widths
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)  # Cap at 50 characters
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # Save to bytes
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            return output.read()
            
        except ImportError:
            logger.warning("openpyxl not installed, falling back to CSV")
            # Fallback to CSV if openpyxl not available
            csv_content = self.export_to_csv(review_id, user_id)
            return csv_content.encode('utf-8')

