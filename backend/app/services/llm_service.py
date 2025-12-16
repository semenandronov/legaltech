"""LLM service wrapper for OpenRouter via LangChain"""
from typing import List, Dict, Any, Optional, Tuple
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.documents import Document
from app.config import config
import logging

logger = logging.getLogger(__name__)


class LLMService:
    """Service for LLM operations via OpenRouter"""
    
    def __init__(self):
        """Initialize LLM service"""
        self.llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.7,
            max_tokens=2000,
            timeout=60.0
        )
    
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> str:
        """
        Generate text using LLM
        
        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            temperature: Temperature for generation
            max_tokens: Maximum tokens
            
        Returns:
            Generated text
        """
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            response = self.llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"Ошибка при генерации через LLM: {e}")
            raise
    
    def generate_with_sources(
        self,
        system_prompt: str,
        user_prompt: str,
        documents: List[Document],
        temperature: float = 0.7
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Generate answer with source references
        
        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            documents: List of source documents
            temperature: Temperature for generation
            
        Returns:
            Tuple of (answer, sources)
        """
        # Format sources
        sources_text = self._format_sources_for_prompt(documents)
        
        # Update system prompt with sources
        full_system_prompt = f"""{system_prompt}

ВАЖНО: ВСЕГДА указывай конкретные источники в формате:
[Документ: filename.pdf, стр. 5, строки 12-15]

Источники:
{sources_text}
"""
        
        # Generate answer
        answer = self.generate(full_system_prompt, user_prompt, temperature)
        
        # Format sources
        sources = self._format_sources(documents)
        
        return answer, sources
    
    def _format_sources_for_prompt(self, documents: List[Document]) -> str:
        """Format sources as text for prompt"""
        formatted = []
        for i, doc in enumerate(documents, 1):
            metadata = doc.metadata
            source_file = metadata.get("source_file", "unknown")
            source_page = metadata.get("source_page")
            source_line = metadata.get("source_start_line")
            
            source_ref = f"[Источник {i}: {source_file}"
            if source_page:
                source_ref += f", стр. {source_page}"
            if source_line:
                source_ref += f", строка {source_line}"
            source_ref += "]"
            
            formatted.append(f"{source_ref}\n{doc.page_content}")
        
        return "\n\n".join(formatted)
    
    def _format_sources(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """Format source documents"""
        sources = []
        for doc in documents:
            metadata = doc.metadata
            source = {
                "file": metadata.get("source_file", "unknown"),
                "page": metadata.get("source_page"),
                "chunk_index": metadata.get("chunk_index"),
                "start_line": metadata.get("source_start_line"),
                "end_line": metadata.get("source_end_line"),
                "text_preview": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content,
                "similarity_score": metadata.get("similarity_score")
            }
            sources.append(source)
        return sources

