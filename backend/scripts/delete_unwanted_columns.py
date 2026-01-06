#!/usr/bin/env python3
"""Script to delete unwanted columns (Date, Document type, Summary, Author, Persons mentioned, Language) from all tabular reviews"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.database import get_db
from app.models.tabular_review import TabularColumn, TabularCell, CellComment, CellHistory
from sqlalchemy import or_, func
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Target column labels to find and remove (case-insensitive)
UNWANTED_COLUMN_LABELS = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]
UNWANTED_COLUMN_LABELS_LOWER = [label.lower() for label in UNWANTED_COLUMN_LABELS]

def delete_unwanted_columns():
    """Find and delete all unwanted columns from all tabular reviews"""
    db = next(get_db())
    
    try:
        # Find all unwanted columns
        unwanted_columns = []
        
        # Get all columns
        all_columns = db.query(TabularColumn).all()
        
        for col in all_columns:
            col_label_lower = col.column_label.lower()
            
            # Check exact match
            if col.column_label in UNWANTED_COLUMN_LABELS:
                unwanted_columns.append(col)
            # Check case-insensitive match
            elif col_label_lower in UNWANTED_COLUMN_LABELS_LOWER:
                unwanted_columns.append(col)
            # Check for variations like "Per on mentioned" (typo for "Persons mentioned")
            elif "per on" in col_label_lower and "mentioned" in col_label_lower:
                unwanted_columns.append(col)
        
        if not unwanted_columns:
            logger.info("No unwanted columns found in the database.")
            return
        
        logger.info(f"Found {len(unwanted_columns)} unwanted columns to delete:")
        for col in unwanted_columns:
            logger.info(f"  - ID: {col.id}, Label: '{col.column_label}', Review ID: {col.tabular_review_id}")
        
        # Delete all related data for each unwanted column
        deleted_cells_count = 0
        deleted_comments_count = 0
        deleted_history_count = 0
        
        for col in unwanted_columns:
            # Delete all cells for this column
            cells = db.query(TabularCell).filter(TabularCell.column_id == col.id).all()
            deleted_cells_count += len(cells)
            db.query(TabularCell).filter(TabularCell.column_id == col.id).delete()
            
            # Delete all comments for this column
            comments = db.query(CellComment).filter(CellComment.column_id == col.id).all()
            deleted_comments_count += len(comments)
            db.query(CellComment).filter(CellComment.column_id == col.id).delete()
            
            # Delete all history records for this column
            history_records = db.query(CellHistory).filter(CellHistory.column_id == col.id).all()
            deleted_history_count += len(history_records)
            db.query(CellHistory).filter(CellHistory.column_id == col.id).delete()
            
            logger.info(f"  Deleted related data for column '{col.column_label}': {len(cells)} cells, {len(comments)} comments, {len(history_records)} history records")
        
        # Delete the columns themselves
        column_ids = [col.id for col in unwanted_columns]
        db.query(TabularColumn).filter(TabularColumn.id.in_(column_ids)).delete(synchronize_session=False)
        
        # Commit all changes
        db.commit()
        
        logger.info(f"\n✅ Successfully deleted:")
        logger.info(f"  - {len(unwanted_columns)} unwanted columns")
        logger.info(f"  - {deleted_cells_count} cells")
        logger.info(f"  - {deleted_comments_count} comments")
        logger.info(f"  - {deleted_history_count} history records")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting unwanted columns: {e}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    delete_unwanted_columns()

