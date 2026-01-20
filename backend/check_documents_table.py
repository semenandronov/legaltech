#!/usr/bin/env python3
"""Check documents table structure"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import create_engine, text
from app.config import config

# Get database URL from config
db_url = config.DATABASE_URL
print(f"Connecting to database...")
engine = create_engine(db_url)

with engine.connect() as conn:
    # Check table structure
    result = conn.execute(text("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'documents'
        ORDER BY ordinal_position;
    """))
    
    print("\n=== Documents table structure ===")
    for row in result:
        print(f"{row[0]}: {row[1]} (nullable: {row[2]})")
    
    # Check if table exists
    result = conn.execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'documents'
        );
    """))
    exists = result.scalar()
    print(f"\nTable 'documents' exists: {exists}")
    
    # Try to select from table
    try:
        result = conn.execute(text("SELECT COUNT(*) FROM documents"))
        count = result.scalar()
        print(f"Documents count: {count}")
    except Exception as e:
        print(f"Error selecting from documents: {e}")




















