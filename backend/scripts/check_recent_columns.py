#!/usr/bin/env python3
"""Script to check recent column creation activity"""
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

def check_recent_columns():
    """Check recent column creation activity"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Get all recent columns (last 24 hours)
        result = db.execute(text("""
            SELECT 
                tc.id,
                tc.tabular_review_id,
                tc.column_label,
                tc.column_type,
                tc.order_index,
                tc.created_at,
                tr.name as review_name,
                tr.user_id,
                tr.created_at as review_created_at
            FROM tabular_columns tc
            LEFT JOIN tabular_reviews tr ON tc.tabular_review_id = tr.id
            WHERE tc.created_at > NOW() - INTERVAL '24 hours'
            ORDER BY tc.created_at DESC
            LIMIT 100
        """))
        
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
                "user_id": row[7],
                "review_created_at": row[8]
            })
        
        if not columns_found:
            logger.info("No columns created in the last 24 hours.")
            return
        
        logger.info(f"Found {len(columns_found)} columns created in the last 24 hours:")
        logger.info("")
        
        # Group by review_id
        reviews_with_columns = {}
        for col in columns_found:
            review_id = col["review_id"]
            if review_id not in reviews_with_columns:
                reviews_with_columns[review_id] = {
                    "review_name": col["review_name"],
                    "user_id": col["user_id"],
                    "review_created_at": col["review_created_at"],
                    "columns": []
                }
            reviews_with_columns[review_id]["columns"].append(col)
        
        for review_id, data in reviews_with_columns.items():
            logger.info(f"Review ID: {review_id}")
            logger.info(f"  Review Name: {data['review_name']}")
            logger.info(f"  User ID: {data['user_id']}")
            logger.info(f"  Review Created: {data['review_created_at']}")
            logger.info(f"  Columns ({len(data['columns'])}):")
            for col in sorted(data['columns'], key=lambda x: x['order_index']):
                logger.info(f"    - {col['column_label']} (type: {col['column_type']}, order: {col['order_index']}, created: {col['created_at']})")
            logger.info("")
        
        # Check for problematic columns
        problematic = [col for col in columns_found if col['column_label'] in ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]]
        if problematic:
            logger.warning(f"\n⚠️  Found {len(problematic)} problematic columns:")
            for col in problematic:
                logger.warning(f"  - Review {col['review_id']}: {col['column_label']} (created: {col['created_at']})")
        
    except Exception as e:
        logger.error(f"Error checking columns: {e}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    check_recent_columns()

