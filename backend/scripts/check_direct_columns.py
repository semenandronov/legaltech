#!/usr/bin/env python3
"""Script to check if problematic columns exist directly in tabular_columns table"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection string from user
DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Target column labels to find
TARGET_COLUMNS = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]

def check_direct_columns():
    """Check if problematic columns exist directly in tabular_columns"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Get all columns with target labels
        result = db.execute(text("""
            SELECT 
                tc.id,
                tc.tabular_review_id,
                tc.column_label,
                tc.column_type,
                tc.order_index,
                tc.created_at,
                tr.name as review_name,
                tr.user_id
            FROM tabular_columns tc
            LEFT JOIN tabular_reviews tr ON tc.tabular_review_id = tr.id
            WHERE tc.column_label IN :target_labels
            ORDER BY tc.created_at DESC
            LIMIT 50
        """), {"target_labels": tuple(TARGET_COLUMNS)})
        
        columns_found = []
        for row in result:
            columns_found.append({
                "id": row[0],
                "review_id": row[1],
                "column_label": row[2],
                "column_type": row[3],
                "order_index": row[4],
                "created_at": row[5],
                "review_name": row[6],
                "user_id": row[7]
            })
        
        if not columns_found:
            logger.info("No problematic columns found in tabular_columns table.")
            return
        
        logger.info(f"Found {len(columns_found)} problematic columns:")
        logger.info("")
        
        # Group by review_id
        reviews_with_problematic_columns = {}
        for col in columns_found:
            review_id = col["review_id"]
            if review_id not in reviews_with_problematic_columns:
                reviews_with_problematic_columns[review_id] = []
            reviews_with_problematic_columns[review_id].append(col)
        
        for review_id, cols in reviews_with_problematic_columns.items():
            logger.info(f"Review ID: {review_id}")
            logger.info(f"  Review Name: {cols[0]['review_name']}")
            logger.info(f"  User ID: {cols[0]['user_id']}")
            logger.info(f"  Problematic columns ({len(cols)}):")
            for col in cols:
                logger.info(f"    - {col['column_label']} (type: {col['column_type']}, order: {col['order_index']}, created: {col['created_at']})")
            logger.info("")
        
        # Check if we should delete these columns
        logger.info(f"\nTotal problematic columns found: {len(columns_found)}")
        logger.info("These columns should be deleted automatically by the code, but if they persist, they can be removed manually.")
        
    except Exception as e:
        logger.error(f"Error checking columns: {e}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    check_direct_columns()

