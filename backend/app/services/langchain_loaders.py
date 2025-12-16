"""LangChain document loaders for Legal AI Vault"""
from typing import List, Dict, Any, Optional
from langchain_community.document_loaders import (
    PyPDFLoader,
    UnstructuredWordDocumentLoader,
    TextLoader,
    CSVLoader,
)
from langchain_core.documents import Document
from app.config import config
import logging
import io
import tempfile
import os

logger = logging.getLogger(__name__)


class DocumentLoaderService:
    """Service for loading documents using LangChain loaders"""
    
    @staticmethod
    def load_pdf(content: bytes, filename: str) -> List[Document]:
        """
        Load PDF document using PyPDFLoader
        
        Args:
            content: PDF file content as bytes
            filename: Original filename
            
        Returns:
            List of Document objects with metadata
        """
        try:
            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name
            
            try:
                loader = PyPDFLoader(tmp_path)
                documents = loader.load()
                
                # Add filename to metadata
                for doc in documents:
                    if not doc.metadata.get("source"):
                        doc.metadata["source_file"] = filename
                    else:
                        # Extract page number from source if available
                        source = doc.metadata.get("source", "")
                        if "page" in source.lower():
                            try:
                                # PyPDFLoader adds page info to source
                                page_num = int(source.split("page")[-1].strip())
                                doc.metadata["source_page"] = page_num
                            except:
                                pass
                        doc.metadata["source_file"] = filename
                
                logger.info(f"Loaded PDF {filename}: {len(documents)} pages")
                return documents
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"Error loading PDF {filename}: {e}")
            raise
    
    @staticmethod
    def load_docx(content: bytes, filename: str) -> List[Document]:
        """
        Load DOCX document using UnstructuredWordDocumentLoader
        
        Args:
            content: DOCX file content as bytes
            filename: Original filename
            
        Returns:
            List of Document objects with metadata
        """
        try:
            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name
            
            try:
                # Try UnstructuredWordDocumentLoader first (better structure preservation)
                try:
                    loader = UnstructuredWordDocumentLoader(tmp_path, mode="elements")
                    documents = loader.load()
                except Exception:
                    # Fallback to simple text extraction
                    from docx import Document as DocxDocument
                    doc = DocxDocument(io.BytesIO(content))
                    text = "\n".join([para.text for para in doc.paragraphs])
                    documents = [Document(page_content=text, metadata={"source_file": filename})]
                
                # Add filename to metadata
                for doc in documents:
                    if "source_file" not in doc.metadata:
                        doc.metadata["source_file"] = filename
                
                logger.info(f"Loaded DOCX {filename}: {len(documents)} elements")
                return documents
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"Error loading DOCX {filename}: {e}")
            raise
    
    @staticmethod
    def load_txt(content: bytes, filename: str) -> List[Document]:
        """
        Load text document using TextLoader
        
        Args:
            content: Text file content as bytes
            filename: Original filename
            
        Returns:
            List of Document objects with metadata
        """
        try:
            # Decode content
            try:
                text_content = content.decode('utf-8')
            except UnicodeDecodeError:
                text_content = content.decode('latin-1')
            
            # Save to temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as tmp_file:
                tmp_file.write(text_content)
                tmp_path = tmp_file.name
            
            try:
                loader = TextLoader(tmp_path, encoding='utf-8')
                documents = loader.load()
                
                # Add filename to metadata
                for doc in documents:
                    doc.metadata["source_file"] = filename
                
                logger.info(f"Loaded TXT {filename}: {len(documents)} documents")
                return documents
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"Error loading TXT {filename}: {e}")
            raise
    
    @staticmethod
    def load_xlsx(content: bytes, filename: str) -> List[Document]:
        """
        Load Excel document (convert to text format)
        
        Args:
            content: XLSX file content as bytes
            filename: Original filename
            
        Returns:
            List of Document objects with metadata
        """
        try:
            from openpyxl import load_workbook
            
            # Load workbook
            workbook = load_workbook(io.BytesIO(content), data_only=True)
            
            documents = []
            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                
                # Extract text from cells
                rows_text = []
                for row in sheet.iter_rows(values_only=True):
                    row_text = " | ".join([str(cell) if cell is not None else "" for cell in row])
                    if row_text.strip():
                        rows_text.append(row_text)
                
                if rows_text:
                    sheet_text = "\n".join(rows_text)
                    doc = Document(
                        page_content=sheet_text,
                        metadata={
                            "source_file": filename,
                            "sheet_name": sheet_name,
                            "source_type": "excel"
                        }
                    )
                    documents.append(doc)
            
            logger.info(f"Loaded XLSX {filename}: {len(documents)} sheets")
            return documents
        except Exception as e:
            logger.error(f"Error loading XLSX {filename}: {e}")
            raise
    
    @staticmethod
    def load_document(content: bytes, filename: str) -> List[Document]:
        """
        Load document based on file extension
        
        Args:
            content: File content as bytes
            filename: Original filename
            
        Returns:
            List of Document objects with metadata
        """
        # Get file extension
        _, ext = os.path.splitext(filename)
        ext = ext.lower()
        
        if ext == '.pdf':
            return DocumentLoaderService.load_pdf(content, filename)
        elif ext in ['.docx', '.doc']:
            return DocumentLoaderService.load_docx(content, filename)
        elif ext == '.txt':
            return DocumentLoaderService.load_txt(content, filename)
        elif ext in ['.xlsx', '.xls']:
            return DocumentLoaderService.load_xlsx(content, filename)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

