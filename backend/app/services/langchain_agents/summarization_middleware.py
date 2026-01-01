"""Summarization Middleware for automatic content summarization (inspired by Deep Agents)"""
from typing import Optional
from app.services.llm_factory import create_llm
import logging

logger = logging.getLogger(__name__)


class SummarizationMiddleware:
    """
    Middleware для авто-суммаризации больших контекстов (вдохновлено Deep Agents)
    
    Автоматически суммаризирует контент, если он превышает лимит токенов,
    чтобы предотвратить переполнение контекста LLM.
    """
    
    def __init__(self, llm=None, max_tokens: int = 100000):
        """
        Initialize summarization middleware
        
        Args:
            llm: LLM instance for summarization (optional, will create if not provided)
            max_tokens: Maximum tokens before summarization (default: 100000)
        """
        self.llm = llm or create_llm(temperature=0.1)
        self.max_tokens = max_tokens
        
        logger.debug(f"SummarizationMiddleware initialized with max_tokens={max_tokens}")
    
    def estimate_tokens(self, content: str) -> int:
        """
        Оценить количество токенов в контенте
        
        Args:
            content: Text content
            
        Returns:
            Estimated token count
        """
        # Rough estimation: ~4 characters per token for most languages
        # For Russian/Cyrillic, might be slightly different
        return len(content) // 4
    
    def summarize_if_needed(self, content: str, context: Optional[str] = None) -> str:
        """
        Суммаризировать контент если он слишком большой
        
        Args:
            content: Content to potentially summarize
            context: Optional context for summarization
            
        Returns:
            Original content or summary
        """
        estimated_tokens = self.estimate_tokens(content)
        
        if estimated_tokens <= self.max_tokens:
            # Content is within limit, return as-is
            return content
        
        logger.info(
            f"Content exceeds token limit ({estimated_tokens} > {self.max_tokens}), "
            "summarizing..."
        )
        
        try:
            # Create summarization prompt
            summary_prompt = f"""Суммаризируй следующий текст, сохраняя все ключевые факты и важную информацию:

{content[:50000]}  # Limit to first 50k chars to avoid token limits

Создай краткое, но полное резюме, которое сохраняет:
- Все ключевые факты
- Важные даты и события
- Существенные детали
- Основные выводы

Резюме:"""
            
            if context:
                summary_prompt = f"""Контекст: {context}

{summary_prompt}"""
            
            # Call LLM for summarization
            from langchain_core.messages import HumanMessage
            response = self.llm.invoke([HumanMessage(content=summary_prompt)])
            
            summary = response.content if hasattr(response, 'content') else str(response)
            
            logger.info(f"Summarized content: {len(content)} -> {len(summary)} characters")
            return summary
            
        except Exception as e:
            logger.warning(f"Error during summarization: {e}, returning original content")
            # Return truncated content as fallback
            max_chars = self.max_tokens * 4  # Convert tokens to chars
            return content[:max_chars] + "\n\n[... content truncated ...]"
    
    def summarize_documents(self, documents: list, max_docs: int = 50) -> str:
        """
        Суммаризировать список документов
        
        Args:
            documents: List of document objects or strings
            max_docs: Maximum number of documents to include before summarizing
            
        Returns:
            Summarized document content
        """
        if not documents:
            return ""
        
        # Extract text from documents
        texts = []
        for doc in documents[:max_docs]:
            if hasattr(doc, 'page_content'):
                texts.append(doc.page_content)
            elif hasattr(doc, 'content'):
                texts.append(doc.content)
            elif isinstance(doc, str):
                texts.append(doc)
            else:
                texts.append(str(doc))
        
        combined_text = "\n\n".join(texts)
        
        # Check if summarization is needed
        return self.summarize_if_needed(combined_text, context="Document collection")
    
    def summarize_state(self, state: dict, fields: Optional[list] = None) -> dict:
        """
        Суммаризировать большие поля в state
        
        Args:
            state: State dictionary
            fields: Optional list of field names to summarize (if None, summarizes all large text fields)
            
        Returns:
            State with summarized fields
        """
        summarized_state = state.copy()
        
        # Default fields to check for summarization
        if fields is None:
            fields = [
                "timeline_result", "key_facts_result", "discrepancy_result",
                "risk_result", "summary_result", "context", "user_task"
            ]
        
        for field in fields:
            if field in summarized_state:
                value = summarized_state[field]
                
                # Check if value is a large string or dict with large text
                if isinstance(value, str):
                    if self.estimate_tokens(value) > self.max_tokens:
                        summarized_state[field] = self.summarize_if_needed(value, context=field)
                elif isinstance(value, dict):
                    # Summarize large text fields in dict
                    for key, val in value.items():
                        if isinstance(val, str) and self.estimate_tokens(val) > self.max_tokens:
                            value[key] = self.summarize_if_needed(val, context=f"{field}.{key}")
        
        return summarized_state

