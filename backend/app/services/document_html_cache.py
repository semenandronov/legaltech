"""Document HTML Cache Service for Legal AI Vault"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.case import File
import logging

logger = logging.getLogger(__name__)


class DocumentHtmlCacheService:
    """Service for caching HTML representations of documents"""
    
    def __init__(self, db: Session):
        """Initialize HTML cache service"""
        self.db = db
    
    def get_cached_html(self, file_id: str) -> Optional[str]:
        """
        Get cached HTML for a file
        
        Args:
            file_id: File identifier
            
        Returns:
            Cached HTML string or None if not cached
        """
        try:
            file = self.db.query(File).filter(File.id == file_id).first()
            if file and file.html_content:
                logger.debug(f"Cache hit for file {file_id}")
                return file.html_content
            logger.debug(f"Cache miss for file {file_id}")
            return None
        except Exception as e:
            logger.error(f"Error getting cached HTML for file {file_id}: {e}", exc_info=True)
            return None
    
    def cache_html(self, file_id: str, html: str) -> None:
        """
        Cache HTML for a file
        
        Args:
            file_id: File identifier
            html: HTML string to cache
        """
        try:
            file = self.db.query(File).filter(File.id == file_id).first()
            if not file:
                logger.warning(f"File {file_id} not found, cannot cache HTML")
                return
            
            file.html_content = html
            self.db.commit()
            logger.info(f"Cached HTML for file {file_id} ({len(html)} chars)")
        except Exception as e:
            logger.error(f"Error caching HTML for file {file_id}: {e}", exc_info=True)
            self.db.rollback()
            raise
    
    def invalidate_cache(self, file_id: str) -> None:
        """
        Invalidate cached HTML for a file
        
        Args:
            file_id: File identifier
        """
        try:
            file = self.db.query(File).filter(File.id == file_id).first()
            if not file:
                logger.warning(f"File {file_id} not found, cannot invalidate cache")
                return
            
            if file.html_content:
                file.html_content = None
                self.db.commit()
                logger.info(f"Invalidated HTML cache for file {file_id}")
        except Exception as e:
            logger.error(f"Error invalidating cache for file {file_id}: {e}", exc_info=True)
            self.db.rollback()
            raise
    
    def has_cache(self, file_id: str) -> bool:
        """
        Check if HTML is cached for a file
        
        Args:
            file_id: File identifier
            
        Returns:
            True if HTML is cached, False otherwise
        """
        try:
            file = self.db.query(File).filter(File.id == file_id).first()
            return file is not None and file.html_content is not None
        except Exception as e:
            logger.error(f"Error checking cache for file {file_id}: {e}", exc_info=True)
            return False

