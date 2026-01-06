#!/usr/bin/env python3
"""Script to check if templates contain unwanted columns"""
import psycopg2
import json

DATABASE_URL = 'postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'

UNWANTED_COLUMN_LABELS = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]
UNWANTED_COLUMN_LABELS_LOWER = [label.lower() for label in UNWANTED_COLUMN_LABELS]

def check_templates():
    """Check if templates contain unwanted columns"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Get all templates
        cur.execute("""
            SELECT id, name, columns, is_system, is_featured
            FROM tabular_column_templates
            ORDER BY created_at DESC;
        """)
        
        templates = cur.fetchall()
        
        problematic_templates = []
        
        for template in templates:
            template_id, name, columns_json, is_system, is_featured = template
            
            if not columns_json:
                continue
            
            try:
                columns = json.loads(columns_json) if isinstance(columns_json, str) else columns_json
                
                if not isinstance(columns, list):
                    continue
                
                unwanted_in_template = []
                for col in columns:
                    if not isinstance(col, dict):
                        continue
                    
                    col_label = col.get('column_label', '')
                    col_label_lower = col_label.lower()
                    
                    # Check if column is unwanted
                    if col_label in UNWANTED_COLUMN_LABELS:
                        unwanted_in_template.append(col_label)
                    elif col_label_lower in UNWANTED_COLUMN_LABELS_LOWER:
                        unwanted_in_template.append(col_label)
                    elif "per on" in col_label_lower and "mentioned" in col_label_lower:
                        unwanted_in_template.append(col_label)
                
                if unwanted_in_template:
                    problematic_templates.append({
                        'id': template_id,
                        'name': name,
                        'is_system': is_system,
                        'is_featured': is_featured,
                        'unwanted_columns': unwanted_in_template,
                        'total_columns': len(columns)
                    })
            except Exception as e:
                print(f"Error parsing template {template_id}: {e}")
        
        if problematic_templates:
            print(f"⚠️  Found {len(problematic_templates)} templates with unwanted columns:\n")
            for tmpl in problematic_templates:
                print(f"  Template: '{tmpl['name']}' (ID: {tmpl['id']})")
                print(f"    System: {tmpl['is_system']}, Featured: {tmpl['is_featured']}")
                print(f"    Total columns: {tmpl['total_columns']}")
                print(f"    Unwanted columns: {', '.join(tmpl['unwanted_columns'])}")
                print()
        else:
            print("✅ No templates found with unwanted columns!")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error checking templates: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_templates()

