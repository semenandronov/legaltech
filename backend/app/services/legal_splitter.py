"""Legal text splitter optimized for legal documents"""
from typing import List, Optional
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
import logging
import hashlib

logger = logging.getLogger(__name__)


def generate_chunk_id(doc_id: str, chunk_index: int, char_start: int) -> str:
    """
    Generate a unique, deterministic chunk_id for reliable citation linking.
    
    Format: {doc_id_short}_{chunk_index}_{char_start_hash}
    Example: "abc123_0_f7d2" for first chunk of document abc123
    
    This ID is:
    - Deterministic: same content always produces same ID
    - Unique: different chunks have different IDs
    - Short: suitable for use in prompts and UI
    """
    # Create a hash of doc_id + chunk_index + char_start for uniqueness
    hash_input = f"{doc_id}:{chunk_index}:{char_start}"
    hash_short = hashlib.md5(hash_input.encode()).hexdigest()[:6]
    
    # Use first 8 chars of doc_id for readability
    doc_id_short = doc_id[:8] if len(doc_id) > 8 else doc_id
    
    return f"{doc_id_short}_{chunk_index}_{hash_short}"


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
            List of Document objects with legal citation metadata including char_start/char_end
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
        
        # Calculate char_start and char_end for each chunk
        previous_end = 0
        for i, chunk_text in enumerate(chunks):
            # Find the start position of this chunk in the original text
            # Start searching from previous_end to handle overlaps correctly
            char_start = text.find(chunk_text, previous_end)
            
            # If not found, try searching from the beginning (shouldn't happen normally)
            if char_start == -1:
                char_start = text.find(chunk_text)
                if char_start == -1:
                    # Fallback: estimate position (shouldn't happen with proper splitting)
                    char_start = previous_end
                    logger.warning(f"Could not find chunk {i} in text, using estimated position")
            
            char_end = char_start + len(chunk_text)
            previous_end = max(previous_end, char_start)  # Update for next iteration
            
            # Generate unique chunk_id for reliable citation linking
            doc_id = base_metadata.get("doc_id", base_metadata.get("source_id", filename))
            chunk_id = generate_chunk_id(str(doc_id), i, char_start)
            
            chunk_metadata = {
                **base_metadata,
                "chunk_id": chunk_id,  # Unique ID for this chunk - used for citation linking
                "chunk_index": i,
                "chunk_start_line": None,  # Line numbers not calculated here
                "chunk_end_line": None,
                "char_start": char_start,  # Character start position for citation
                "char_end": char_end,  # Character end position for citation
            }
            
            documents.append(Document(page_content=chunk_text, metadata=chunk_metadata))
        
        logger.debug(f"Split {len(text)} chars into {len(documents)} chunks for {filename} with chunk_ids and char offsets")
        return documents




