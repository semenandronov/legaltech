#!/usr/bin/env python3
"""
Migration script to reindex files that were added to cases but not indexed in PGVector.

This script:
1. Finds all files in the database
2. Checks which files are already indexed in PGVector (by file_id in metadata)
3. Indexes missing files in PGVector

Run with: python -m migrations.reindex_missing_files
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import config
from app.models.case import Case, File as FileModel
from app.models.analysis import DocumentClassification
from app.services.document_processor import DocumentProcessor
from app.utils.database import get_db, SessionLocal

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sanitize_text(text: str) -> str:
    """Remove null bytes and other problematic characters from text"""
    if not text:
        return ""
    # Remove null bytes
    text = text.replace('\x00', '')
    # Remove other control characters except newlines and tabs
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')
    return text


def get_indexed_file_ids(engine) -> set:
    """Get set of file_ids that are already indexed in PGVector"""
    indexed_file_ids = set()
    
    try:
        with engine.connect() as conn:
            # Query all unique file_ids from PGVector metadata
            result = conn.execute(text("""
                SELECT DISTINCT document->'metadata'->>'file_id' as file_id
                FROM langchain_pg_embedding
                WHERE document->'metadata'->>'file_id' IS NOT NULL
            """))
            
            for row in result:
                if row[0]:
                    indexed_file_ids.add(row[0])
        
        logger.info(f"Found {len(indexed_file_ids)} files already indexed in PGVector")
    except Exception as e:
        logger.warning(f"Could not query indexed files (table may not exist): {e}")
    
    return indexed_file_ids


def reindex_missing_files():
    """Main function to reindex missing files"""
    logger.info("=" * 60)
    logger.info("Starting migration: Reindex missing files in PGVector")
    logger.info("=" * 60)
    
    # Create database session
    db = SessionLocal()
    
    try:
        # Get all files from database
        all_files = db.query(FileModel).all()
        logger.info(f"Found {len(all_files)} total files in database")
        
        if not all_files:
            logger.info("No files found in database. Nothing to reindex.")
            return
        
        # Create engine for PGVector queries
        db_url = config.DATABASE_URL
        if db_url.startswith("postgresql+psycopg://"):
            db_url = db_url.replace("postgresql+psycopg://", "postgresql://")
        engine = create_engine(db_url)
        
        # Get already indexed file IDs
        indexed_file_ids = get_indexed_file_ids(engine)
        
        # Find files that need to be indexed
        files_to_index = [f for f in all_files if f.id not in indexed_file_ids]
        logger.info(f"Found {len(files_to_index)} files that need to be indexed")
        
        if not files_to_index:
            logger.info("All files are already indexed. Nothing to do.")
            return
        
        # Group files by case_id for efficient processing
        files_by_case = {}
        for file in files_to_index:
            if file.case_id not in files_by_case:
                files_by_case[file.case_id] = []
            files_by_case[file.case_id].append(file)
        
        logger.info(f"Files to index are distributed across {len(files_by_case)} cases")
        
        # Initialize document processor
        document_processor = DocumentProcessor()
        
        # Get all classifications for efficiency
        all_file_ids = [f.id for f in files_to_index]
        classifications = db.query(DocumentClassification).filter(
            DocumentClassification.file_id.in_(all_file_ids)
        ).all()
        classification_map = {c.file_id: c for c in classifications if c.file_id}
        logger.info(f"Loaded {len(classification_map)} classifications for files")
        
        # Process each case
        total_indexed = 0
        total_chunks = 0
        
        for case_id, case_files in files_by_case.items():
            logger.info(f"\nProcessing case {case_id} with {len(case_files)} files...")
            
            all_documents = []
            
            for file in case_files:
                if not file.original_text:
                    logger.warning(f"  Skipping file {file.id} ({file.filename}) - no text content")
                    continue
                
                # Build metadata
                metadata = {
                    "source": file.filename,
                    "file_id": file.id,
                    "file_type": file.file_type or "unknown",
                }
                
                # Add classification metadata if available
                classification = classification_map.get(file.id)
                if classification:
                    metadata["doc_type"] = classification.doc_type or "other"
                    metadata["is_privileged"] = str(classification.is_privileged) if classification.is_privileged else "false"
                    metadata["relevance_score"] = classification.relevance_score or 0
                
                # Split text into chunks
                try:
                    file_documents = document_processor.split_documents(
                        text=file.original_text,
                        filename=file.filename,
                        metadata=metadata,
                    )
                    all_documents.extend(file_documents)
                    logger.info(f"  Processed file {file.filename}: {len(file_documents)} chunks")
                except Exception as e:
                    logger.error(f"  Error processing file {file.filename}: {e}")
                    continue
            
            if all_documents:
                try:
                    logger.info(f"  Storing {len(all_documents)} chunks in PGVector for case {case_id}...")
                    
                    collection_name = document_processor.store_in_vector_db(
                        case_id=case_id,
                        documents=all_documents,
                        db=db,
                        original_files=None
                    )
                    
                    total_indexed += len(case_files)
                    total_chunks += len(all_documents)
                    logger.info(f"  ✅ Successfully indexed {len(all_documents)} chunks for case {case_id}")
                    
                except Exception as e:
                    logger.error(f"  ❌ Error indexing case {case_id}: {e}")
            else:
                logger.warning(f"  No documents to index for case {case_id}")
        
        logger.info("\n" + "=" * 60)
        logger.info("Migration completed!")
        logger.info(f"  Total files indexed: {total_indexed}")
        logger.info(f"  Total chunks created: {total_chunks}")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    reindex_missing_files()

