#!/usr/bin/env python3
"""Script to run SQL script against the database"""
import psycopg2
import sys
import os

# Database connection string
DATABASE_URL = 'postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'

def run_sql_script(script_path):
    """Run SQL script from file"""
    try:
        # Connect to database
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cur = conn.cursor()
        
        # Read SQL script
        with open(script_path, 'r') as f:
            sql_script = f.read()
        
        # Execute SQL script
        cur.execute(sql_script)
        
        # Commit transaction
        conn.commit()
        
        print("✅ SQL script executed successfully")
        
        # Try to fetch results if there's a SELECT statement
        try:
            results = cur.fetchall()
            if results:
                print("\nResults:")
                for row in results:
                    print(f"  {row}")
        except:
            pass  # No results to fetch
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error executing SQL script: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        sys.exit(1)

if __name__ == "__main__":
    script_path = os.path.join(os.path.dirname(__file__), "delete_unwanted_columns.sql")
    run_sql_script(script_path)

