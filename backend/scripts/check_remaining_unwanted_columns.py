#!/usr/bin/env python3
"""Script to check if any unwanted columns remain in the database"""
import psycopg2

DATABASE_URL = 'postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'

def check_remaining_columns():
    """Check if any unwanted columns remain"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Check for unwanted columns
        cur.execute("""
            SELECT id, tabular_review_id, column_label, column_type, created_at
            FROM tabular_columns
            WHERE column_label IN ('Date', 'Document type', 'Summary', 'Author', 'Persons mentioned', 'Language')
               OR LOWER(column_label) IN ('date', 'document type', 'summary', 'author', 'persons mentioned', 'language')
               OR (LOWER(column_label) LIKE '%per on%' AND LOWER(column_label) LIKE '%mentioned%')
            ORDER BY created_at DESC;
        """)
        
        results = cur.fetchall()
        
        if results:
            print(f"⚠️  Found {len(results)} unwanted columns still in database:")
            for row in results:
                print(f"  - ID: {row[0]}, Label: '{row[2]}', Review ID: {row[1]}, Type: {row[3]}, Created: {row[4]}")
        else:
            print("✅ No unwanted columns found in database!")
        
        # Also check all columns to see what we have
        cur.execute("""
            SELECT COUNT(*) as total_columns,
                   COUNT(DISTINCT tabular_review_id) as total_reviews
            FROM tabular_columns;
        """)
        
        stats = cur.fetchone()
        print(f"\nDatabase statistics:")
        print(f"  - Total columns: {stats[0]}")
        print(f"  - Total reviews: {stats[1]}")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error checking columns: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_remaining_columns()

