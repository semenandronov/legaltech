"""Legal text splitter optimized for legal documents"""
from typing import List, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
import logging

logger = logging.getLogger(__name__)


class LegalTextSplitter(RecursiveCharacterTextSplitter):
    """
    Text splitter optimized for legal documents
    
    Uses optimal chunk size and overlap for legal text, with specialized
    separators for legal document structure (paragraphs, sections, clauses).
    """
    
    def __init__(
        self,
        chunk_size: int = 1200,
        chunk_overlap: int = 300,
        separators: Optional[List[str]] = None,
        **kwargs
    ):
        """
        Initialize LegalTextSplitter
        
        Args:
            chunk_size: Maximum size of chunks (default: 1200 chars, optimal for legal docs)
            chunk_overlap: Overlap between chunks (default: 300 chars)
            separators: Custom separators (default: legal document structure)
            **kwargs: Additional arguments for RecursiveCharacterTextSplitter
        """
        # Legal document separators - optimized for legal structure
        if separators is None:
            separators = [
                "\n\n",      # Paragraphs
                "\n",        # Lines
                ". ",        # Sentences
                ";\n",       # Legal clauses (semicolon + newline)
                ")",         # Numbered lists and sections
                " ",         # Words
                ""           # Characters (fallback)
            ]
        
        super().__init__(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=separators,
            is_separator_regex=False,
            add_start_index=True,  # Enable start index for precise citation
            **kwargs
        )
        
        logger.debug(f"Initialized LegalTextSplitter: chunk_size={chunk_size}, chunk_overlap={chunk_overlap}")
    
    def split_documents_with_metadata(
        self,
        text: str,
        filename: str,
        metadata: Optional[dict] = None,
        page_num: Optional[int] = None,
        paragraph_num: Optional[int] = None
    ) -> List[Document]:
        """
        Split text into chunks with enhanced metadata for legal citation
        
        Args:
            text: Document text to split
            filename: Source filename
            metadata: Additional metadata
            page_num: Page number (if available)
            paragraph_num: Paragraph number (if available)
            
        Returns:
            List of Document objects with legal citation metadata
        """
        # Split text into chunks
        chunks = self.split_text(text)
        
        # Create Document objects with metadata
        documents = []
        base_metadata = {
            "source_file": filename,
            **(metadata or {})
        }
        
        if page_num is not None:
            base_metadata["source_page"] = page_num
        if paragraph_num is not None:
            base_metadata["source_paragraph"] = paragraph_num
        
        for i, chunk_text in enumerate(chunks):
            chunk_metadata = {
                **base_metadata,
                "chunk_index": i,
                "chunk_start_line": None,  # Will be calculated if possible
                "chunk_end_line": None,
            }
            
            # Try to extract start index from chunk if available
            # (requires add_start_index=True in RecursiveCharacterTextSplitter)
            # Note: This may require custom implementation or additional processing
            
            documents.append(Document(page_content=chunk_text, metadata=chunk_metadata))
        
        logger.debug(f"Split {len(text)} chars into {len(documents)} chunks for {filename}")
        return documents

