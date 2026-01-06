#!/usr/bin/env python3
"""Script to check columns for a specific review ID"""
import psycopg2

DATABASE_URL = 'postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'

# Review ID from the browser URL
REVIEW_ID = '056d9e06-c88e-43f9-abaf-c18e679e30ce'

def check_review_columns():
    """Check columns for a specific review"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Get review info
        cur.execute("""
            SELECT id, name, case_id, user_id, created_at
            FROM tabular_reviews
            WHERE id = %s;
        """, (REVIEW_ID,))
        
        review = cur.fetchone()
        if not review:
            print(f"❌ Review {REVIEW_ID} not found")
            return
        
        print(f"Review: {review[1]} (ID: {review[0]})")
        print(f"Case ID: {review[2]}, User ID: {review[3]}")
        print(f"Created: {review[4]}\n")
        
        # Get all columns for this review
        cur.execute("""
            SELECT id, column_label, column_type, order_index, created_at
            FROM tabular_columns
            WHERE tabular_review_id = %s
            ORDER BY order_index;
        """, (REVIEW_ID,))
        
        columns = cur.fetchall()
        
        print(f"Total columns in database: {len(columns)}")
        if columns:
            print("\nColumns:")
            for col in columns:
                print(f"  {col[3]}. '{col[1]}' (type: {col[2]}, id: {col[0]}, created: {col[4]})")
        
        # Check for unwanted columns
        unwanted_labels = ["Date", "Document type", "Summary", "Author", "Persons mentioned", "Language"]
        unwanted = [col for col in columns if col[1] in unwanted_labels or col[1].lower() in [l.lower() for l in unwanted_labels]]
        
        if unwanted:
            print(f"\n⚠️  Found {len(unwanted)} unwanted columns:")
            for col in unwanted:
                print(f"  - '{col[1]}' (id: {col[0]})")
        else:
            print("\n✅ No unwanted columns found in database")
        
        # Check cells - see if there are cells for columns that don't exist
        cur.execute("""
            SELECT DISTINCT tc.column_id, COUNT(*) as cell_count
            FROM tabular_cells tc
            WHERE tc.tabular_review_id = %s
            GROUP BY tc.column_id;
        """, (REVIEW_ID,))
        
        cell_stats = cur.fetchall()
        
        column_ids = {col[0] for col in columns}
        orphaned_cells = [stat for stat in cell_stats if stat[0] not in column_ids]
        
        if orphaned_cells:
            print(f"\n⚠️  Found cells for non-existent columns:")
            for stat in orphaned_cells:
                print(f"  - Column ID: {stat[0]}, Cells: {stat[1]}")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_review_columns()

