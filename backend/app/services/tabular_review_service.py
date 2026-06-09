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
from app.services.llm_factory import create_llm
from app.config import config
from app.services.tabular_review_models import TabularCellExtractionModel, coerce_optional_int
from app.services.tabular_cell_pipeline import (
    cell_result_to_api_payload,
    cell_result_to_websocket_payload,
    run_tabular_cell_extraction,
    TabularColumnExtractionOutcome,
)
from app.services.tabular_extraction_policy import (
    coerce_source_references,
    count_nonempty_cells,
)
from app.services.tabular_cell_payload import build_tabular_cell_db_payload
from app.services.tabular_file_queries import (
    fetch_files_for_extraction,
    fetch_files_for_table,
    fetch_files_ids_only,
)
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
import json
import logging
import asyncio
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class TabularReviewService:
    """Service for managing tabular reviews"""
    
    def __init__(self, db: Session):
        """Initialize tabular review service"""
        self.db = db
        # Initialize LLM for extraction
        try:
            # Use use_rate_limiting=False for LangChain | operator compatibility
            self.llm = create_llm(temperature=0.1, use_rate_limiting=False)  # Low temperature for deterministic extraction
        except Exception as e:
            self.llm = None
            logger.warning(f"GigaChat not configured: {e}, extraction will not work")
    
    def create_tabular_review(
        self, 
        case_id: str, 
        user_id: str,
        name: str, 
        description: Optional[str] = None,
        selected_file_ids: Optional[List[str]] = None
    ) -> TabularReview:
        """Create a new tabular review"""
        # Verify case exists and belongs to user
        case = self.db.query(Case).filter(
            and_(Case.id == case_id, Case.user_id == user_id)
        ).first()
        
        if not case:
            raise ValueError(f"Case {case_id} not found or access denied")
        
        # Verify selected files belong to the case
        if selected_file_ids:
            files = fetch_files_ids_only(self.db, case_id, selected_file_ids)
            if len(files) != len(selected_file_ids):
                raise ValueError("Some selected files do not belong to this case")
        
        review = TabularReview(
            case_id=case_id,
            user_id=user_id,
            name=name,
            description=description,
            status="draft",
            selected_file_ids=selected_file_ids
        )
        
        # #region agent log
        logger.debug(f"[DEBUG HYPOTHESIS Q] [create_tabular_review] Before commit: review_id will be {review.id if hasattr(review, 'id') else 'NEW'}, case_id={case_id}, user_id={user_id}")
        # #endregion
        
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        
        # #region agent log
        logger.debug(f"[DEBUG HYPOTHESIS R] [create_tabular_review] After commit: review_id={review.id}, checking for columns")
        # #endregion
        
        # Check if any columns were automatically created
        columns = self.db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review.id
        ).all()
        
        # #region agent log
        logger.debug(f"[DEBUG HYPOTHESIS S] [create_tabular_review] Found columns after commit: review_id={review.id}, columns_count={len(columns)}, column_labels={[c.column_label for c in columns]}")
        # #endregion
        
        # CRITICAL: Check for unwanted default columns and delete them immediately
        unwanted_column_labels = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]
        unwanted_columns = [c for c in columns if c.column_label in unwanted_column_labels]
        
        if unwanted_columns:
            logger.error(f"[create_tabular_review] CRITICAL: Found {len(unwanted_columns)} unwanted default columns! Deleting them immediately: {[c.column_label for c in unwanted_columns]}")
            # #region agent log
            logger.debug(f"[DEBUG HYPOTHESIS T] [create_tabular_review] Found unwanted columns: review_id={review.id}, unwanted_count={len(unwanted_columns)}, unwanted_labels={[c.column_label for c in unwanted_columns]}")
            # #endregion
            for unwanted_col in unwanted_columns:
                # Delete all cells for this column first
                from app.models.tabular_review import TabularCell
                self.db.query(TabularCell).filter(TabularCell.column_id == unwanted_col.id).delete()
                # Delete the column
                self.db.delete(unwanted_col)
            self.db.commit()
            logger.info(f"[create_tabular_review] Deleted {len(unwanted_columns)} unwanted columns")
            # Refresh columns after deletion
            columns = self.db.query(TabularColumn).filter(
                TabularColumn.tabular_review_id == review.id
            ).all()
        
        columns_count = len(columns)
        logger.info(f"Created tabular review {review.id} for case {case_id} with {len(selected_file_ids) if selected_file_ids else 0} selected files. Columns count: {columns_count}")
        if columns_count > 0:
            logger.warning(f"WARNING: Tabular review {review.id} was created with {columns_count} columns automatically! This should not happen.")
            for col in columns:
                logger.warning(f"  - Auto-created column: {col.column_label} (type: {col.column_type}, order: {col.order_index})")
        
        return review
    
    def delete_review(
        self,
        review_id: str,
        user_id: str
    ) -> bool:
        """Delete a tabular review (cascade deletes all columns, cells, etc.)"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Delete review (cascade will delete all columns, cells, document_statuses, etc.)
        self.db.delete(review)
        self.db.commit()
        
        logger.info(f"Deleted tabular review {review_id}")
        return True
    
    def update_review(
        self,
        review_id: str,
        user_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> TabularReview:
        """Update review name/description"""
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()

        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")

        if name is not None:
            review.name = name.strip()
        if description is not None:
            review.description = description

        self.db.commit()
        self.db.refresh(review)
        logger.info(f"Updated tabular review {review_id}")
        return review

    def add_column(
        self,
        review_id: str,
        column_label: str,
        column_type: str,
        prompt: str,
        user_id: str,
        column_config: Optional[Dict[str, Any]] = None
    ) -> TabularColumn:
        """Add a column to tabular review"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")

        from app.services.tabular_column_type_contract import (
            validate_column_config,
            validate_column_type,
        )

        column_type = validate_column_type(column_type)
        validate_column_config(column_type, column_config)
        
        # Get max order_index
        max_order = self.db.query(TabularColumn.order_index).filter(
            TabularColumn.tabular_review_id == review_id
        ).order_by(TabularColumn.order_index.desc()).first()
        
        # Log columns count before adding
        columns_before = self.db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).all()
        # #region agent log
        logger.debug(f"[DEBUG HYPOTHESIS A] [add_column] Before adding column: review_id={review_id}, columns_before_count={len(columns_before)}, columns_before_labels={[c.column_label for c in columns_before]}, new_column_label={column_label}, new_column_type={column_type}")
        # #endregion
        logger.info(f"[add_column] Before adding: {len(columns_before)} columns in review {review_id}: {[c.column_label for c in columns_before]}")
        
        order_index = (max_order[0] + 1) if max_order else 0
        
        column = TabularColumn(
            tabular_review_id=review_id,
            column_label=column_label,
            column_type=column_type,
            prompt=prompt,
            column_config=column_config,
            order_index=order_index
        )
        
        self.db.add(column)
        # #region agent log
        logger.debug(f"[DEBUG HYPOTHESIS B] [add_column] About to commit new column: review_id={review_id}, column_id={column.id}, column_label={column_label}")
        # #endregion
        self.db.commit()
        self.db.refresh(column)
        
        # Check total columns count after adding
        columns_after = self.db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).all()
        
        # #region agent log
        logger.debug(f"[DEBUG HYPOTHESIS C] [add_column] After commit, checking columns: review_id={review_id}, columns_after_count={len(columns_after)}, columns_after_labels={[c.column_label for c in columns_after]}, expected_count={len(columns_before)+1}")
        # #endregion
        logger.info(f"[add_column] After adding: {len(columns_after)} columns in review {review_id}: {[c.column_label for c in columns_after]}")
        
        # CRITICAL: Check for unwanted default columns and delete them immediately
        unwanted_column_labels = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]
        unwanted_columns = [c for c in columns_after if c.column_label in unwanted_column_labels and c.id != column.id]
        
        # #region agent log
        if unwanted_columns:
            logger.debug(f"[DEBUG HYPOTHESIS D] [add_column] Found unwanted columns after commit: review_id={review_id}, unwanted_count={len(unwanted_columns)}, unwanted_labels={[c.column_label for c in unwanted_columns]}, unwanted_ids={[c.id for c in unwanted_columns]}")
        # #endregion
        
        if unwanted_columns:
            logger.error(f"[add_column] CRITICAL: Found {len(unwanted_columns)} unwanted default columns! Deleting them immediately: {[c.column_label for c in unwanted_columns]}")
            for unwanted_col in unwanted_columns:
                # Delete all cells for this column first
                from app.models.tabular_review import TabularCell
                self.db.query(TabularCell).filter(TabularCell.column_id == unwanted_col.id).delete()
                # Delete the column
                self.db.delete(unwanted_col)
            self.db.commit()
            logger.info(f"[add_column] Deleted {len(unwanted_columns)} unwanted columns")
            # Refresh columns_after after deletion
            columns_after = self.db.query(TabularColumn).filter(
                TabularColumn.tabular_review_id == review_id
            ).all()
        
        if len(columns_after) > len(columns_before) + 1:
            logger.error(f"[add_column] ERROR: More than one column was added! Expected {len(columns_before) + 1}, got {len(columns_after)}")
            logger.error(f"[add_column] Added columns: {[c.column_label for c in columns_after if c.id != column.id and c not in columns_before]}")
            # CRITICAL: If more than one column was added, something is wrong - rollback and raise error
            self.db.rollback()
            raise ValueError(f"ERROR: More than one column was added automatically! This should not happen. Expected {len(columns_before) + 1}, got {len(columns_after)}")
        
        logger.info(f"Added column {column.id} ({column.column_label}, type: {column.column_type}) to review {review_id}. Total columns: {len(columns_after)}")
        return column
    
    def update_column(
        self,
        review_id: str,
        column_id: str,
        user_id: str,
        column_label: Optional[str] = None,
        column_type: Optional[str] = None,
        prompt: Optional[str] = None,
        column_config: Optional[Dict[str, Any]] = None
    ) -> TabularColumn:
        """Update a column (rename, type, prompt, config)"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Get the column
        column = self.db.query(TabularColumn).filter(
            and_(
                TabularColumn.id == column_id,
                TabularColumn.tabular_review_id == review_id
            )
        ).first()
        
        if not column:
            raise ValueError(f"Column {column_id} not found in review {review_id}")
        
        # Update fields
        if column_label is not None:
            column.column_label = column_label
        if column_type is not None:
            from app.services.tabular_column_type_contract import (
                validate_column_config,
                validate_column_type,
            )

            normalized_type = validate_column_type(column_type)
            effective_config = (
                column_config if column_config is not None else column.column_config
            )
            validate_column_config(normalized_type, effective_config)
            column.column_type = normalized_type
        if prompt is not None:
            column.prompt = prompt
        if column_config is not None:
            column.column_config = column_config
        
        self.db.commit()
        self.db.refresh(column)
        
        logger.info(f"Updated column {column_id} in review {review_id}")
        return column
    
    def delete_column(
        self,
        review_id: str,
        column_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Delete a column and related rows in review queue; compact order_index."""
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()

        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")

        column = self.db.query(TabularColumn).filter(
            and_(
                TabularColumn.id == column_id,
                TabularColumn.tabular_review_id == review_id,
            )
        ).first()

        if not column:
            raise ValueError(f"Column {column_id} not found in review {review_id}")

        column_label = column.column_label
        deleted_order = column.order_index

        # Explicit deletes: ORM backrefs on review_queue_items would NULL FKs (NOT NULL → 500).
        from app.models.tabular_review import (
            CellComment,
            CellHistory,
            ReviewQueueItem,
            TabularCell,
        )

        self.db.query(ReviewQueueItem).filter(
            ReviewQueueItem.column_id == column_id,
        ).delete(synchronize_session=False)
        self.db.query(CellComment).filter(
            CellComment.column_id == column_id,
        ).delete(synchronize_session=False)
        self.db.query(CellHistory).filter(
            CellHistory.column_id == column_id,
        ).delete(synchronize_session=False)
        self.db.query(TabularCell).filter(
            TabularCell.column_id == column_id,
        ).delete(synchronize_session=False)

        self.db.delete(column)
        self.db.flush()

        remaining = (
            self.db.query(TabularColumn)
            .filter(TabularColumn.tabular_review_id == review_id)
            .order_by(TabularColumn.order_index)
            .all()
        )
        for index, col in enumerate(remaining):
            col.order_index = index

        review.updated_at = datetime.utcnow()
        self.db.commit()

        logger.info(
            "Deleted column %s (%s) from review %s",
            column_id,
            column_label,
            review_id,
        )
        return {
            "column_id": column_id,
            "column_label": column_label,
            "order_index": deleted_order,
        }

    async def delete_column_and_notify(
        self,
        review_id: str,
        column_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Delete column in DB and broadcast column_deleted to connected clients."""
        payload = self.delete_column(review_id, column_id, user_id)
        from app.services.websocket_manager import websocket_manager

        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "column_deleted",
                "column_id": payload["column_id"],
                "column_label": payload.get("column_label"),
            },
        )
        return payload
    
    def reorder_columns(
        self,
        review_id: str,
        column_ids: List[str],
        user_id: str
    ) -> List[TabularColumn]:
        """Reorder columns by providing ordered list of column IDs"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Get all columns for this review
        columns = self.db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).all()
        
        column_map = {col.id: col for col in columns}
        
        # Verify all provided IDs exist and belong to this review
        for col_id in column_ids:
            if col_id not in column_map:
                raise ValueError(f"Column {col_id} not found in review {review_id}")
        
        # Update order_index for each column
        for index, col_id in enumerate(column_ids):
            column_map[col_id].order_index = index
        
        # Handle columns not in the list (shouldn't happen, but be safe)
        for col in columns:
            if col.id not in column_ids:
                # Put them at the end
                col.order_index = len(column_ids) + columns.index(col)
        
        self.db.commit()
        
        # Return columns in new order
        updated_columns = self.db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).order_by(TabularColumn.order_index).all()
        
        logger.info(f"Reordered columns for review {review_id}")
        return updated_columns
    
    def get_table_data(self, review_id: str, user_id: str) -> Dict[str, Any]:
        """Get table data for tabular review"""
        # #region agent log
        logger.debug(f"[DEBUG HYPOTHESIS J] [get_table_data] Called: review_id={review_id}, user_id={user_id}")
        # #endregion
        
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Metadata only — no file_content / html_content blobs
        file_ids = review.selected_file_ids if review.selected_file_ids else None
        files = fetch_files_for_table(self.db, review.case_id, file_ids)
        
        # Get columns
        columns = self.db.query(TabularColumn).filter(
            TabularColumn.tabular_review_id == review_id
        ).order_by(TabularColumn.order_index).all()
        
        # #region agent log
        logger.debug(f"[DEBUG HYPOTHESIS K] [get_table_data] Before cleanup: review_id={review_id}, columns_count={len(columns)}, column_labels={[c.column_label for c in columns]}")
        # #endregion
        
        # CRITICAL: Check for unwanted default columns and delete them immediately
        # Also check for variations and case-insensitive matches
        unwanted_column_labels = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]
        unwanted_column_labels_lower = [label.lower() for label in unwanted_column_labels]
        unwanted_columns = []
        for c in columns:
            # Check exact match
            if c.column_label in unwanted_column_labels:
                unwanted_columns.append(c)
            # Check case-insensitive match
            elif c.column_label.lower() in unwanted_column_labels_lower:
                unwanted_columns.append(c)
            # Check for variations like "Per on mentioned" (typo for "Persons mentioned")
            elif "per on" in c.column_label.lower() and "mentioned" in c.column_label.lower():
                unwanted_columns.append(c)
        
        if unwanted_columns:
            logger.error(f"[get_table_data] CRITICAL: Found {len(unwanted_columns)} unwanted default columns! Deleting them immediately: {[c.column_label for c in unwanted_columns]}")
            # #region agent log
            logger.debug(f"[DEBUG HYPOTHESIS L] [get_table_data] Found unwanted columns: review_id={review_id}, unwanted_count={len(unwanted_columns)}, unwanted_labels={[c.column_label for c in unwanted_columns]}")
            # #endregion
            for unwanted_col in unwanted_columns:
                # Delete all cells for this column first
                from app.models.tabular_review import TabularCell
                self.db.query(TabularCell).filter(TabularCell.column_id == unwanted_col.id).delete()
                # Delete all comments for this column
                from app.models.tabular_review import CellComment
                self.db.query(CellComment).filter(CellComment.column_id == unwanted_col.id).delete()
                # Delete all history records for this column
                from app.models.tabular_review import CellHistory
                self.db.query(CellHistory).filter(CellHistory.column_id == unwanted_col.id).delete()
                # Delete the column
                self.db.delete(unwanted_col)
            self.db.commit()
            logger.info(f"[get_table_data] Deleted {len(unwanted_columns)} unwanted columns and all related data")
            # Refresh columns after deletion
            columns = self.db.query(TabularColumn).filter(
                TabularColumn.tabular_review_id == review_id
            ).order_by(TabularColumn.order_index).all()
        
        # #region agent log
        logger.debug(f"[DEBUG HYPOTHESIS M] [get_table_data] After cleanup: review_id={review_id}, columns_count={len(columns)}, column_labels={[c.column_label for c in columns]}")
        # #endregion
        
        # Log all columns found
        logger.info(f"[get_table_data] Found {len(columns)} columns for review {review_id}: {[c.column_label for c in columns]}")
        
        # CRITICAL: Check for orphaned cells (cells with column_id that doesn't exist in columns)
        from app.models.tabular_review import TabularCell
        all_cells = self.db.query(TabularCell).filter(
            TabularCell.tabular_review_id == review_id
        ).all()
        column_ids_set = {col.id for col in columns}
        orphaned_cells = [cell for cell in all_cells if cell.column_id not in column_ids_set]
        if orphaned_cells:
            logger.error(f"[get_table_data] CRITICAL: Found {len(orphaned_cells)} orphaned cells (cells with column_id that doesn't exist)! Orphaned column_ids: {set(cell.column_id for cell in orphaned_cells)}")
            # #region agent log
            logger.debug(f"[DEBUG HYPOTHESIS N] [get_table_data] Found orphaned cells: review_id={review_id}, orphaned_count={len(orphaned_cells)}, orphaned_column_ids={list(set(cell.column_id for cell in orphaned_cells))}")
            # #endregion
            # Delete orphaned cells
            for orphaned_cell in orphaned_cells:
                self.db.delete(orphaned_cell)
            self.db.commit()
            logger.info(f"[get_table_data] Deleted {len(orphaned_cells)} orphaned cells")
        
        # Get all cells (after deleting orphaned ones)
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
                cell_value = cell.cell_value if cell else None
                
                # Parse JSON if cell_value is a JSON string
                if cell_value and isinstance(cell_value, str) and cell_value.strip().startswith("{"):
                    try:
                        import json
                        parsed = json.loads(cell_value)
                        if isinstance(parsed, dict) and "cell_value" in parsed:
                            cell_value = parsed["cell_value"]
                    except (json.JSONDecodeError, ValueError):
                        # Not valid JSON, keep original value
                        pass
                
                row["cells"][column.id] = {
                    "cell_value": cell_value,
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
                "selected_file_ids": review.selected_file_ids,
                "table_mode": getattr(review, "table_mode", "document"),
                "entity_config": getattr(review, "entity_config", None),
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

    @staticmethod
    def _coerce_source_references(raw: Any) -> List[Dict[str, Any]]:
        return coerce_source_references(raw)
    
    def _normalize_extraction_result(
        self,
        result_dict: Dict[str, Any],
        column: TabularColumn,
        file: File
    ) -> Dict[str, Any]:
        """
        Normalize LLM extraction result to match TabularCellExtractionModel schema.
        """
        from app.services.tabular_column_type_contract import finalize_extraction_dict

        merged = dict(result_dict)
        if not merged.get("reasoning"):
            merged["reasoning"] = (
                f"Извлечено из документа '{file.filename}' для колонки '{column.column_label}'"
            )

        if "confidence" in merged:
            try:
                merged["confidence"] = float(merged["confidence"])
            except (ValueError, TypeError):
                merged["confidence"] = 0.8

        for int_field in ("source_page", "source_start_line", "source_end_line"):
            if int_field in merged and merged[int_field] is not None:
                merged[int_field] = coerce_optional_int(merged[int_field])

        finalized = finalize_extraction_dict(
            merged,
            column_type=str(column.column_type),
            column_config=column.column_config if isinstance(column.column_config, dict) else None,
        )
        logger.debug(
            "Normalized extraction result: %s -> %s",
            list(result_dict.keys()),
            list(finalized.keys()),
        )
        return finalized
    
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
            column_type_descriptions = {
                "text": "свободный текст",
                "number": "числовое значение",
                "currency": "денежная сумма с валютой (например: '100000 USD' или '50 000 руб.')",
                "yes_no": "только «Да» или «Нет» (русский канон)",
                "date": "дата в формате YYYY-MM-DD или DD.MM.YYYY",
                "tag": "один тег из предопределенного списка",
                "verbatim": "точная цитата из документа с указанием источника",
                "manual_input": "ручной ввод (не используется AI)",
            }
            
            type_desc = column_type_descriptions.get(column.column_type, "свободный текст")
            
            # Для tag добавляем доступные опции
            tag_options_text = ""
            if column.column_type == "tag" and column.column_config:
                options = column.column_config.get("options", [])
                if options:
                    tag_options_text = f"\n\nДоступные опции: {', '.join([opt.get('label', '') for opt in options])}"
            
            # Улучшенные инструкции по формату для каждого типа
            type_format_instructions = {
                "number": """
КРИТИЧЕСКИ ВАЖНО для типа number:
- cell_value ДОЛЖЕН быть ТОЛЬКО числом (например: "100", "3.14", "1000")
- БЕЗ текста, БЕЗ валютных символов ($, руб., USD и т.д.), БЕЗ единиц измерения
- Только цифры, точка или запятая для десятичных чисел
- Примеры ПРАВИЛЬНО: "100", "3.14", "1000.5", "1234"
- Примеры НЕПРАВИЛЬНО: "100 USD", "100 рублей", "около 100", "100 шт."
""",
                "currency": """
КРИТИЧЕСКИ ВАЖНО для типа currency:
- cell_value ДОЛЖЕН содержать число и валюту
- Формат: "ЧИСЛО ВАЛЮТА" (например: "100000 USD", "50000 RUB", "50 000 руб.")
- Число должно быть валидным (только цифры, точка/запятая)
- Валюта указывается после числа (USD, RUB, EUR, руб. и т.д.)
- Примеры ПРАВИЛЬНО: "100000 USD", "50 000 руб.", "5000 EUR"
""",
                "date": """
КРИТИЧЕСКИ ВАЖНО для типа date:
- cell_value ДОЛЖЕН быть ДАТОЙ в формате YYYY-MM-DD
- ТОЛЬКО формат YYYY-MM-DD, никаких других форматов
- Примеры ПРАВИЛЬНО: "2024-01-15", "2023-12-31", "2024-03-05"
- Примеры НЕПРАВИЛЬНО: "15.01.2024", "2024/01/15", "15 января 2024"
""",
                "yes_no": """
КРИТИЧЕСКИ ВАЖНО для типа yes_no:
- cell_value ДОЛЖЕН быть ТОЛЬКО «Да», «Нет» или N/A
- Положительный ответ по документу — «Да»; отрицательный — «Нет»; данных нет — N/A
- Не используй Yes/No, true/false, 1/0, Unknown
- Примеры ПРАВИЛЬНО: «Да», «Нет», N/A
""",
                "tag": """
КРИТИЧЕСКИ ВАЖНО для типа tag:
- cell_value ДОЛЖЕН быть ОДНИМ из предопределенных тегов из списка выше
- Используй ТОЛЬКО опции из списка, БЕЗ создания новых тегов
""",
            }
            
            format_instruction = type_format_instructions.get(column.column_type, "")
            
            system_prompt = f"""Ты эксперт по извлечению информации из юридических документов.
Твоя задача - ответить на вопрос о документе и предоставить подробное обоснование.

Тип ответа: {column.column_type}
Описание: {type_desc}{tag_options_text}

{format_instruction}

ВАЖНО:
1. Если информация не найдена, верни "N/A" для cell_value
2. СТРОГО соблюдай формат для типа {column.column_type} - это КРИТИЧЕСКИ ВАЖНО
3. Для yes_no: только «Да», «Нет» или N/A
4. Для verbatim: приведи точную цитату из документа
5. Для tag: используй ТОЛЬКО опции из списка выше
6. ВСЕГДА указывай reasoning - подробное объяснение, откуда взялась информация
7. ВСЕГДА указывай source_references - конкретные места в документе (страницы, разделы, цитаты)
8. ВСЕГДА указывай verbatim_extract - дословная цитата из документа (5-25 слов), которая БУКВАЛЬНО содержит ответ, без изменений и перефразирования

Формат ответа (JSON):
{{
    "cell_value": "извлеченное значение (СТРОГО по формату типа {column.column_type})",
    "verbatim_extract": "дословная цитата из документа, буквально содержащая ответ (5-25 слов, точно как в тексте)",
    "reasoning": "подробное объяснение, почему именно такой ответ, с указанием конкретных мест в документе",
    "source_references": [
        {{"page": 1, "section": "Раздел 3.1", "text": "цитата из документа"}},
        {{"page": 2, "section": null, "text": "еще одна цитата"}}
    ],
    "confidence": 0.9
}}"""

            user_prompt = f"""Вопрос: {column.prompt}

Документ ({file.filename}):
{limited_text}

Извлеки информацию согласно типу {column.column_type} и верни JSON с cell_value, verbatim_extract, reasoning и source_references."""
            
            if not self.llm:
                raise ValueError("LLM not configured")
            
            # Try structured output first, fallback to regular if not supported
            try:
                from app.services.tabular_review_models import TabularCellExtractionModel
                from langchain_core.messages import SystemMessage, HumanMessage
                
                # Use structured output if LLM supports it.
                # Prefer json_mode to avoid provider-specific JSON Schema validation issues
                # (e.g. `additionalProperties must be false`).
                if hasattr(self.llm, 'with_structured_output'):
                    structured_llm = self.llm.with_structured_output(
                        TabularCellExtractionModel,
                        method="json_mode"
                    )
                    messages = [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=user_prompt)
                    ]
                    result = await structured_llm.ainvoke(messages)
                    
                    # #region agent log
                    import json
                    import os
                    log_data = {
                        "timestamp": int(__import__('time').time() * 1000),
                        "location": "tabular_review_service.py:677",
                        "message": "Structured LLM result",
                        "data": {
                            "result_is_none": result is None,
                            "result_type": str(type(result)) if result else "None",
                            "has_model_dump": hasattr(result, 'model_dump') if result else False,
                            "column_type": column.column_type,
                            "column_label": column.column_label,
                            "file_id": file.id
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "A"
                    }
                    logger.info(f"[DEBUG] {json.dumps(log_data)}")
                    # Try to write to file if local
                    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
                    try:
                        os.makedirs(os.path.dirname(log_path), exist_ok=True)
                        with open(log_path, 'a') as f:
                            f.write(json.dumps(log_data) + "\n")
                    except Exception:
                        pass  # File logging not available (e.g., on Render)
                    # #endregion
                    
                    if result is None:
                        logger.error(f"Structured LLM returned None for column {column.column_label} (type: {column.column_type}), file {file.id}")
                        raise ValueError("Structured LLM returned None")
                    
                    if not hasattr(result, 'model_dump'):
                        logger.error(f"Structured LLM result has no model_dump method for column {column.column_label} (type: {column.column_type}), file {file.id}, result type: {type(result)}")
                        # Попробуем получить данные другим способом
                        if hasattr(result, 'dict'):
                            result_dict = result.dict()
                        elif hasattr(result, '__dict__'):
                            result_dict = result.__dict__
                        elif isinstance(result, dict):
                            result_dict = result
                        else:
                            raise ValueError(f"Cannot extract data from structured LLM result: {type(result)}")
                    else:
                        # Устанавливаем column_type для активации валидации
                        result_dict = result.model_dump()
                    
                    # Normalize field names - GigaChat may return different field names
                    result_dict = self._normalize_extraction_result(result_dict, column, file)
                    
                    # #region agent log
                    import json
                    import os
                    log_data = {
                        "timestamp": int(__import__('time').time() * 1000),
                        "location": "tabular_review_service.py:717",
                        "message": "Before validation",
                        "data": {
                            "raw_cell_value": result_dict.get("cell_value"),
                            "column_type": column.column_type,
                            "column_label": column.column_label
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B"
                    }
                    logger.info(f"[DEBUG] {json.dumps(log_data)}")
                    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
                    try:
                        with open(log_path, 'a') as f:
                            f.write(json.dumps(log_data) + "\n")
                    except Exception:
                        pass
                    # #endregion
                    
                    result_dict['column_type'] = column.column_type
                    
                    # Создаем новый экземпляр с column_type для валидации
                    validated_result = TabularCellExtractionModel(**result_dict)
                    
                    # #region agent log
                    import json
                    import os
                    log_data = {
                        "timestamp": int(__import__('time').time() * 1000),
                        "location": "tabular_review_service.py:750",
                        "message": "After validation",
                        "data": {
                            "validated_cell_value": validated_result.cell_value,
                            "normalized_value": validated_result.normalized_value,
                            "column_type": column.column_type,
                            "column_label": column.column_label
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B"
                    }
                    logger.info(f"[DEBUG] {json.dumps(log_data)}")
                    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
                    try:
                        with open(log_path, 'a') as f:
                            f.write(json.dumps(log_data) + "\n")
                    except Exception:
                        pass
                    # #endregion
                    
                    cell_value = validated_result.cell_value  # Уже валидировано и нормализовано
                    reasoning = validated_result.reasoning
                    source_references = validated_result.source_references or []
                    confidence = validated_result.confidence
                    normalized_value = validated_result.normalized_value
                    verbatim_extract = validated_result.verbatim_extract
                else:
                    # Fallback to regular LLM call with JSON parsing
                    messages = [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=user_prompt)
                    ]
                    response = await self.llm.ainvoke(messages)
                    response_text = response.content.strip() if hasattr(response, 'content') else str(response).strip()
                    
                    # Filter out refusal responses from LLM
                    refusal_patterns = [
                        r'не обладаю.*мнением',
                        r'не транслирую.*мнение',
                        r'ответ сгенерирован.*моделью',
                        r'разговоры.*ограничены',
                        r'не могу.*ответить',
                        r'ограничены.*темы',
                        r'неправильного толкования',
                        r'чувствительные темы',
                    ]
                    for pattern in refusal_patterns:
                        if re.search(pattern, response_text, re.IGNORECASE):
                            logger.warning(f"LLM returned refusal response, retrying with different prompt")
                            # Retry with a more direct prompt
                            retry_prompt = f"Извлеки информацию из документа. Вопрос: {column.prompt}\n\nДокумент:\n{limited_text}\n\nВерни только JSON с полями cell_value, reasoning, source_references."
                            retry_messages = [
                                SystemMessage(content="Ты помощник для извлечения информации из юридических документов. Всегда отвечай на русском языке."),
                                HumanMessage(content=retry_prompt)
                            ]
                            response = await self.llm.ainvoke(retry_messages)
                            response_text = response.content.strip() if hasattr(response, 'content') else str(response).strip()
                            break
                    
                    # Try to parse JSON from response
                    import json
                    import re
                    # Extract JSON from response (might be wrapped in markdown code blocks)
                    # Improved regex to match nested JSON objects
                    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*"cell_value"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response_text, re.DOTALL)
                    if json_match:
                        try:
                            parsed = json.loads(json_match.group(0))
                            cell_value_raw = parsed.get("cell_value", response_text)
                            reasoning = parsed.get("reasoning", f"Извлечено из документа '{file.filename}'")
                            source_references = parsed.get("source_references", [])
                            confidence = parsed.get("confidence", 0.85)
                        except:
                            cell_value_raw = response_text
                            reasoning = f"Извлечено из документа '{file.filename}' на основе вопроса: {column.prompt}"
                            source_references = []
                            confidence = 0.85
                    else:
                        cell_value_raw = response_text
                        reasoning = f"Извлечено из документа '{file.filename}' на основе вопроса: {column.prompt}"
                        source_references = []
                        confidence = 0.85
                    
                    # После парсинга JSON создаем модель с валидацией
                    # #region agent log
                    import json
                    import os
                    log_data = {
                        "timestamp": int(__import__('time').time() * 1000),
                        "location": "tabular_review_service.py:790",
                        "message": "Before validation (fallback JSON)",
                        "data": {
                            "raw_cell_value": cell_value_raw,
                            "column_type": column.column_type,
                            "column_label": column.column_label,
                            "file_id": file.id
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "C"
                    }
                    logger.info(f"[DEBUG] {json.dumps(log_data)}")
                    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
                    try:
                        with open(log_path, 'a') as f:
                            f.write(json.dumps(log_data) + "\n")
                    except Exception:
                        pass
                    # #endregion
                    
                    try:
                        parsed_result = TabularCellExtractionModel(
                            cell_value=cell_value_raw,
                            reasoning=reasoning,
                            source_references=source_references,
                            confidence=confidence,
                            column_type=column.column_type  # Ключевой момент - передаем тип колонки
                        )
                        
                        # #region agent log
                        import json
                        import os
                        log_data = {
                            "timestamp": int(__import__('time').time() * 1000),
                            "location": "tabular_review_service.py:810",
                            "message": "After validation (fallback JSON)",
                            "data": {
                                "validated_cell_value": parsed_result.cell_value,
                                "normalized_value": parsed_result.normalized_value,
                                "column_type": column.column_type,
                                "column_label": column.column_label
                            },
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "C"
                        }
                        logger.info(f"[DEBUG] {json.dumps(log_data)}")
                        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
                        try:
                            with open(log_path, 'a') as f:
                                f.write(json.dumps(log_data) + "\n")
                        except Exception:
                            pass
                        # #endregion
                        
                        cell_value = parsed_result.cell_value  # Валидированное значение
                        normalized_value = parsed_result.normalized_value
                        verbatim_extract = parsed_result.verbatim_extract
                    except Exception as validation_error:
                        logger.warning(f"Validation failed: {validation_error}, using raw value")
                        # #region agent log
                        import json
                        import os
                        log_data = {
                            "timestamp": int(__import__('time').time() * 1000),
                            "location": "tabular_review_service.py:830",
                            "message": "Validation error",
                            "data": {
                                "error": str(validation_error),
                                "raw_cell_value": cell_value_raw,
                                "column_type": column.column_type,
                                "column_label": column.column_label
                            },
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "D"
                        }
                        logger.info(f"[DEBUG] {json.dumps(log_data)}")
                        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
                        try:
                            with open(log_path, 'a') as f:
                                f.write(json.dumps(log_data) + "\n")
                        except Exception:
                            pass
                        # #endregion
                        cell_value = cell_value_raw
                        normalized_value = None
                        verbatim_extract = None
            except Exception as e:
                logger.warning(f"Structured output failed, using fallback: {e}")
                # Fallback to simple extraction
                from langchain_core.messages import SystemMessage, HumanMessage
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt)
                ]
                response = await self.llm.ainvoke(messages)
                cell_value_raw = response.content.strip() if hasattr(response, 'content') else str(response).strip()
                reasoning = f"Извлечено из документа '{file.filename}' на основе вопроса: {column.prompt}"
                source_references = []
                confidence = 0.85
                
                # Применяем валидацию через модель
                # #region agent log
                import json
                import os
                log_data = {
                    "timestamp": int(__import__('time').time() * 1000),
                    "location": "tabular_review_service.py:850",
                    "message": "Before validation (final fallback)",
                    "data": {
                        "raw_cell_value": cell_value_raw,
                        "column_type": column.column_type,
                        "column_label": column.column_label,
                        "file_id": file.id
                    },
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "E"
                }
                logger.info(f"[DEBUG] {json.dumps(log_data)}")
                log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
                try:
                    with open(log_path, 'a') as f:
                        f.write(json.dumps(log_data) + "\n")
                except Exception:
                    pass
                # #endregion
                
                try:
                    parsed_result = TabularCellExtractionModel(
                        cell_value=cell_value_raw,
                        reasoning=reasoning,
                        source_references=source_references,
                        confidence=confidence,
                        column_type=column.column_type
                    )
                    
                    # #region agent log
                    import json
                    import os
                    log_data = {
                        "timestamp": int(__import__('time').time() * 1000),
                        "location": "tabular_review_service.py:870",
                        "message": "After validation (final fallback)",
                        "data": {
                            "validated_cell_value": parsed_result.cell_value,
                            "normalized_value": parsed_result.normalized_value,
                            "column_type": column.column_type,
                            "column_label": column.column_label
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "E"
                    }
                    logger.info(f"[DEBUG] {json.dumps(log_data)}")
                    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
                    try:
                        with open(log_path, 'a') as f:
                            f.write(json.dumps(log_data) + "\n")
                    except Exception:
                        pass
                    # #endregion
                    
                    cell_value = parsed_result.cell_value
                    normalized_value = parsed_result.normalized_value
                    verbatim_extract = parsed_result.verbatim_extract
                except Exception as validation_error:
                    logger.warning(f"Validation failed in fallback: {validation_error}, using raw value")
                    # #region agent log
                    import json
                    import os
                    log_data = {
                        "timestamp": int(__import__('time').time() * 1000),
                        "location": "tabular_review_service.py:890",
                        "message": "Validation error (final fallback)",
                        "data": {
                            "error": str(validation_error),
                            "raw_cell_value": cell_value_raw,
                            "column_type": column.column_type,
                            "column_label": column.column_label
                        },
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "E"
                    }
                    logger.info(f"[DEBUG] {json.dumps(log_data)}")
                    log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.cursor', 'debug.log')
                    try:
                        with open(log_path, 'a') as f:
                            f.write(json.dumps(log_data) + "\n")
                    except Exception:
                        pass
                    # #endregion
                    cell_value = cell_value_raw
                    normalized_value = None
                    verbatim_extract = cell_value if column.column_type == "verbatim" else None
            
            # Дополнительная обработка для tag типа (валидация против опций)
            if column.column_type == "tag" and column.column_config and column.column_config.get("options"):
                valid_options = [opt.get("label", "").lower() for opt in column.column_config["options"]]
                # Проверяем, что значение соответствует одному из опций
                if cell_value.lower() not in valid_options:
                    # Пытаемся найти ближайшее совпадение
                    for opt in column.column_config["options"]:
                        if opt.get("label", "").lower() in cell_value.lower():
                            cell_value = opt.get("label", "")
                            break
            
            return {
                "file_id": file.id,
                "column_id": column.id,
                "cell_value": cell_value,
                "verbatim_extract": verbatim_extract,
                "reasoning": reasoning,
                "source_references": source_references,
                "confidence_score": confidence,
            }
            
        except Exception as e:
            logger.error(f"Error extracting cell value for file {file.id}, column {column.id}: {e}", exc_info=True)
            return {
                "file_id": file.id,
                "column_id": column.id,
                "cell_value": None,
                "error": str(e)
            }
    
    def _is_complex_question(self, prompt: str) -> bool:
        """Determine if question is complex and requires advanced reasoning"""
        complex_keywords = [
            "оцени", "проанализируй", "сравни", "найди все",
            "риски", "противоречия", "последствия", "прецеденты",
            "юридические", "правовые", "судебная практика", "анализ"
        ]
        prompt_lower = prompt.lower()
        return any(keyword in prompt_lower for keyword in complex_keywords)
    
    def _determine_extraction_strategy(
        self,
        file: File,
        column: TabularColumn
    ) -> str:
        """
        Determine optimal extraction strategy based on column type, question complexity, and document size
        
        Returns:
            Strategy name: 'simple', 'multi_query', 'compression', 'iterative', 'map_reduce'
        """
        """
        Strategy selection.

        NOTE: For tabular extraction quality we default to retrieval-first (RAG / hybrid search)
        and treat full-text local chunking as a fallback only (e.g., if the vector index is empty).
        """
        doc_length = len(file.original_text or "")
        is_complex = self._is_complex_question(column.prompt)

        # Always prefer RAG/hybrid retrieval as the default path.
        # For very large/complex documents, allow stronger retrieval strategies.
        if column.column_type in ['text', 'verbatim'] and is_complex and doc_length > 20000:
            return 'iterative'
        if column.column_type in ['text', 'verbatim'] and doc_length > 50000:
            return 'compression'

        return 'hybrid'
    
    def _detect_conflicts(
        self,
        candidates: List[TabularCellExtractionModel],
        column_type: str
    ) -> bool:
        """
        Detect conflicts between candidate values
        
        Args:
            candidates: List of extraction results
            column_type: Type of column (date, currency, number, text, etc.)
        
        Returns:
            True if conflicts detected, False otherwise
        """
        if len(candidates) < 2:
            return False
        
        # Get normalized values for comparison
        normalized_values = []
        for candidate in candidates:
            # Use normalized_value if available, otherwise normalize cell_value
            norm_val = candidate.normalized_value
            if not norm_val and candidate.cell_value:
                # Try to normalize on the fly
                if column_type == 'date':
                    from app.services.tabular_extraction_policy import is_na_cell_value
                    if is_na_cell_value(candidate.cell_value):
                        norm_val = "n/a"
                    else:
                        try:
                            from app.services.date_validator import parse_and_normalize_date
                            norm_val = parse_and_normalize_date(candidate.cell_value)
                        except Exception:
                            norm_val = candidate.cell_value.strip().lower()
                elif column_type in ['currency', 'number']:
                    try:
                        norm_val = candidate.cell_value.replace(' ', '').replace(',', '.')
                        float(norm_val)  # Validate it's a number
                    except:
                        norm_val = candidate.cell_value.strip().lower()
                elif column_type == 'yes_no':
                    from app.services.tabular_review_models import (
                        YES_NO_UNKNOWN,
                        validate_yes_no,
                        yes_no_normalized_key,
                    )
                    validated = validate_yes_no(candidate.cell_value or "")
                    norm_val = (
                        yes_no_normalized_key(validated)
                        if validated != YES_NO_UNKNOWN
                        else candidate.cell_value.strip().lower()
                    )
                else:
                    # For text, use lowercase for comparison
                    norm_val = candidate.cell_value.strip().lower()
            
            if norm_val and norm_val not in ['n/a', 'none', '']:
                normalized_values.append(norm_val)
        
        if len(normalized_values) < 2:
            return False
        
        # Check for conflicts
        if column_type in ['date', 'currency', 'number', 'yes_no']:
            # For structured types, exact comparison
            unique_values = set(normalized_values)
            return len(unique_values) > 1
        else:
            # For text, use semantic similarity (simple approach: check if values are significantly different)
            # For now, use simple string comparison - can be enhanced with embeddings later
            unique_values = set(normalized_values)
            if len(unique_values) == 1:
                return False
            
            # Check if values are substantially different (not just whitespace/formatting)
            first_val = normalized_values[0]
            for val in normalized_values[1:]:
                # Remove common punctuation and whitespace for comparison
                first_clean = re.sub(r'[^\w]', '', first_val)
                val_clean = re.sub(r'[^\w]', '', val)
                if first_clean != val_clean and abs(len(first_clean) - len(val_clean)) > len(first_clean) * 0.3:
                    return True
            
            return False

    def _build_cell_extraction_response(
        self,
        *,
        file: File,
        column: TabularColumn,
        result: TabularCellExtractionModel,
        included_docs: Optional[List[Document]] = None,
        verification_outcome=None,
    ) -> Dict[str, Any]:
        """Map extraction model to DB payload (provenance + status gates)."""
        return build_tabular_cell_db_payload(
            file=file,
            column=column,
            result=result,
            included_docs=included_docs,
            db=self.db,
            verification_outcome=verification_outcome,
        )
    
    def _tabular_pipeline_error_response(
        self,
        *,
        file: File,
        column: TabularColumn,
        error: str,
        log_level: str = "error",
    ) -> Dict[str, Any]:
        log_fn = logger.warning if log_level == "warning" else logger.error
        log_fn(
            "Tabular pipeline failed for file %s column %s: %s",
            file.id,
            column.id,
            error,
        )
        return {
            "file_id": file.id,
            "column_id": column.id,
            "cell_value": None,
            "error": error,
        }

    async def extract_cell_value_improved(
        self,
        file: File,
        column: TabularColumn,
        strategy: str = 'multi_query',
        rag_service=None,
        column_run=None,
    ) -> Dict[str, Any]:
        """
        Canonical tabular cell pipeline: assistant RAG → structured extract → verify → payload.

        strategy is retained for API compatibility; retrieval uses case-assistant hybrid funnel.
        """
        if not self.llm:
            return self._tabular_pipeline_error_response(
                file=file,
                column=column,
                error="LLM not configured",
            )

        if rag_service is None:
            from app.services.rag_service import get_rag_service

            rag_service = get_rag_service()

        try:
            pipeline = await run_tabular_cell_extraction(
                self.llm,
                rag_service=rag_service,
                file=file,
                column=column,
                normalize_fn=self._normalize_extraction_result,
                column_run=column_run,
            )

            logger.info(
                "Tabular pipeline file=%s column=%s recall=%s context_docs=%s forced_na=%s review=%s",
                file.id,
                column.id,
                len(pipeline.prepared.file_chunks),
                len(pipeline.prepared.included_docs),
                pipeline.verification.forced_na,
                pipeline.verification.needs_review,
            )

            return self._build_cell_extraction_response(
                file=file,
                column=column,
                result=pipeline.extraction,
                included_docs=pipeline.prepared.included_docs,
                verification_outcome=pipeline.verification,
            )

        except ValueError as err:
            code = str(err)
            if code == "No text content":
                return self._tabular_pipeline_error_response(
                    file=file,
                    column=column,
                    error="No text content",
                    log_level="warning",
                )
            if code == "No chunks available for extraction":
                return self._tabular_pipeline_error_response(
                    file=file,
                    column=column,
                    error="No chunks available for extraction",
                    log_level="warning",
                )
            if code == "empty_context":
                return self._tabular_pipeline_error_response(
                    file=file,
                    column=column,
                    error="Empty RAG context",
                    log_level="warning",
                )
            raise

        except Exception as e:
            logger.error(
                "Tabular pipeline failed for file %s column %s: %s",
                file.id,
                column.id,
                e,
                exc_info=True,
            )
            return self._tabular_pipeline_error_response(
                file=file,
                column=column,
                error=str(e),
            )

    async def extract_cell_value_smart(
        self,
        file: File,
        column: TabularColumn,
        rag_service=None,
        column_run=None,
    ) -> Dict[str, Any]:
        """
        Smart extraction with automatic strategy selection
        
        Determines optimal strategy and uses it for extraction
        """
        strategy = self._determine_extraction_strategy(file, column)
        logger.debug(f"Using extraction strategy '{strategy}' for file {file.id}, column {column.id}")
        return await self.extract_cell_value_improved(
            file,
            column,
            strategy=strategy,
            rag_service=rag_service,
            column_run=column_run,
        )

    async def extract_workflow_tabular_step(
        self,
        *,
        case_id: str,
        file_ids: List[str],
        columns: List[Dict[str, Any]],
        confidence_threshold: float = 0.8,
        rag_service=None,
    ) -> Dict[str, Any]:
        """
        Ad-hoc tabular extraction for WorkflowGraph steps (no LangGraph duplicate).

        Uses the same retrieve → extract → verify pipeline as TabularReviewPage.
        """
        from types import SimpleNamespace

        from app.services.tabular_extraction_policy import is_na_cell_value

        if rag_service is None:
            from app.services.rag_service import get_rag_service

            rag_service = get_rag_service()

        col_objs = [
            SimpleNamespace(
                id=str(col["id"]),
                column_label=col.get("label", col["id"]),
                column_type=col.get("type", col.get("column_type", "text")),
                prompt=col.get("prompt", f"Извлеки {col.get('label', col['id'])}"),
                column_config=col.get("config") or col.get("column_config"),
            )
            for col in columns
        ]

        files = (
            self.db.query(File)
            .filter(File.case_id == case_id, File.id.in_(file_ids))
            .all()
        )
        file_by_id = {f.id: f for f in files}

        pairs: List[tuple[File, Any]] = []
        for file_id in file_ids:
            file = file_by_id.get(file_id)
            if not file:
                continue
            for col in col_objs:
                pairs.append((file, col))

        async def _one(file: File, col) -> Dict[str, Any]:
            return await self.extract_cell_value_smart(file, col, rag_service=rag_service)

        raw_results = await asyncio.gather(
            *[_one(f, c) for f, c in pairs],
            return_exceptions=True,
        )

        successful: List[Dict[str, Any]] = []
        needs_clarification: List[Dict[str, Any]] = []

        for (file, col), raw in zip(pairs, raw_results):
            if isinstance(raw, Exception) or raw.get("error"):
                err = str(raw) if isinstance(raw, Exception) else raw.get("error")
                needs_clarification.append(
                    {
                        "column_id": col.id,
                        "file_id": file.id,
                        "value": "",
                        "confidence": 0.0,
                        "source_quote": None,
                        "source_page": None,
                        "needs_clarification": True,
                        "clarification_question": f"Ошибка извлечения '{col.column_label}': {err}",
                    }
                )
                continue

            value = raw.get("cell_value")
            confidence = float(raw.get("confidence_score") or 0.0)
            entry = {
                "column_id": col.id,
                "file_id": file.id,
                "value": value,
                "confidence": confidence,
                "source_quote": raw.get("verbatim_extract"),
                "source_page": raw.get("source_page"),
                "needs_clarification": False,
                "clarification_question": None,
            }

            if is_na_cell_value(value if value is None else str(value)):
                entry["needs_clarification"] = True
                entry["clarification_question"] = (
                    f"Значение для '{col.column_label}' не найдено в документе"
                )
                needs_clarification.append(entry)
            elif confidence < confidence_threshold or raw.get("status") == "pending":
                entry["needs_clarification"] = True
                entry["clarification_question"] = (
                    f"Проверьте значение для '{col.column_label}' "
                    f"(уверенность: {confidence:.0%})"
                )
                needs_clarification.append(entry)
            else:
                successful.append(entry)

        total = len(pairs)
        return {
            "successful": successful,
            "needs_clarification": needs_clarification,
            "total_cells": total,
            "success_rate": len(successful) / total if total else 0.0,
        }

    def upsert_tabular_cell_from_extraction(
        self,
        review_id: str,
        result: Dict[str, Any],
    ) -> TabularCell:
        """Persist one extraction result as a tabular cell (create or update)."""
        existing_cell = self.db.query(TabularCell).filter(
            and_(
                TabularCell.file_id == result["file_id"],
                TabularCell.column_id == result["column_id"],
            )
        ).first()

        source_refs = result.get("source_references", [])
        source_page = result.get("source_page")
        source_section = result.get("source_section")
        # Prefer explicit deep-link fields (improved pipeline), fall back to first source_reference.
        primary_source_doc_id = result.get("primary_source_doc_id") or result["file_id"]
        primary_source_char_start = result.get("primary_source_char_start")
        primary_source_char_end = result.get("primary_source_char_end")
        verified_flag = result.get("verified_flag")

        if source_refs and isinstance(source_refs, list) and len(source_refs) > 0:
            first_ref = source_refs[0]
            if isinstance(first_ref, dict):
                source_page = first_ref.get("page") or source_page
                source_section = first_ref.get("section") or source_section
                if primary_source_char_start is None:
                    primary_source_char_start = first_ref.get("char_start") or first_ref.get("start_char")
                if primary_source_char_end is None:
                    primary_source_char_end = first_ref.get("char_end") or first_ref.get("end_char")
                if not result.get("primary_source_doc_id") and first_ref.get("doc_id"):
                    primary_source_doc_id = first_ref.get("doc_id")
                if verified_flag is None and "verified" in first_ref:
                    verified_flag = first_ref.get("verified")

        if existing_cell:
            existing_cell.cell_value = result.get("cell_value")
            existing_cell.normalized_value = result.get("normalized_value")
            existing_cell.verbatim_extract = result.get("verbatim_extract")
            existing_cell.reasoning = result.get("reasoning")
            existing_cell.source_references = result.get("source_references")
            existing_cell.confidence_score = result.get("confidence_score")
            existing_cell.candidates = result.get("candidates")
            existing_cell.source_page = source_page
            existing_cell.source_section = source_section
            existing_cell.primary_source_doc_id = primary_source_doc_id
            existing_cell.primary_source_char_start = primary_source_char_start
            existing_cell.primary_source_char_end = primary_source_char_end
            existing_cell.verified_flag = verified_flag
            existing_cell.status = result.get("status", "completed")
            existing_cell.updated_at = datetime.utcnow()
            return existing_cell

        cell = TabularCell(
            tabular_review_id=review_id,
            file_id=result["file_id"],
            column_id=result["column_id"],
            cell_value=result.get("cell_value"),
            normalized_value=result.get("normalized_value"),
            verbatim_extract=result.get("verbatim_extract"),
            reasoning=result.get("reasoning"),
            source_references=result.get("source_references"),
            confidence_score=result.get("confidence_score"),
            source_page=source_page,
            source_section=source_section,
            status=result.get("status", "completed"),
            candidates=result.get("candidates"),
            primary_source_doc_id=primary_source_doc_id,
            primary_source_char_start=primary_source_char_start,
            primary_source_char_end=primary_source_char_end,
            verified_flag=verified_flag,
        )
        self.db.add(cell)
        return cell

    async def _broadcast_tabular_cell_saved(
        self,
        review_id: str,
        cell: TabularCell,
        result: Dict[str, Any],
    ) -> None:
        from app.services.websocket_manager import websocket_manager

        await websocket_manager.broadcast_cell_update(
            review_id,
            cell_result_to_websocket_payload(cell.id, result),
        )

    async def _broadcast_tabular_extraction_cell_finished(
        self,
        review_id: str,
        *,
        column_id: str,
        file_id: str,
        success: bool,
    ) -> None:
        from app.services.websocket_manager import websocket_manager

        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "extraction_cell_finished",
                "column_id": column_id,
                "file_id": file_id,
                "success": success,
            },
        )

    async def _extract_single_column_cell(
        self,
        file: File,
        column: TabularColumn,
        rag_service,
        column_run=None,
    ) -> TabularColumnExtractionOutcome:
        """Run one cell extraction; always returns file_id (never raises to caller)."""
        try:
            result = await self.extract_cell_value_smart(
                file,
                column,
                rag_service=rag_service,
                column_run=column_run,
            )
            return TabularColumnExtractionOutcome.from_result(file.id, result)
        except Exception as exc:
            logger.error(
                "Extraction task failed for file %s column %s: %s",
                file.id,
                column.id,
                exc,
                exc_info=True,
            )
            return TabularColumnExtractionOutcome.from_exception(file.id, exc)

    async def _broadcast_column_extraction_progress(
        self,
        review_id: str,
        *,
        column_id: str,
        finished_count: int,
        total_tasks: int,
        saved_count: int,
        error_count: int,
    ) -> None:
        from app.services.websocket_manager import websocket_manager

        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "extraction_progress",
                "progress": {
                    "column_id": column_id,
                    "progress": finished_count,
                    "total": total_tasks,
                    "saved_count": saved_count,
                    "error_count": error_count,
                },
            },
        )

    async def _broadcast_column_extraction_completed(
        self,
        review_id: str,
        *,
        column_id: str,
        status: str,
        saved_count: int,
        filled_count: int,
        error_count: int,
        total_tasks: int,
        message: Optional[str] = None,
    ) -> None:
        from app.services.websocket_manager import websocket_manager

        await websocket_manager.broadcast_to_review(
            review_id,
            {
                "type": "column_extraction_completed",
                "column_id": column_id,
                "status": status,
                "saved_count": saved_count,
                "filled_count": filled_count,
                "error_count": error_count,
                "total_tasks": total_tasks,
                "message": message,
            },
        )

    async def _apply_column_extraction_outcome(
        self,
        review_id: str,
        column_id: str,
        outcome: TabularColumnExtractionOutcome,
        *,
        finished_count: int,
        total_tasks: int,
        saved_count: int,
        error_count: int,
    ) -> tuple[int, int, Optional[Dict[str, Any]]]:
        """
        Persist one outcome, notify clients, return updated (saved_count, error_count, api_payload?).
        """
        if not outcome.succeeded or outcome.result is None:
            error_count += 1
            if outcome.error:
                logger.warning(
                    "Extraction error for file %s column %s: %s",
                    outcome.file_id,
                    column_id,
                    outcome.error,
                )
            await self._broadcast_tabular_extraction_cell_finished(
                review_id,
                column_id=column_id,
                file_id=outcome.file_id,
                success=False,
            )
            await self._broadcast_column_extraction_progress(
                review_id,
                column_id=column_id,
                finished_count=finished_count,
                total_tasks=total_tasks,
                saved_count=saved_count,
                error_count=error_count,
            )
            return saved_count, error_count, None

        result = outcome.result
        cell = self.upsert_tabular_cell_from_extraction(review_id, result)
        self.db.commit()
        self.db.refresh(cell)

        payload = cell_result_to_api_payload(result)
        saved_count += 1

        await self._broadcast_tabular_cell_saved(review_id, cell, result)
        await self._broadcast_tabular_extraction_cell_finished(
            review_id,
            column_id=column_id,
            file_id=outcome.file_id,
            success=True,
        )
        await self._broadcast_column_extraction_progress(
            review_id,
            column_id=column_id,
            finished_count=finished_count,
            total_tasks=total_tasks,
            saved_count=saved_count,
            error_count=error_count,
        )
        return saved_count, error_count, payload
    
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
            file_ids = review.selected_file_ids if review.selected_file_ids else None
            files = fetch_files_for_extraction(self.db, review.case_id, file_ids)

            # Get columns
            columns = self.db.query(TabularColumn).filter(
                TabularColumn.tabular_review_id == review_id
            ).order_by(TabularColumn.order_index).all()
            
            if not files:
                raise ValueError("No files found for this case")
            
            if not columns:
                raise ValueError("No columns defined for this review")

            from app.services.rag_service import get_rag_service
            from app.services.document_processor import get_document_processor
            from app.services.bm25_case_prewarm import prepare_bm25_for_tabular_extraction

            rag_service = get_rag_service()
            document_processor = get_document_processor()
            prepare_bm25_for_tabular_extraction(document_processor, review.case_id)

            tasks = [
                self.extract_cell_value_smart(file, column, rag_service=rag_service)
                for file in files
                for column in columns
            ]
            
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

                # Canonical persistence path (keeps deep-link + provenance fields consistent).
                self.upsert_tabular_cell_from_extraction(review_id, result)
                saved_count += 1
            
            self.db.commit()

            try:
                self._refresh_review_queue(review_id)
            except Exception as e:
                logger.warning(
                    "Failed to build review queue for review %s: %s",
                    review_id,
                    e,
                    exc_info=True,
                )
            
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

    def _refresh_review_queue(self, review_id: str) -> int:
        """Rebuild unreviewed queue items after extraction (idempotent)."""
        from app.models.tabular_review import ReviewQueueItem
        from app.services.review_queue_service import ReviewQueueService

        queue_service = ReviewQueueService(self.db)
        queue_items = queue_service.build_review_queue(review_id)

        self.db.query(ReviewQueueItem).filter(
            and_(
                ReviewQueueItem.tabular_review_id == review_id,
                ReviewQueueItem.is_reviewed == False,
            )
        ).delete()

        for item in queue_items:
            self.db.add(
                ReviewQueueItem(
                    tabular_review_id=item.review_id,
                    file_id=item.file_id,
                    column_id=item.column_id,
                    cell_id=item.cell_id,
                    priority=item.priority,
                    reason=item.reason,
                )
            )

        self.db.commit()
        logger.info("Review queue built: %s items for review %s", len(queue_items), review_id)
        return len(queue_items)
    
    def plan_column_extraction(
        self,
        review_id: str,
        column_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Validate column run and return metadata (no LLM work)."""
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()

        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")

        column = self.db.query(TabularColumn).filter(
            and_(
                TabularColumn.id == column_id,
                TabularColumn.tabular_review_id == review_id,
            )
        ).first()

        if not column:
            raise ValueError(f"Column {column_id} not found in review {review_id}")

        if column.column_type == "manual_input":
            return {
                "status": "skipped",
                "column_id": column_id,
                "total_tasks": 0,
            }

        file_ids = review.selected_file_ids if review.selected_file_ids else None
        files = fetch_files_for_extraction(self.db, review.case_id, file_ids)
        if not files:
            raise ValueError("No files found for this case")

        return {
            "status": "ready",
            "column_id": column_id,
            "total_tasks": len(files),
            "case_id": review.case_id,
        }

    async def _extract_single_column_cell_with_slot(
        self,
        file: File,
        column: TabularColumn,
        rag_service,
        column_run=None,
    ) -> TabularColumnExtractionOutcome:
        from app.services.tabular_extraction_runtime import tabular_cell_semaphore

        async with tabular_cell_semaphore():
            return await self._extract_single_column_cell(
                file,
                column,
                rag_service,
                column_run=column_run,
            )

    async def execute_column_extraction(
        self,
        review_id: str,
        column_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Run extraction for one column (bounded parallelism, WS updates)."""
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()

        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")

        column = self.db.query(TabularColumn).filter(
            and_(
                TabularColumn.id == column_id,
                TabularColumn.tabular_review_id == review_id,
            )
        ).first()

        if not column:
            raise ValueError(f"Column {column_id} not found in review {review_id}")

        if column.column_type == "manual_input":
            result = {
                "status": "skipped",
                "saved_count": 0,
                "error_count": 0,
                "total_tasks": 0,
                "column_id": column_id,
                "cells": [],
            }
            await self._broadcast_column_extraction_completed(
                review_id,
                column_id=column_id,
                status="skipped",
                saved_count=0,
                filled_count=0,
                error_count=0,
                total_tasks=0,
            )
            return result

        file_ids = review.selected_file_ids if review.selected_file_ids else None
        files = fetch_files_for_extraction(self.db, review.case_id, file_ids)
        if not files:
            raise ValueError("No files found for this case")

        from app.services.rag_service import get_rag_service
        from app.services.document_processor import get_document_processor
        from app.services.bm25_case_prewarm import prepare_bm25_for_tabular_extraction
        from app.services.tabular_cell_pipeline import tabular_rerank_enabled
        from app.services.tabular_extraction_runtime import tabular_max_parallel_cells

        rag_service = get_rag_service()
        document_processor = get_document_processor()
        bm25_ok = prepare_bm25_for_tabular_extraction(document_processor, review.case_id)

        from app.services.tabular_column_run_context import prepare_tabular_column_run_context

        try:
            column_run = await asyncio.to_thread(prepare_tabular_column_run_context, column)
        except ValueError as exc:
            if str(exc) == "empty_query":
                raise ValueError("Column prompt is required for extraction") from exc
            raise
        except RuntimeError as exc:
            raise ValueError(f"Query embedding failed: {exc}") from exc

        logger.info(
            "Tabular column extraction: column=%s files=%s bm25_ready=%s rerank=%s parallel=%s embed_once=true",
            column_id,
            len(files),
            bm25_ok,
            tabular_rerank_enabled(),
            tabular_max_parallel_cells(),
        )

        extraction_tasks = [
            asyncio.create_task(
                self._extract_single_column_cell_with_slot(
                    file,
                    column,
                    rag_service,
                    column_run,
                )
            )
            for file in files
        ]

        logger.info(
            "Starting column extraction %s: %s tasks (max %s concurrent)",
            column_id,
            len(extraction_tasks),
            tabular_max_parallel_cells(),
        )

        saved_count = 0
        error_count = 0
        cells_payload: List[Dict[str, Any]] = []
        total_tasks = len(extraction_tasks)
        finished_count = 0

        for pending in asyncio.as_completed(extraction_tasks):
            outcome = await pending
            finished_count += 1
            saved_count, error_count, payload = await self._apply_column_extraction_outcome(
                review_id,
                column_id,
                outcome,
                finished_count=finished_count,
                total_tasks=total_tasks,
                saved_count=saved_count,
                error_count=error_count,
            )
            if payload is not None:
                cells_payload.append(payload)

        filled_count = count_nonempty_cells(cells_payload)
        logger.info(
            "Column extraction completed: %s cells saved, %s filled, %s errors",
            saved_count,
            filled_count,
            error_count,
        )

        try:
            self._refresh_review_queue(review_id)
        except Exception as queue_err:
            logger.warning(
                "Review queue refresh failed for review %s: %s",
                review_id,
                queue_err,
                exc_info=True,
            )

        result = {
            "status": "completed",
            "saved_count": saved_count,
            "filled_count": filled_count,
            "error_count": error_count,
            "total_tasks": total_tasks,
            "column_id": column_id,
            "cells": cells_payload,
        }
        await self._broadcast_column_extraction_completed(
            review_id,
            column_id=column_id,
            status="completed",
            saved_count=saved_count,
            filled_count=filled_count,
            error_count=error_count,
            total_tasks=total_tasks,
        )
        return result

    async def run_column_extraction(
        self,
        review_id: str,
        column_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Synchronous column run (tests / direct calls)."""
        self.plan_column_extraction(review_id, column_id, user_id)
        return await self.execute_column_extraction(review_id, column_id, user_id)
    
    def update_selected_files(
        self,
        review_id: str,
        file_ids: List[str],
        user_id: str
    ) -> TabularReview:
        """Update selected files for a tabular review"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Verify files belong to the case
        if file_ids:
            files = fetch_files_ids_only(self.db, review.case_id, file_ids)
            if len(files) != len(file_ids):
                raise ValueError("Some selected files do not belong to this case")
        
        review.selected_file_ids = file_ids if file_ids else None
        review.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(review)
        
        logger.info(f"Updated selected files for review {review_id}: {len(file_ids) if file_ids else 0} files")
        return review
    
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
    
    def update_cell(
        self,
        review_id: str,
        file_id: str,
        column_id: str,
        cell_value: str,
        user_id: str,
        is_manual_override: bool = True
    ) -> TabularCell:
        """Update a cell value (manual edit) by file_id and column_id"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Get or create the cell with atomic locking (SELECT FOR UPDATE)
        # Это предотвращает race conditions при одновременном редактировании
        try:
            cell = self.db.query(TabularCell).filter(
                and_(
                    TabularCell.tabular_review_id == review_id,
                    TabularCell.file_id == file_id,
                    TabularCell.column_id == column_id
                )
            ).with_for_update(nowait=True).first()  # nowait=True - сразу ошибка если заблокировано
        except Exception as lock_error:
            # Если не удалось получить блокировку (другой пользователь редактирует)
            from sqlalchemy.exc import OperationalError
            if isinstance(lock_error, OperationalError) and "could not obtain lock" in str(lock_error).lower():
                raise ValueError("Ячейка заблокирована другим пользователем. Попробуйте через несколько секунд.")
            # Для других ошибок - пробрасываем дальше
            raise
        
        # Save previous value for history
        previous_cell_value = cell.cell_value if cell else None
        change_type = "updated" if cell else "created"
        
        if not cell:
            # Create new cell if it doesn't exist
            cell = TabularCell(
                tabular_review_id=review_id,
                file_id=file_id,
                column_id=column_id,
                cell_value=cell_value,
                status="reviewed" if is_manual_override else "pending"
            )
            self.db.add(cell)
            self.db.flush()  # Flush to get the cell ID
        else:
            # Check if cell is locked by another user (атомарная проверка благодаря FOR UPDATE)
            if cell.locked_by and cell.locked_by != user_id:
                # Check if lock has expired
                if cell.lock_expires_at and cell.lock_expires_at > datetime.utcnow():
                    locked_user = self.db.query(User).filter(User.id == cell.locked_by).first()
                    locked_user_name = locked_user.name if locked_user else "Unknown"
                    raise ValueError(f"Ячейка заблокирована пользователем {locked_user_name}")
                # Lock has expired, allow update and unlock
                cell.locked_by = None
                cell.locked_at = None
                cell.lock_expires_at = None
            
            # Update existing cell
            cell.cell_value = cell_value
            cell.status = "reviewed" if is_manual_override else cell.status
            cell.updated_at = datetime.utcnow()
            # For manual edits, clear AI-related fields
            if is_manual_override:
                cell.verbatim_extract = None
                cell.reasoning = None
                cell.source_references = None
                cell.confidence_score = None
                cell.source_page = None
                cell.source_section = None
            
            # Unlock cell after update (if it was locked by this user)
            if cell.locked_by == user_id:
                cell.locked_by = None
                cell.locked_at = None
                cell.lock_expires_at = None
        
        self.db.commit()
        self.db.refresh(cell)
        
        # Log the change to history
        try:
            from app.services.cell_history_service import CellHistoryService
            history_service = CellHistoryService(self.db)
            history_service.log_cell_change(
                cell=cell,
                change_type=change_type,
                changed_by=user_id,
                previous_cell_value=previous_cell_value,
                change_reason="Manual edit" if is_manual_override else "Cell update"
            )
        except Exception as e:
            logger.warning(f"Failed to log cell history: {e}", exc_info=True)
            # Don't fail the update if history logging fails
        
        logger.info(f"Updated cell for file {file_id}, column {column_id} in review {review_id}")
        return cell
    
    def bulk_update_status(
        self,
        review_id: str,
        file_ids: List[str],
        status: str,
        user_id: str
    ) -> int:
        """Bulk update document status for multiple files"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        files = fetch_files_ids_only(self.db, review.case_id, file_ids)
        if len(files) != len(file_ids):
            raise ValueError("Some files do not belong to this case")
        
        updated_count = 0
        for file_id in file_ids:
            # Get or create document status
            doc_status = self.db.query(TabularDocumentStatus).filter(
                and_(
                    TabularDocumentStatus.tabular_review_id == review_id,
                    TabularDocumentStatus.file_id == file_id,
                    TabularDocumentStatus.user_id == user_id
                )
            ).first()
            
            if doc_status:
                doc_status.status = status
                doc_status.updated_at = datetime.utcnow()
            else:
                doc_status = TabularDocumentStatus(
                    tabular_review_id=review_id,
                    file_id=file_id,
                    user_id=user_id,
                    status=status
                )
                self.db.add(doc_status)
            
            updated_count += 1
        
        self.db.commit()
        logger.info(f"Bulk updated status for {updated_count} files in review {review_id}")
        return updated_count
    
    async def bulk_run_extraction(
        self,
        review_id: str,
        file_ids: List[str],
        column_ids: List[str],
        user_id: str
    ) -> Dict[str, Any]:
        """Bulk run extraction for specific files and columns"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        files = fetch_files_for_extraction(self.db, review.case_id, file_ids)
        if len(files) != len(file_ids):
            raise ValueError("Some files do not belong to this case")
        
        # Get columns
        columns = self.db.query(TabularColumn).filter(
            and_(
                TabularColumn.tabular_review_id == review_id,
                TabularColumn.id.in_(column_ids)
            )
        ).all()
        
        if len(columns) != len(column_ids):
            raise ValueError("Some columns do not belong to this review")

        from app.services.rag_service import get_rag_service
        from app.services.document_processor import get_document_processor
        from app.services.bm25_case_prewarm import prepare_bm25_for_tabular_extraction

        rag_service = get_rag_service()
        document_processor = get_document_processor()
        prepare_bm25_for_tabular_extraction(document_processor, review.case_id)

        # Create tasks for parallel processing
        tasks = [
            self.extract_cell_value_smart(file, column, rag_service=rag_service)
            for file in files
            for column in columns
        ]
        
        # Execute tasks in parallel
        logger.info(f"Starting bulk extraction: {len(tasks)} tasks for {len(file_ids)} files, {len(column_ids)} columns")
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

            self.upsert_tabular_cell_from_extraction(review_id, result)
            saved_count += 1
        
        self.db.commit()
        
        logger.info(f"Bulk extraction completed: {saved_count} cells saved, {error_count} errors")
        
        return {
            "status": "completed",
            "saved_count": saved_count,
            "error_count": error_count,
            "total_tasks": len(tasks),
            "files_processed": len(file_ids),
            "columns_processed": len(column_ids)
        }
    
    def bulk_delete_rows(
        self,
        review_id: str,
        file_ids: List[str],
        user_id: str
    ) -> int:
        """Bulk delete rows (remove files from selected_file_ids)"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Update selected_file_ids to remove deleted files
        if review.selected_file_ids:
            updated_file_ids = [fid for fid in review.selected_file_ids if fid not in file_ids]
            review.selected_file_ids = updated_file_ids if updated_file_ids else None
        else:
            # If no selected_file_ids, all files are included, so we can't "delete" them
            # Instead, we'll set selected_file_ids to exclude these files
            # Get all files for the case
            all_file_ids = [
                f.id for f in fetch_files_for_table(self.db, review.case_id)
            ]
            updated_file_ids = [fid for fid in all_file_ids if fid not in file_ids]
            review.selected_file_ids = updated_file_ids if updated_file_ids else None
        
        # Delete cells for these files (cascade should handle this, but explicit for clarity)
        deleted_cells = self.db.query(TabularCell).filter(
            and_(
                TabularCell.tabular_review_id == review_id,
                TabularCell.file_id.in_(file_ids)
            )
        ).delete(synchronize_session=False)
        
        # Delete document statuses for these files
        deleted_statuses = self.db.query(TabularDocumentStatus).filter(
            and_(
                TabularDocumentStatus.tabular_review_id == review_id,
                TabularDocumentStatus.file_id.in_(file_ids)
            )
        ).delete(synchronize_session=False)
        
        review.updated_at = datetime.utcnow()
        self.db.commit()
        
        logger.info(f"Bulk deleted {len(file_ids)} rows from review {review_id} (removed {deleted_cells} cells, {deleted_statuses} statuses)")
        return len(file_ids)
    
    @staticmethod
    def _clean_export_value(raw: str | None) -> str:
        """Parse cell_value that may be a raw JSON string from the LLM."""
        if not raw:
            return ""
        v = raw.strip()
        # Try JSON parse first
        if v.startswith("{"):
            try:
                parsed = json.loads(v)
                v = parsed.get("cell_value", "") or ""
            except Exception:
                m = re.search(r'"cell_value"\s*:\s*"([^"]*)"', v)
                v = m.group(1) if m else ""
        # Normalize blanks
        stripped = v.strip()
        if not stripped or stripped.upper() in ("N/A", "НЕТ ДАННЫХ", "ОТСУТСТВУЕТ", "НЕ УКАЗАНО", "-", "—", "–"):
            return ""
        if re.match(r'^[_\-\.\s]+$', stripped):
            return ""
        if re.search(r'_{2,}', stripped):   # unfilled template blanks like «___» ____20__г.
            return ""
        return stripped

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
                csv_row.append(self._clean_export_value(cell.get("cell_value")))
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
                    ws.cell(row=row_num, column=col_num, value=self._clean_export_value(cell.get("cell_value")))
            
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
    
    def export_to_word(self, review_id: str, user_id: str) -> bytes:
        """Export tabular review to Word (.docx) format"""
        from docx import Document
        from docx.shared import Pt, Inches
        from docx.oxml.ns import qn
        import io

        data = self.get_table_data(review_id, user_id)
        columns = data["columns"]
        rows = data["rows"]

        doc = Document()

        # Title
        doc.add_heading(data["review"]["name"], level=1)

        # Table: 1 header row + data rows, 1 col for doc name + columns
        num_cols = len(columns) + 1
        num_rows = len(rows) + 1

        table = doc.add_table(rows=num_rows, cols=num_cols)
        table.style = "Table Grid"

        # Header row
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = "Document"
        for i, col in enumerate(columns):
            hdr_cells[i + 1].text = col["column_label"]

        # Bold header cells
        for cell in hdr_cells:
            for para in cell.paragraphs:
                for run in para.runs:
                    run.bold = True
                    run.font.size = Pt(10)

        # Data rows
        for row_idx, row in enumerate(rows, start=1):
            row_cells = table.rows[row_idx].cells
            row_cells[0].text = row["file_name"]
            for col_idx, col in enumerate(columns):
                cell_data = row["cells"].get(col["id"], {})
                row_cells[col_idx + 1].text = cell_data.get("cell_value") or ""

        # Set narrow column widths so table fits on page
        col_width = Inches(1.5)
        for row in table.rows:
            for cell in row.cells:
                cell.width = col_width

        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        return output.read()

    def create_timeline_table_from_results(
        self,
        case_id: str,
        user_id: str,
        name: str = "Хронология событий"
    ) -> TabularReview:
        """Создает таблицу из результатов Timeline агента"""
        from app.models.analysis import TimelineEvent
        
        # Get timeline events
        events = self.db.query(TimelineEvent).filter(
            TimelineEvent.case_id == case_id
        ).order_by(TimelineEvent.date).all()
        
        if not events:
            raise ValueError("No timeline events found for this case")
        
        # Create review
        review = self.create_tabular_review(
            case_id=case_id,
            user_id=user_id,
            name=name,
            description="Автоматически созданная таблица из хронологии событий"
        )
        
        # Add columns
        self.add_column(
            review_id=review.id,
            column_label="Дата",
            column_type="date",
            prompt="Дата события",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Тип события",
            column_type="text",
            prompt="Тип события",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Описание",
            column_type="text",
            prompt="Описание события",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Источник",
            column_type="text",
            prompt="Документ-источник",
            user_id=user_id
        )
        
        # Get files for events
        from app.models.case import File
        files_dict = {}
        for event in events:
            source_doc = event.source_document
            if source_doc and source_doc not in files_dict:
                file = self.db.query(File).filter(
                    File.case_id == case_id,
                    File.filename == source_doc
                ).first()
                if file:
                    files_dict[source_doc] = file
        
        # Create cells from events
        for event in events:
            file = files_dict.get(event.source_document)
            if not file:
                continue
            
            # Date cell
            cell_date = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[0].id,
                cell_value=event.date.strftime("%Y-%m-%d") if event.date else "",
                confidence_score=0.9
            )
            self.db.add(cell_date)
            
            # Event type cell
            cell_type = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[1].id,
                cell_value=event.event_type or "",
                confidence_score=0.9
            )
            self.db.add(cell_type)
            
            # Description cell
            cell_desc = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[2].id,
                cell_value=event.description,
                confidence_score=0.9
            )
            self.db.add(cell_desc)
            
            # Source cell
            cell_source = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[3].id,
                cell_value=event.source_document,
                confidence_score=1.0
            )
            self.db.add(cell_source)
        
        self.db.commit()
        logger.info(f"Created timeline table {review.id} with {len(events)} events")
        return review
    
    def create_entities_table_from_results(
        self,
        case_id: str,
        user_id: str,
        name: str = "Извлеченные сущности"
    ) -> TabularReview:
        """Создает таблицу из результатов Entity Extraction агента"""
        from app.models.analysis import ExtractedEntity
        
        # Get entities
        entities = self.db.query(ExtractedEntity).filter(
            ExtractedEntity.case_id == case_id
        ).all()
        
        if not entities:
            raise ValueError("No entities found for this case")
        
        # Create review
        review = self.create_tabular_review(
            case_id=case_id,
            user_id=user_id,
            name=name,
            description="Автоматически созданная таблица из извлеченных сущностей"
        )
        
        # Add columns
        self.add_column(
            review_id=review.id,
            column_label="Сущность",
            column_type="text",
            prompt="Название сущности",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Тип",
            column_type="text",
            prompt="Тип сущности (PERSON, ORG, etc.)",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Контекст",
            column_type="text",
            prompt="Контекст, в котором найдена сущность",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Источник",
            column_type="text",
            prompt="Документ-источник",
            user_id=user_id
        )
        
        # Get files for entities
        from app.models.case import File
        files_dict = {}
        for entity in entities:
            if entity.file_id and entity.file_id not in files_dict:
                file = self.db.query(File).filter(File.id == entity.file_id).first()
                if file:
                    files_dict[entity.file_id] = file
        
        # Create cells from entities
        for entity in entities:
            file = files_dict.get(entity.file_id) if entity.file_id else None
            if not file:
                continue
            
            # Entity text cell
            cell_entity = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[0].id,
                cell_value=entity.entity_text,
                confidence_score=float(entity.confidence) if entity.confidence else 0.8
            )
            self.db.add(cell_entity)
            
            # Entity type cell
            cell_type = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[1].id,
                cell_value=entity.entity_type,
                confidence_score=0.9
            )
            self.db.add(cell_type)
            
            # Context cell
            cell_context = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[2].id,
                cell_value=entity.context or "",
                confidence_score=0.8
            )
            self.db.add(cell_context)
            
            # Source cell
            cell_source = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[3].id,
                cell_value=entity.source_document or file.name,
                confidence_score=1.0
            )
            self.db.add(cell_source)
        
        self.db.commit()
        logger.info(f"Created entities table {review.id} with {len(entities)} entities")
        return review
    
    def create_discrepancies_table_from_results(
        self,
        case_id: str,
        user_id: str,
        name: str = "Найденные противоречия"
    ) -> TabularReview:
        """Создает таблицу из результатов Discrepancy агента"""
        from app.models.analysis import Discrepancy
        
        # Get discrepancies
        discrepancies = self.db.query(Discrepancy).filter(
            Discrepancy.case_id == case_id
        ).all()
        
        if not discrepancies:
            raise ValueError("No discrepancies found for this case")
        
        # Create review
        review = self.create_tabular_review(
            case_id=case_id,
            user_id=user_id,
            name=name,
            description="Автоматически созданная таблица из найденных противоречий"
        )
        
        # Add columns
        self.add_column(
            review_id=review.id,
            column_label="Тип противоречия",
            column_type="text",
            prompt="Тип противоречия",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Серьезность",
            column_type="text",
            prompt="Уровень серьезности (HIGH, MEDIUM, LOW)",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Описание",
            column_type="text",
            prompt="Описание противоречия",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Документы",
            column_type="text",
            prompt="Документы с противоречиями",
            user_id=user_id
        )
        
        # Get files
        from app.models.case import File
        files = self.db.query(File).filter(File.case_id == case_id).all()
        if not files:
            raise ValueError("No files found for this case")
        
        # Create cells from discrepancies
        # Check for existing cells to avoid duplicates
        from app.models.tabular_review import TabularCell
        
        for disc in discrepancies:
            # Use first file as placeholder (discrepancies don't have direct file_id)
            file = files[0]
            
            # Helper function to check and create cell
            def get_or_create_cell(column_idx, value, confidence=0.9):
                column_id = review.columns[column_idx].id
                # Check if cell already exists
                existing = self.db.query(TabularCell).filter(
                    TabularCell.tabular_review_id == review.id,
                    TabularCell.file_id == file.id,
                    TabularCell.column_id == column_id
                ).first()
                
                if existing:
                    # Update existing cell
                    existing.cell_value = value
                    existing.confidence_score = confidence
                    return existing
                else:
                    # Create new cell
                    return TabularCell(
                        tabular_review_id=review.id,
                        file_id=file.id,
                        column_id=column_id,
                        cell_value=value,
                        confidence_score=confidence
                    )
            
            # Type cell
            cell_type = get_or_create_cell(0, disc.type, 0.9)
            if not self.db.is_modified(cell_type, include_collections=False) and cell_type not in self.db.new:
                self.db.add(cell_type)
            
            # Severity cell
            cell_severity = get_or_create_cell(1, disc.severity, 0.9)
            if not self.db.is_modified(cell_severity, include_collections=False) and cell_severity not in self.db.new:
                self.db.add(cell_severity)
            
            # Description cell
            cell_desc = get_or_create_cell(2, disc.description, 0.9)
            if not self.db.is_modified(cell_desc, include_collections=False) and cell_desc not in self.db.new:
                self.db.add(cell_desc)
            
            # Documents cell
            source_docs = disc.source_documents
            if isinstance(source_docs, list):
                docs_str = ", ".join(source_docs)
            else:
                docs_str = str(source_docs)
            
            cell_docs = get_or_create_cell(3, docs_str, 1.0)
            if not self.db.is_modified(cell_docs, include_collections=False) and cell_docs not in self.db.new:
                self.db.add(cell_docs)
        
        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise
        logger.info(f"Created discrepancies table {review.id} with {len(discrepancies)} discrepancies")
        return review
    
    def create_risks_table_from_results(
        self,
        case_id: str,
        user_id: str,
        name: str = "Выявленные риски"
    ) -> TabularReview:
        """Создает таблицу из результатов Risk агента"""
        from app.models.analysis import Risk
        
        # Get risks
        risks = self.db.query(Risk).filter(
            Risk.case_id == case_id
        ).all()
        
        if not risks:
            raise ValueError("No risks found for this case")
        
        # Create review
        review = self.create_tabular_review(
            case_id=case_id,
            user_id=user_id,
            name=name,
            description="Автоматически созданная таблица из выявленных рисков"
        )
        
        # Add columns
        self.add_column(
            review_id=review.id,
            column_label="Название риска",
            column_type="text",
            prompt="Название риска",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Категория",
            column_type="text",
            prompt="Категория риска",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Вероятность",
            column_type="text",
            prompt="Вероятность (HIGH, MEDIUM, LOW)",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Влияние",
            column_type="text",
            prompt="Влияние (HIGH, MEDIUM, LOW)",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Описание",
            column_type="text",
            prompt="Описание риска",
            user_id=user_id
        )
        
        # Get files
        from app.models.case import File
        files = self.db.query(File).filter(File.case_id == case_id).all()
        if not files:
            raise ValueError("No files found for this case")
        
        # Create cells from risks
        for risk in risks:
            # Use first file as placeholder
            file = files[0]
            
            # Name cell
            cell_name = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[0].id,
                cell_value=risk.risk_name,
                confidence_score=0.9
            )
            self.db.add(cell_name)
            
            # Category cell
            cell_category = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[1].id,
                cell_value=risk.risk_category,
                confidence_score=0.9
            )
            self.db.add(cell_category)
            
            # Probability cell
            cell_prob = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[2].id,
                cell_value=risk.probability,
                confidence_score=0.9
            )
            self.db.add(cell_prob)
            
            # Impact cell
            cell_impact = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[3].id,
                cell_value=risk.impact,
                confidence_score=0.9
            )
            self.db.add(cell_impact)
            
            # Description cell
            cell_desc = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[4].id,
                cell_value=risk.description,
                confidence_score=0.9
            )
            self.db.add(cell_desc)
        
        self.db.commit()
        logger.info(f"Created risks table {review.id} with {len(risks)} risks")
        return review

    def create_key_facts_table_from_results(
        self,
        case_id: str,
        user_id: str,
        name: str = "Ключевые факты"
    ) -> TabularReview:
        """Создает таблицу из результатов Key Facts агента"""
        from app.models.analysis import AnalysisResult
        
        # Get key_facts from AnalysisResult
        key_facts_result = self.db.query(AnalysisResult).filter(
            AnalysisResult.case_id == case_id,
            AnalysisResult.analysis_type == "key_facts"
        ).order_by(AnalysisResult.created_at.desc()).first()
        
        if not key_facts_result or not key_facts_result.result_data:
            raise ValueError("No key_facts found for this case")
        
        result_data = key_facts_result.result_data
        
        # Create review
        review = self.create_tabular_review(
            case_id=case_id,
            user_id=user_id,
            name=name,
            description="Автоматически созданная таблица из ключевых фактов"
        )
        
        # Add columns based on key_facts structure
        # Обычно key_facts содержит: parties, amounts, dates, key_terms, etc.
        self.add_column(
            review_id=review.id,
            column_label="Категория",
            column_type="text",
            prompt="Категория факта",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Значение",
            column_type="text",
            prompt="Значение факта",
            user_id=user_id
        )
        
        self.add_column(
            review_id=review.id,
            column_label="Описание",
            column_type="text",
            prompt="Описание факта",
            user_id=user_id
        )
        
        # Get files
        from app.models.case import File
        files = self.db.query(File).filter(File.case_id == case_id).all()
        if not files:
            raise ValueError("No files found for this case")
        
        # Use first file as placeholder (key_facts are case-level, not file-level)
        file = files[0]
        
        # Extract key facts from result_data
        facts_to_add = []
        
        # Parties
        if result_data.get("parties"):
            parties = result_data["parties"]
            if isinstance(parties, dict):
                for role, name in parties.items():
                    facts_to_add.append({
                        "category": f"Сторона: {role}",
                        "value": str(name),
                        "description": f"Сторона дела: {role}"
                    })
        
        # Amounts
        if result_data.get("amounts"):
            amounts = result_data["amounts"]
            if isinstance(amounts, dict):
                for key, value in amounts.items():
                    facts_to_add.append({
                        "category": f"Сумма: {key}",
                        "value": str(value),
                        "description": f"Финансовая информация: {key}"
                    })
        
        # Dates
        if result_data.get("dates"):
            dates = result_data["dates"]
            if isinstance(dates, dict):
                for key, value in dates.items():
                    facts_to_add.append({
                        "category": f"Дата: {key}",
                        "value": str(value),
                        "description": f"Важная дата: {key}"
                    })
        
        # Key terms
        if result_data.get("key_terms"):
            key_terms = result_data["key_terms"]
            if isinstance(key_terms, list):
                for term in key_terms:
                    facts_to_add.append({
                        "category": "Ключевой термин",
                        "value": str(term),
                        "description": "Важный термин из документов"
                    })
        
        # If no structured data, add summary
        if not facts_to_add and result_data.get("summary"):
            facts_to_add.append({
                "category": "Резюме",
                "value": result_data["summary"][:500],
                "description": "Общее резюме ключевых фактов"
            })
        
        # Create cells from facts
        for fact in facts_to_add:
            # Category cell
            cell_category = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[0].id,
                cell_value=fact["category"],
                confidence_score=0.9
            )
            self.db.add(cell_category)
            
            # Value cell
            cell_value = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[1].id,
                cell_value=fact["value"],
                confidence_score=0.9
            )
            self.db.add(cell_value)
            
            # Description cell
            cell_desc = TabularCell(
                tabular_review_id=review.id,
                file_id=file.id,
                column_id=review.columns[2].id,
                cell_value=fact["description"],
                confidence_score=0.9
            )
            self.db.add(cell_desc)
        
        self.db.commit()
        logger.info(f"Created key_facts table {review.id} with {len(facts_to_add)} facts")
        return review
    
    def lock_cell(
        self,
        review_id: str,
        file_id: str,
        column_id: str,
        user_id: str,
        lock_duration_seconds: int = 300  # Default 5 minutes
    ) -> TabularCell:
        """Lock a cell for editing by a specific user"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Get or create the cell
        cell = self.db.query(TabularCell).filter(
            and_(
                TabularCell.tabular_review_id == review_id,
                TabularCell.file_id == file_id,
                TabularCell.column_id == column_id
            )
        ).first()
        
        if not cell:
            # Create cell if it doesn't exist
            cell = TabularCell(
                tabular_review_id=review_id,
                file_id=file_id,
                column_id=column_id,
                cell_value=None,
                status="pending"
            )
            self.db.add(cell)
            self.db.flush()
        
        # Check if cell is already locked by another user
        if cell.locked_by and cell.locked_by != user_id:
            # Check if lock has expired
            if cell.lock_expires_at and cell.lock_expires_at > datetime.utcnow():
                locked_user = self.db.query(User).filter(User.id == cell.locked_by).first()
                locked_user_name = locked_user.full_name if locked_user else "Unknown"
                raise ValueError(f"Cell is locked by {locked_user_name}")
            # Lock has expired, allow new lock
        elif cell.locked_by == user_id:
            # Already locked by this user, extend lock
            pass
        
        # Lock the cell
        now = datetime.utcnow()
        cell.locked_by = user_id
        cell.locked_at = now
        cell.lock_expires_at = now + timedelta(seconds=lock_duration_seconds)
        
        self.db.commit()
        self.db.refresh(cell)
        
        logger.info(f"Locked cell for file {file_id}, column {column_id} in review {review_id} by user {user_id}")
        return cell
    
    def unlock_cell(
        self,
        review_id: str,
        file_id: str,
        column_id: str,
        user_id: str
    ) -> TabularCell:
        """Unlock a cell"""
        # Verify review belongs to user
        review = self.db.query(TabularReview).filter(
            and_(TabularReview.id == review_id, TabularReview.user_id == user_id)
        ).first()
        
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        
        # Get the cell
        cell = self.db.query(TabularCell).filter(
            and_(
                TabularCell.tabular_review_id == review_id,
                TabularCell.file_id == file_id,
                TabularCell.column_id == column_id
            )
        ).first()
        
        if not cell:
            raise ValueError(f"Cell not found")
        
        # Check if cell is locked
        if not cell.locked_by:
            # Already unlocked
            return cell
        
        # Check if user can unlock (must be the one who locked it or review owner)
        if cell.locked_by != user_id and review.user_id != user_id:
            raise ValueError("You don't have permission to unlock this cell")
        
        # Unlock the cell
        cell.locked_by = None
        cell.locked_at = None
        cell.lock_expires_at = None
        
        self.db.commit()
        self.db.refresh(cell)
        
        logger.info(f"Unlocked cell for file {file_id}, column {column_id} in review {review_id} by user {user_id}")
        return cell

