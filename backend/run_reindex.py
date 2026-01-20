#!/usr/bin/env python3
"""
Quick script to check and reindex files for test@test.com user.
Connects directly to the database.
"""

import os
import sys

# Set DATABASE_URL before importing app modules
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require"

# Now we can import
try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "-q"])
    import psycopg2

import json

DATABASE_URL = os.environ["DATABASE_URL"]

def main():
    print("=" * 60)
    print("Checking files for user: test@test.com")
    print("=" * 60)
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # Find user
    cursor.execute("SELECT id, email, name FROM users WHERE email = %s", ("test@test.com",))
    user = cursor.fetchone()
    
    if not user:
        print("❌ User test@test.com not found!")
        cursor.close()
        conn.close()
        return
    
    user_id = user[0]
    print(f"✅ Found user: {user[1]} (ID: {user_id})")
    
    # Get cases
    cursor.execute("SELECT id, title, num_documents FROM cases WHERE user_id = %s", (user_id,))
    cases = cursor.fetchall()
    print(f"\nUser has {len(cases)} cases")
    
    if not cases:
        print("No cases found.")
        cursor.close()
        conn.close()
        return
    
    # Get indexed file IDs
    cursor.execute("""
        SELECT DISTINCT document->'metadata'->>'file_id' as file_id
        FROM langchain_pg_embedding
        WHERE document->'metadata'->>'file_id' IS NOT NULL
    """)
    indexed_file_ids = set(row[0] for row in cursor.fetchall() if row[0])
    print(f"\nTotal indexed files in PGVector: {len(indexed_file_ids)}")
    
    # Check each case
    total_files = 0
    unindexed_files = []
    
    for case_id, title, num_docs in cases:
        cursor.execute("SELECT id, filename FROM files WHERE case_id = %s", (case_id,))
        files = cursor.fetchall()
        
        print(f"\nCase: {title or case_id}")
        print(f"  Files: {len(files)}")
        
        for file_id, filename in files:
            total_files += 1
            is_indexed = file_id in indexed_file_ids
            status = "✅" if is_indexed else "❌"
            print(f"    {status} {filename}")
            if not is_indexed:
                unindexed_files.append((case_id, file_id, filename))
    
    print(f"\n{'=' * 60}")
    print(f"Summary:")
    print(f"  Total files: {total_files}")
    print(f"  Indexed: {total_files - len(unindexed_files)}")
    print(f"  Not indexed: {len(unindexed_files)}")
    print(f"{'=' * 60}")
    
    cursor.close()
    conn.close()
    
    if unindexed_files:
        print(f"\n⚠️  {len(unindexed_files)} files need to be reindexed!")
        print("\nTo reindex, run the full script on the server:")
        print("  cd backend && python scripts/reindex_user_files.py test@test.com")
    else:
        print("\n✅ All files are already indexed!")


if __name__ == "__main__":
    main()



