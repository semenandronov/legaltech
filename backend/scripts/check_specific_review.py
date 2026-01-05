#!/usr/bin/env python3
"""Script to check a specific review for problematic columns"""
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

# Review ID to check
REVIEW_ID = "3b28f1ba-0a22-49ce-a844-1e26dcf1b12e"

def check_specific_review():
    """Check a specific review for all columns"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Get all columns for this review
        result = db.execute(text("""
            SELECT 
                tc.id,
                tc.column_label,
                tc.column_type,
                tc.order_index,
                tc.created_at,
                tr.name as review_name,
                tr.created_at as review_created_at
            FROM tabular_columns tc
            LEFT JOIN tabular_reviews tr ON tc.tabular_review_id = tr.id
            WHERE tc.tabular_review_id = :review_id
            ORDER BY tc.order_index
        """), {"review_id": REVIEW_ID})
        
        columns_found = []
        for row in result:
            columns_found.append({
                "id": row[0],
                "column_label": row[1],
                "column_type": row[2],
                "order_index": row[3],
                "created_at": row[4],
                "review_name": row[5],
                "review_created_at": row[6]
            })
        
        if not columns_found:
            logger.info(f"No columns found for review {REVIEW_ID}.")
            return
        
        logger.info(f"Review ID: {REVIEW_ID}")
        logger.info(f"Review Name: {columns_found[0]['review_name']}")
        logger.info(f"Review Created: {columns_found[0]['review_created_at']}")
        logger.info(f"Total columns: {len(columns_found)}")
        logger.info("")
        logger.info("All columns:")
        for col in columns_found:
            logger.info(f"  {col['order_index']}. {col['column_label']} (type: {col['column_type']}, created: {col['created_at']}, id: {col['id']})")
        
        # Check for problematic columns
        problematic_labels = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]
        problematic = [col for col in columns_found if col['column_label'] in problematic_labels]
        if problematic:
            logger.warning(f"\n⚠️  Found {len(problematic)} problematic columns:")
            for col in problematic:
                logger.warning(f"  - {col['column_label']} (id: {col['id']}, created: {col['created_at']})")
        else:
            logger.info("\n✅ No problematic columns found in this review.")
        
    except Exception as e:
        logger.error(f"Error checking review: {e}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    check_specific_review()

