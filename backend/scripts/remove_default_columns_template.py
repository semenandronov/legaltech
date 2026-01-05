#!/usr/bin/env python3
"""Script to remove templates with default columns (Date, Document type, Summary, Author, Persons mentioned, Language)"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.database import get_db
from app.models.tabular_review import TabularColumnTemplate
from sqlalchemy import or_

# Target column labels to find and remove
TARGET_COLUMNS = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]

def find_and_remove_templates():
    """Find and remove templates containing the target columns"""
    db = next(get_db())
    
    try:
        # Get all templates
        templates = db.query(TabularColumnTemplate).all()
        
        templates_to_remove = []
        for template in templates:
            if not template.columns:
                continue
                
            column_labels = [col.get('column_label', '') for col in template.columns]
            
            # Check if template contains any of the target columns
            has_target_columns = any(label in TARGET_COLUMNS for label in column_labels)
            
            # Check if template has all or most of the target columns (likely the default template)
            matching_count = sum(1 for label in column_labels if label in TARGET_COLUMNS)
            
            if has_target_columns:
                print(f"Found template: {template.name} (ID: {template.id})")
                print(f"  Featured: {template.is_featured}, System: {template.is_system}")
                print(f"  Columns: {column_labels}")
                print(f"  Matching target columns: {matching_count}/{len(TARGET_COLUMNS)}")
                
                # If it has 4+ matching columns, it's likely the default template
                if matching_count >= 4:
                    templates_to_remove.append(template)
                    print(f"  -> MARKED FOR REMOVAL")
                print()
        
        if not templates_to_remove:
            print("No templates found with target columns.")
            return
        
        # Remove templates
        print(f"\nRemoving {len(templates_to_remove)} template(s)...")
        for template in templates_to_remove:
            print(f"  Removing: {template.name} (ID: {template.id})")
            db.delete(template)
        
        db.commit()
        print(f"\nSuccessfully removed {len(templates_to_remove)} template(s)")
        
    except Exception as e:
        db.rollback()
        print(f"Error removing templates: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    find_and_remove_templates()

