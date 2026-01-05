#!/usr/bin/env python3
"""Script to check for orphaned cells (cells with column_id that doesn't exist)"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection string from user
DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Review ID from screenshot
REVIEW_ID = "2b4916e1-6d74-4fb7-b551-c60fe67bf748"

def check_orphaned_cells():
    """Check for orphaned cells (cells with column_id that doesn't exist)"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Get all cells for this review
        result = db.execute(text("""
            SELECT 
                tc.id,
                tc.column_id,
                tc.file_id,
                tc.cell_value,
                tc.created_at,
                col.column_label,
                col.id as column_exists
            FROM tabular_cells tc
            LEFT JOIN tabular_columns col ON tc.column_id = col.id
            WHERE tc.tabular_review_id = :review_id
            ORDER BY tc.created_at DESC
        """), {"review_id": REVIEW_ID})
        
        cells_found = []
        orphaned_cells = []
        for row in result:
            cell = {
                "id": row[0],
                "column_id": row[1],
                "file_id": row[2],
                "cell_value": row[3],
                "created_at": row[4],
                "column_label": row[5],
                "column_exists": row[6]
            }
            cells_found.append(cell)
            if not cell["column_exists"]:
                orphaned_cells.append(cell)
        
        logger.info(f"Review ID: {REVIEW_ID}")
        logger.info(f"Total cells: {len(cells_found)}")
        logger.info(f"Orphaned cells (column doesn't exist): {len(orphaned_cells)}")
        logger.info("")
        
        if orphaned_cells:
            logger.warning("⚠️  Found orphaned cells (cells with column_id that doesn't exist):")
            for cell in orphaned_cells:
                logger.warning(f"  - Cell ID: {cell['id']}, Column ID: {cell['column_id']}, Created: {cell['created_at']}")
        
        # Group cells by column_id
        cells_by_column = {}
        for cell in cells_found:
            col_id = cell["column_id"]
            if col_id not in cells_by_column:
                cells_by_column[col_id] = []
            cells_by_column[col_id].append(cell)
        
        logger.info(f"\nCells grouped by column_id ({len(cells_by_column)} unique column_ids):")
        for col_id, cells in cells_by_column.items():
            col_label = cells[0]["column_label"] if cells[0]["column_label"] else "UNKNOWN"
            logger.info(f"  Column ID {col_id} ({col_label}): {len(cells)} cells")
        
    except Exception as e:
        logger.error(f"Error checking cells: {e}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    check_orphaned_cells()

