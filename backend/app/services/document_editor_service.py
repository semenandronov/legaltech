"""Document Editor Service for Legal AI Vault"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from app.models.document_editor import Document, DocumentVersion
from app.models.case import Case
from app.models.user import User
from datetime import datetime
import logging
import re
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


class HTMLToPlainTextParser(HTMLParser):
    """Simple HTML to plain text converter"""
    def __init__(self):
        super().__init__()
        self.text = []
    
    def handle_data(self, data):
        self.text.append(data)
    
    def get_text(self):
        return ' '.join(self.text)


class DocumentEditorService:
    """Service for managing editable documents"""
    
    def __init__(self, db: Session):
        """Initialize document editor service"""
        self.db = db
    
    def create_document(
        self,
        case_id: str,
        user_id: str,
        title: str,
        content: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Document:
        """
        Create a new document
        
        Args:
            case_id: Case identifier
            user_id: User identifier
            title: Document title
            content: Initial HTML content (optional)
            metadata: Additional metadata (optional)
            
        Returns:
            Created Document object
        """
        # Verify case exists and user has access
        case = self.db.query(Case).filter(
            and_(Case.id == case_id, Case.user_id == user_id)
        ).first()
        
        if not case:
            raise ValueError(f"Case {case_id} not found or access denied")
        
        # Extract plain text from HTML for search
        content_plain = self._extract_plain_text(content)
        
        # Create document
        try:
            logger.info(f"Creating Document object: case_id={case_id}, user_id={user_id}, title={title[:50]}")
            document = Document(
                case_id=case_id,
                user_id=user_id,
                title=title,
                content=content or "",
                content_plain=content_plain,
                document_metadata=metadata or {},
                version=1
            )
            
            logger.info(f"Adding document to session...")
            self.db.add(document)
            logger.info(f"Committing to database...")
            self.db.commit()
            logger.info(f"Refreshing document...")
            self.db.refresh(document)
        except Exception as db_error:
            logger.error(f"Database error creating document: {db_error}", exc_info=True)
            self.db.rollback()
            raise
        
        logger.info(f"Created document {document.id} for case {case_id}")
        return document
    
    def get_document(self, document_id: str, user_id: str) -> Optional[Document]:
        """
        Get a document by ID
        
        Args:
            document_id: Document identifier
            user_id: User identifier (for access control)
            
        Returns:
            Document object or None if not found
        """
        document = self.db.query(Document).filter(
            and_(Document.id == document_id, Document.user_id == user_id)
        ).first()
        
        return document
    
    def update_document(
        self,
        document_id: str,
        user_id: str,
        content: str,
        title: Optional[str] = None,
        create_version: bool = True
    ) -> Document:
        """
        Update a document
        
        Args:
            document_id: Document identifier
            user_id: User identifier
            content: New HTML content
            title: New title (optional)
            create_version: Whether to create a version snapshot
            
        Returns:
            Updated Document object
        """
        document = self.get_document(document_id, user_id)
        
        if not document:
            raise ValueError(f"Document {document_id} not found or access denied")
        
        # Create version snapshot before update if requested
        if create_version:
            self._create_version(document, user_id)
        
        # Update document
        document.content = content
        document.content_plain = self._extract_plain_text(content)
        document.updated_at = datetime.utcnow()
        document.version += 1
        
        if title:
            document.title = title
        
        self.db.commit()
        self.db.refresh(document)
        
        logger.info(f"Updated document {document_id}, version {document.version}")
        return document
    
    def delete_document(self, document_id: str, user_id: str) -> bool:
        """
        Delete a document
        
        Args:
            document_id: Document identifier
            user_id: User identifier
            
        Returns:
            True if deleted, False if not found
        """
        document = self.get_document(document_id, user_id)
        
        if not document:
            return False
        
        self.db.delete(document)
        self.db.commit()
        
        logger.info(f"Deleted document {document_id}")
        return True
    
    def list_documents(
        self,
        case_id: str,
        user_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[Document]:
        """
        List documents for a case
        
        Args:
            case_id: Case identifier
            user_id: User identifier
            limit: Maximum number of documents to return
            offset: Offset for pagination
            
        Returns:
            List of Document objects
        """
        try:
            logger.info(f"Querying documents: case_id={case_id}, user_id={user_id}")
            documents = self.db.query(Document).filter(
                and_(
                    Document.case_id == case_id,
                    Document.user_id == user_id
                )
            ).order_by(desc(Document.updated_at)).offset(offset).limit(limit).all()
            logger.info(f"Query successful, found {len(documents)} documents")
            return documents
        except Exception as query_error:
            logger.error(f"Database error querying documents: {query_error}", exc_info=True)
            raise
    
    def _extract_plain_text(self, html_content: str) -> str:
        """
        Extract plain text from HTML content
        
        Args:
            html_content: HTML content
            
        Returns:
            Plain text
        """
        if not html_content:
            return ""
        
        try:
            # Remove HTML tags using regex (simple approach)
            # For production, consider using BeautifulSoup
            text = re.sub(r'<[^>]+>', '', html_content)
            # Decode HTML entities
            text = text.replace('&nbsp;', ' ')
            text = text.replace('&amp;', '&')
            text = text.replace('&lt;', '<')
            text = text.replace('&gt;', '>')
            text = text.replace('&quot;', '"')
            # Clean up whitespace
            text = ' '.join(text.split())
            return text[:5000]  # Limit length
        except Exception as e:
            logger.warning(f"Error extracting plain text: {e}")
            return ""
    
    def _create_version(self, document: Document, user_id: str) -> DocumentVersion:
        """
        Create a version snapshot of a document
        
        Args:
            document: Document to snapshot
            user_id: User creating the version
            
        Returns:
            Created DocumentVersion object
        """
        version = DocumentVersion(
            document_id=document.id,
            content=document.content,
            version=document.version,
            created_by=user_id
        )
        
        self.db.add(version)
        self.db.commit()
        self.db.refresh(version)
        
        return version
    
    def get_versions(
        self,
        document_id: str,
        user_id: str,
        limit: int = 50
    ) -> List[DocumentVersion]:
        """
        Get version history for a document
        
        Args:
            document_id: Document identifier
            user_id: User identifier (for access control)
            limit: Maximum number of versions to return
            
        Returns:
            List of DocumentVersion objects
        """
        # Verify document access
        document = self.get_document(document_id, user_id)
        if not document:
            return []
        
        versions = self.db.query(DocumentVersion).filter(
            DocumentVersion.document_id == document_id
        ).order_by(desc(DocumentVersion.version)).limit(limit).all()
        
        return versions
    
    def restore_version(
        self,
        document_id: str,
        user_id: str,
        version: int
    ) -> Document:
        """
        Restore a document to a specific version
        
        Args:
            document_id: Document identifier
            user_id: User identifier
            version: Version number to restore
            
        Returns:
            Restored Document object
        """
        document = self.get_document(document_id, user_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")
        
        # Find version
        version_record = self.db.query(DocumentVersion).filter(
            and_(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version == version
            )
        ).first()
        
        if not version_record:
            raise ValueError(f"Version {version} not found for document {document_id}")
        
        # Create new version snapshot before restore
        self._create_version(document, user_id)
        
        # Restore content
        document.content = version_record.content
        document.content_plain = self._extract_plain_text(version_record.content)
        document.version += 1
        document.updated_at = datetime.utcnow()
        
        self.db.commit()
        self.db.refresh(document)
        
        logger.info(f"Restored document {document_id} to version {version}")
        return document

