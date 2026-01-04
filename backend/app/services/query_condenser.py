"""Query Condenser Service - Phase 1.3 Implementation

This module provides query condensation/rewriting functionality
for improving RAG retrieval quality.

Features:
- Query condensation for clearer retrieval
- Query expansion with synonyms
- Multi-query generation for diverse retrieval
- Context-aware query rewriting
"""
from typing import List, Optional, Dict, Any
from app.config import config
import logging

logger = logging.getLogger(__name__)


class QueryCondenserService:
    """
    Service for condensing and rewriting queries for better RAG retrieval.
    
    Simplifies complex queries and generates alternative formulations
    to improve document retrieval quality.
    """
    
    def __init__(self, llm=None):
        """
        Initialize the query condenser service.
        
        Args:
            llm: Optional LLM instance for query rewriting
        """
        self._llm = llm
    
    def _get_llm(self):
        """Get or create LLM instance."""
        if self._llm is None:
            try:
                from app.services.llm_factory import create_llm
                self._llm = create_llm(temperature=0.0)
            except Exception as e:
                logger.warning(f"Failed to initialize LLM for query condensation: {e}")
        return self._llm
    
    def condense_query(
        self,
        query: str,
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """
        Condense a query based on chat history into a standalone question.
        
        Args:
            query: The current user query
            chat_history: Optional list of previous messages
            
        Returns:
            Condensed standalone query
        """
        # If no history, return original query
        if not chat_history or len(chat_history) == 0:
            return query
        
        llm = self._get_llm()
        if not llm:
            return query
        
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            # Build history context
            history_text = ""
            for msg in chat_history[-5:]:  # Last 5 messages
                role = msg.get("role", "user")
                content = msg.get("content", "")
                history_text += f"{role}: {content}\n"
            
            prompt = f"""Преобразуй последний вопрос в самостоятельный вопрос, учитывая контекст разговора.

История разговора:
{history_text}

Текущий вопрос: {query}

Преобразуй вопрос так, чтобы он был понятен без контекста разговора.
Если вопрос уже самостоятельный - верни его без изменений.
Ответь только переформулированным вопросом, без пояснений."""
            
            response = llm.invoke([
                SystemMessage(content="Ты помощник для переформулирования вопросов."),
                HumanMessage(content=prompt)
            ])
            
            condensed = response.content.strip() if hasattr(response, 'content') else str(response).strip()
            
            # Validate result
            if len(condensed) > 0 and len(condensed) < len(query) * 3:
                logger.debug(f"Condensed query: '{query[:50]}...' → '{condensed[:50]}...'")
                return condensed
            
            return query
            
        except Exception as e:
            logger.warning(f"Query condensation failed: {e}")
            return query
    
    def expand_query(self, query: str, max_expansions: int = 3) -> List[str]:
        """
        Expand query with synonyms and related terms.
        
        Args:
            query: The original query
            max_expansions: Maximum number of expanded queries
            
        Returns:
            List of expanded queries (including original)
        """
        llm = self._get_llm()
        if not llm:
            return [query]
        
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            prompt = f"""Создай {max_expansions} альтернативных формулировок для следующего поискового запроса.

Запрос: {query}

Требования:
- Сохрани смысл оригинального запроса
- Используй синонимы и альтернативные термины
- Каждая формулировка на отдельной строке
- Не добавляй нумерацию или пояснения"""
            
            response = llm.invoke([
                SystemMessage(content="Ты помощник для расширения поисковых запросов."),
                HumanMessage(content=prompt)
            ])
            
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Parse expansions
            expansions = [query]  # Original first
            for line in content.strip().split('\n'):
                line = line.strip()
                # Remove numbering if present
                if line and len(line) > 3:
                    # Remove patterns like "1.", "1)", "- "
                    import re
                    cleaned = re.sub(r'^[\d\.\-\)\s]+', '', line).strip()
                    if cleaned and cleaned != query and cleaned not in expansions:
                        expansions.append(cleaned)
            
            return expansions[:max_expansions + 1]  # Original + expansions
            
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}")
            return [query]
    
    def generate_multi_queries(self, query: str, num_queries: int = 3) -> List[str]:
        """
        Generate multiple diverse queries for ensemble retrieval.
        
        Args:
            query: The original query
            num_queries: Number of queries to generate
            
        Returns:
            List of diverse queries
        """
        llm = self._get_llm()
        if not llm:
            return [query]
        
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            
            prompt = f"""Для улучшения поиска по юридическим документам, создай {num_queries} разных формулировок следующего вопроса.

Оригинальный вопрос: {query}

Каждая формулировка должна:
1. Сохранять смысл оригинального вопроса
2. Использовать разные слова и структуру
3. Быть на русском языке
4. Быть на отдельной строке без нумерации"""
            
            response = llm.invoke([
                SystemMessage(content="Ты эксперт по поисковым запросам для юридических документов."),
                HumanMessage(content=prompt)
            ])
            
            content = response.content if hasattr(response, 'content') else str(response)
            
            queries = [query]  # Original first
            for line in content.strip().split('\n'):
                line = line.strip()
                if line and len(line) > 5:
                    import re
                    cleaned = re.sub(r'^[\d\.\-\)\s]+', '', line).strip()
                    if cleaned and cleaned != query and cleaned not in queries:
                        queries.append(cleaned)
            
            return queries[:num_queries + 1]
            
        except Exception as e:
            logger.warning(f"Multi-query generation failed: {e}")
            return [query]
    
    def simplify_for_retrieval(self, query: str) -> str:
        """
        Simplify query for better retrieval (remove noise, focus on key terms).
        
        Args:
            query: The original query
            
        Returns:
            Simplified query
        """
        # Simple rule-based simplification without LLM
        import re
        
        # Remove common question words
        noise_words = [
            "пожалуйста", "можете", "могли бы", "хотел бы",
            "подскажите", "скажите", "расскажите", "объясните",
            "please", "could you", "can you", "tell me"
        ]
        
        simplified = query.lower()
        for word in noise_words:
            simplified = simplified.replace(word, "")
        
        # Remove excessive whitespace
        simplified = re.sub(r'\s+', ' ', simplified).strip()
        
        # If too short, return original
        if len(simplified) < 10:
            return query
        
        return simplified
    
    def extract_key_terms(self, query: str) -> List[str]:
        """
        Extract key terms from query for keyword-based retrieval.
        
        Args:
            query: The original query
            
        Returns:
            List of key terms
        """
        import re
        
        # Remove punctuation
        text = re.sub(r'[^\w\s]', ' ', query.lower())
        
        # Tokenize
        words = text.split()
        
        # Russian stop words
        stop_words = {
            'и', 'в', 'во', 'не', 'что', 'он', 'на', 'я', 'с', 'со', 'как',
            'а', 'то', 'все', 'она', 'так', 'его', 'но', 'да', 'ты', 'к',
            'у', 'же', 'вы', 'за', 'бы', 'по', 'только', 'её', 'мне',
            'было', 'вот', 'от', 'меня', 'ещё', 'нет', 'о', 'из', 'ему',
            'теперь', 'когда', 'уже', 'вам', 'ни', 'быть', 'был', 'него',
            'до', 'вас', 'нибудь', 'опять', 'уж', 'там', 'то', 'этот',
            'который', 'какой', 'чтобы', 'для', 'при', 'это'
        }
        
        # Filter
        key_terms = [w for w in words if len(w) > 2 and w not in stop_words]
        
        return key_terms


# Global service instance
_condenser: Optional[QueryCondenserService] = None


def get_query_condenser() -> QueryCondenserService:
    """Get or create the global query condenser service instance."""
    global _condenser
    
    if _condenser is None:
        _condenser = QueryCondenserService()
    
    return _condenser

