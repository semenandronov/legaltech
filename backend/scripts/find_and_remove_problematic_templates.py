#!/usr/bin/env python3
"""Script to find and remove templates containing problematic default columns"""
import sys
import os
import json

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection string from user
DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Target column labels to find and remove
TARGET_COLUMNS = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]

def find_and_remove_templates():
    """Find and remove templates containing the target columns"""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    
    try:
        # Get all templates
        result = db.execute(text("""
            SELECT id, name, is_featured, is_system, columns
            FROM tabular_column_templates
        """))
        
        templates_to_remove = []
        for row in result:
            template_id = row[0]
            template_name = row[1]
            is_featured = row[2]
            is_system = row[3]
            columns_json = row[4]
            
            if not columns_json:
                continue
            
            # Parse JSON columns
            try:
                columns = json.loads(columns_json) if isinstance(columns_json, str) else columns_json
            except:
                continue
            
            column_labels = [col.get('column_label', '') for col in columns if isinstance(col, dict)]
            
            # Check if template contains any of the target columns
            has_target_columns = any(label in TARGET_COLUMNS for label in column_labels)
            
            # Check if template has all or most of the target columns (likely the default template)
            matching_count = sum(1 for label in column_labels if label in TARGET_COLUMNS)
            
            if has_target_columns:
                logger.info(f"Found template: {template_name} (ID: {template_id})")
                logger.info(f"  Featured: {is_featured}, System: {is_system}")
                logger.info(f"  Columns: {column_labels}")
                logger.info(f"  Matching target columns: {matching_count}/{len(TARGET_COLUMNS)}")
                
                # If it has 4+ matching columns, it's likely the default template
                if matching_count >= 4:
                    templates_to_remove.append((template_id, template_name))
                    logger.info(f"  -> MARKED FOR REMOVAL")
                logger.info("")
        
        if not templates_to_remove:
            logger.info("No templates found with target columns.")
            return
        
        # Remove templates
        logger.info(f"\nRemoving {len(templates_to_remove)} template(s)...")
        for template_id, template_name in templates_to_remove:
            logger.info(f"  Removing: {template_name} (ID: {template_id})")
            db.execute(text("DELETE FROM tabular_column_templates WHERE id = :id"), {"id": template_id})
        
        db.commit()
        logger.info(f"\nSuccessfully removed {len(templates_to_remove)} template(s)")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error removing templates: {e}", exc_info=True)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    find_and_remove_templates()

