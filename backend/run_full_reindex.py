#!/usr/bin/env python3
"""
Full reindex script for test@test.com user.
Connects directly to the database and reindexes all unindexed files.
"""

import os
import sys

# Set DATABASE_URL before importing app modules
os.environ["DATABASE_URL"] = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require"

# Install dependencies if needed
try:
    import psycopg2
except ImportError:
    print("Installing psycopg2-binary...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "-q"])
    import psycopg2

try:
    from langchain_core.documents import Document
except ImportError:
    print("Installing langchain-core...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "langchain-core", "-q"])
    from langchain_core.documents import Document

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    print("Installing langchain-text-splitters...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "langchain-text-splitters", "-q"])
    from langchain_text_splitters import RecursiveCharacterTextSplitter

import json
import uuid
import requests

DATABASE_URL = os.environ["DATABASE_URL"]

# Yandex API settings for embeddings
YANDEX_FOLDER_ID = "b1g4samml2s1n1509ptp"
YANDEX_API_KEY = None  # Will try to get from env

def get_yandex_embeddings(texts):
    """Get embeddings from Yandex API"""
    # Try to get API key from environment or use IAM token
    api_key = os.environ.get("YANDEX_API_KEY") or os.environ.get("YC_API_KEY")
    
    if not api_key:
        # Try to read from config
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from app.config import config
            api_key = config.YANDEX_API_KEY
        except:
            pass
    
    if not api_key:
        raise ValueError("YANDEX_API_KEY not found. Please set it in environment.")
    
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
        "x-folder-id": YANDEX_FOLDER_ID
    }
    
    embeddings = []
    
    for text in texts:
        # Truncate text if too long
        if len(text) > 8000:
            text = text[:8000]
        
        payload = {
            "modelUri": f"emb://{YANDEX_FOLDER_ID}/text-search-doc/latest",
            "text": text
        }
        
        response = requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/textEmbedding",
            headers=headers,
            json=payload
        )
        
        if response.status_code != 200:
            raise Exception(f"Yandex API error: {response.status_code} - {response.text}")
        
        result = response.json()
        embeddings.append(result["embedding"])
    
    return embeddings


def main():
    print("=" * 60)
    print("Full reindex for user: test@test.com")
    print("=" * 60)
    
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    
    # Find user
    cursor.execute("SELECT id, email FROM users WHERE email = %s", ("test@test.com",))
    user = cursor.fetchone()
    
    if not user:
        print("❌ User test@test.com not found!")
        cursor.close()
        conn.close()
        return
    
    user_id = user[0]
    print(f"✅ Found user: {user[1]} (ID: {user_id})")
    
    # Get indexed file IDs
    cursor.execute("""
        SELECT DISTINCT document->'metadata'->>'file_id' as file_id
        FROM langchain_pg_embedding
        WHERE document->'metadata'->>'file_id' IS NOT NULL
    """)
    indexed_file_ids = set(row[0] for row in cursor.fetchall() if row[0])
    
    # Get cases and files
    cursor.execute("SELECT id, title FROM cases WHERE user_id = %s", (user_id,))
    cases = cursor.fetchall()
    
    total_indexed = 0
    total_chunks = 0
    
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
    )
    
    for case_id, title in cases:
        cursor.execute("""
            SELECT f.id, f.filename, f.file_type, f.original_text, dc.doc_type
            FROM files f
            LEFT JOIN document_classifications dc ON dc.file_id = f.id
            WHERE f.case_id = %s
        """, (case_id,))
        files = cursor.fetchall()
        
        files_to_index = [(fid, fname, ftype, text, dtype) 
                         for fid, fname, ftype, text, dtype in files 
                         if fid not in indexed_file_ids and text]
        
        if not files_to_index:
            continue
        
        print(f"\nProcessing case: {title or case_id}")
        print(f"  Files to index: {len(files_to_index)}")
        
        all_documents = []
        
        for file_id, filename, file_type, original_text, doc_type in files_to_index:
            # Split text into chunks
            chunks = text_splitter.split_text(original_text)
            
            for i, chunk in enumerate(chunks):
                metadata = {
                    "source": filename,
                    "file_id": file_id,
                    "file_type": file_type or "unknown",
                    "doc_type": doc_type or "other",
                    "case_id": case_id,
                    "chunk_index": i
                }
                all_documents.append(Document(page_content=chunk, metadata=metadata))
            
            print(f"    ✅ {filename}: {len(chunks)} chunks")
            total_indexed += 1
        
        if all_documents:
            print(f"  Getting embeddings for {len(all_documents)} chunks...")
            
            try:
                # Get embeddings
                texts = [doc.page_content for doc in all_documents]
                embeddings = get_yandex_embeddings(texts)
                
                print(f"  Storing in PGVector...")
                
                # Store in database
                collection_name = "legal_ai_vault_vectors"
                
                for doc, embedding in zip(all_documents, embeddings):
                    doc_id = str(uuid.uuid4())
                    
                    doc_json = {
                        "page_content": doc.page_content,
                        "metadata": doc.metadata
                    }
                    
                    embedding_str = '[' + ','.join(str(float(x)) for x in embedding) + ']'
                    
                    cursor.execute("""
                        INSERT INTO langchain_pg_embedding 
                        (uuid, collection_id, case_id, embedding, document, custom_id)
                        VALUES (%s, %s, %s, %s::vector, %s::jsonb, %s)
                    """, (doc_id, collection_name, case_id, embedding_str, json.dumps(doc_json), doc_id))
                
                conn.commit()
                total_chunks += len(all_documents)
                print(f"  ✅ Stored {len(all_documents)} chunks")
                
                # Update case full_text
                cursor.execute("SELECT original_text, filename FROM files WHERE case_id = %s", (case_id,))
                all_files = cursor.fetchall()
                text_parts = [f"[{fname}]\n{text}" for text, fname in all_files if text]
                
                if text_parts:
                    full_text = "\n\n".join(text_parts)
                    if len(full_text) > 100 * 1024 * 1024:
                        full_text = full_text[:100 * 1024 * 1024]
                    cursor.execute("UPDATE cases SET full_text = %s WHERE id = %s", (full_text, case_id))
                    conn.commit()
                    print(f"  ✅ Updated case full_text")
                
            except Exception as e:
                print(f"  ❌ Error: {e}")
                conn.rollback()
    
    cursor.close()
    conn.close()
    
    print(f"\n{'=' * 60}")
    print("Reindexing completed!")
    print(f"  Files indexed: {total_indexed}")
    print(f"  Total chunks: {total_chunks}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

