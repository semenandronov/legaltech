#!/usr/bin/env python3
"""
Script to check and reindex files for a specific user.

Usage:
    python scripts/reindex_user_files.py test@test.com
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from sqlalchemy import create_engine, text

from app.config import config
from app.models.case import Case, File as FileModel
from app.models.user import User
from app.models.analysis import DocumentClassification
from app.services.document_processor import DocumentProcessor
from app.utils.database import SessionLocal

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def sanitize_text(text_content: str) -> str:
    """Remove null bytes and other problematic characters from text"""
    if not text_content:
        return ""
    text_content = text_content.replace('\x00', '')
    text_content = ''.join(char for char in text_content if ord(char) >= 32 or char in '\n\r\t')
    return text_content


def get_indexed_file_ids(engine) -> set:
    """Get set of file_ids that are already indexed in PGVector"""
    indexed_file_ids = set()
    
    try:
        with engine.connect() as conn:
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
        logger.warning(f"Could not query indexed files: {e}")
    
    return indexed_file_ids


def check_and_reindex_user(email: str):
    """Check and reindex files for a specific user"""
    logger.info("=" * 60)
    logger.info(f"Checking files for user: {email}")
    logger.info("=" * 60)
    
    db = SessionLocal()
    
    try:
        # Find user
        user = db.query(User).filter(User.email == email).first()
        
        if not user:
            logger.error(f"User with email '{email}' not found!")
            return
        
        logger.info(f"Found user: {user.email} (ID: {user.id})")
        
        # Get all cases for user
        cases = db.query(Case).filter(Case.user_id == user.id).all()
        logger.info(f"User has {len(cases)} cases")
        
        if not cases:
            logger.info("No cases found for this user.")
            return
        
        # Create engine for PGVector queries
        db_url = config.DATABASE_URL
        if db_url.startswith("postgresql+psycopg://"):
            db_url = db_url.replace("postgresql+psycopg://", "postgresql://")
        engine = create_engine(db_url)
        
        # Get already indexed file IDs
        indexed_file_ids = get_indexed_file_ids(engine)
        
        # Check each case
        total_files = 0
        unindexed_files = 0
        
        for case in cases:
            files = db.query(FileModel).filter(FileModel.case_id == case.id).all()
            logger.info(f"\nCase: {case.title or case.id}")
            logger.info(f"  - Files: {len(files)}")
            
            for file in files:
                total_files += 1
                is_indexed = file.id in indexed_file_ids
                status = "✅ indexed" if is_indexed else "❌ NOT indexed"
                logger.info(f"    - {file.filename}: {status}")
                if not is_indexed:
                    unindexed_files += 1
        
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Summary:")
        logger.info(f"  Total files: {total_files}")
        logger.info(f"  Indexed: {total_files - unindexed_files}")
        logger.info(f"  Not indexed: {unindexed_files}")
        logger.info(f"{'=' * 60}")
        
        if unindexed_files == 0:
            logger.info("\n✅ All files are already indexed! Nothing to do.")
            return
        
        # Ask for confirmation to reindex
        logger.info(f"\n🔄 Starting reindexing of {unindexed_files} files...")
        
        # Initialize document processor
        document_processor = DocumentProcessor()
        
        total_indexed = 0
        total_chunks = 0
        
        for case in cases:
            files = db.query(FileModel).filter(FileModel.case_id == case.id).all()
            files_to_index = [f for f in files if f.id not in indexed_file_ids]
            
            if not files_to_index:
                continue
            
            logger.info(f"\nReindexing case: {case.title or case.id} ({len(files_to_index)} files)")
            
            # Get classifications
            file_ids = [f.id for f in files_to_index]
            classifications = db.query(DocumentClassification).filter(
                DocumentClassification.file_id.in_(file_ids)
            ).all()
            classification_map = {c.file_id: c for c in classifications if c.file_id}
            
            all_documents = []
            
            for file in files_to_index:
                if not file.original_text:
                    logger.warning(f"  Skipping {file.filename} - no text content")
                    continue
                
                metadata = {
                    "source": file.filename,
                    "file_id": file.id,
                    "file_type": file.file_type or "unknown",
                }
                
                classification = classification_map.get(file.id)
                if classification:
                    metadata["doc_type"] = classification.doc_type or "other"
                    metadata["is_privileged"] = str(classification.is_privileged) if classification.is_privileged else "false"
                    metadata["relevance_score"] = classification.relevance_score or 0
                
                try:
                    file_documents = document_processor.split_documents(
                        text=file.original_text,
                        filename=file.filename,
                        metadata=metadata,
                    )
                    all_documents.extend(file_documents)
                    logger.info(f"  ✅ {file.filename}: {len(file_documents)} chunks")
                    total_indexed += 1
                except Exception as e:
                    logger.error(f"  ❌ Error processing {file.filename}: {e}")
            
            if all_documents:
                try:
                    document_processor.store_in_vector_db(
                        case_id=case.id,
                        documents=all_documents,
                        db=db,
                        original_files=None
                    )
                    total_chunks += len(all_documents)
                    logger.info(f"  Stored {len(all_documents)} chunks in PGVector")
                    
                    # Update case full_text
                    all_case_files = db.query(FileModel).filter(FileModel.case_id == case.id).all()
                    text_parts = []
                    for f in all_case_files:
                        if f.original_text:
                            text_parts.append(f"[{f.filename}]\n{f.original_text}")
                    
                    if text_parts:
                        full_text = "\n\n".join(text_parts)
                        MAX_TEXT_LENGTH = 100 * 1024 * 1024
                        sanitized_full_text = sanitize_text(full_text)
                        if len(sanitized_full_text) > MAX_TEXT_LENGTH:
                            sanitized_full_text = sanitized_full_text[:MAX_TEXT_LENGTH]
                        case.full_text = sanitized_full_text
                        db.commit()
                        
                except Exception as e:
                    logger.error(f"  ❌ Error storing in PGVector: {e}")
        
        logger.info(f"\n{'=' * 60}")
        logger.info("Reindexing completed!")
        logger.info(f"  Files indexed: {total_indexed}")
        logger.info(f"  Total chunks: {total_chunks}")
        logger.info(f"{'=' * 60}")
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/reindex_user_files.py <email>")
        print("Example: python scripts/reindex_user_files.py test@test.com")
        sys.exit(1)
    
    email = sys.argv[1]
    check_and_reindex_user(email)

