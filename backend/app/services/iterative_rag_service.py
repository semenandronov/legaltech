"""Iterative RAG service with adaptive search (inspired by Open Deep Research)"""
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage
from app.services.rag_service import RAGService
from app.services.llm_factory import create_llm
from app.config import config
import logging
import time

logger = logging.getLogger(__name__)


class IterativeRAGService:
    """Итеративный RAG с адаптивным поиском и переформулировкой запросов"""
    
    def __init__(self, rag_service: RAGService):
        """Initialize iterative RAG service
        
        Args:
            rag_service: Base RAG service instance
        """
        self.rag_service = rag_service
        self.llm = create_llm(temperature=0.3)  # Немного выше для переформулировки
    
    def retrieve_iteratively(
        self,
        case_id: str,
        query: str,
        max_iterations: int = 3,
        initial_k: int = 5,
        db: Optional[Session] = None,
        min_relevance_score: float = 0.5,
        use_reranker: bool = False
    ) -> List[Document]:
        """
        Итеративный поиск с переформулировкой запроса при необходимости
        
        Args:
            case_id: Case identifier
            query: Original search query
            max_iterations: Maximum number of search iterations
            initial_k: Initial number of documents to retrieve
            db: Optional database session
            min_relevance_score: Minimum relevance score threshold
            
        Returns:
            List of relevant documents
        """
        documents = []
        current_query = query
        k = initial_k
        seen_docs = set()  # Для дедупликации
        previous_queries = []  # Для контекста переформулировки
        adaptive_threshold = min_relevance_score  # Адаптивный порог релевантности
        
        logger.info(f"Iterative RAG: Starting search for case {case_id}, query: {query[:100]}...")
        
        for iteration in range(max_iterations):
            logger.debug(f"Iteration {iteration + 1}/{max_iterations}: Searching with k={k}, query: {current_query[:100]}...")
            
            # Поиск с текущим запросом
            docs = self.rag_service.retrieve_context(
                case_id=case_id,
                query=current_query,
                k=k,
                retrieval_strategy="multi_query",
                db=db
            )
            
            if not docs:
                logger.warning(f"Iteration {iteration + 1}: No documents found")
                if iteration < max_iterations - 1:
                    # Переформулировать запрос с учетом предыдущих попыток
                    current_query = self._reformulate_query(query, [], iteration + 1, previous_queries)
                    previous_queries.append(current_query)
                    k = min(k * 2, 30)  # Увеличиваем k
                    # Понижаем порог релевантности если не находим документы
                    adaptive_threshold = max(0.3, adaptive_threshold - 0.1)
                    continue
                else:
                    break
            
            # Проверка релевантности с LLM-оценкой или reranker для лучшего качества
            if use_reranker:
                relevant_docs, quality_score = self._filter_relevant_with_reranker(docs, query, adaptive_threshold)
            else:
                relevant_docs, quality_score = self._filter_relevant_with_llm(docs, query, adaptive_threshold)
            
            # Метрика качества найденных документов (0.0-1.0)
            logger.info(f"Iteration {iteration + 1}: Quality score: {quality_score:.2f}, Relevant docs: {len(relevant_docs)}/{len(docs)}")
            
            # Ранняя остановка если качество достаточно высокое (>85%)
            if quality_score >= 0.85:
                logger.info(f"Iteration {iteration + 1}: High quality score ({quality_score:.2f} >= 0.85), stopping early")
                # Добавляем найденные документы
                for doc in relevant_docs:
                    doc_hash = self._get_doc_hash(doc)
                    if doc_hash not in seen_docs:
                        seen_docs.add(doc_hash)
                        documents.append(doc)
                break
            
            # Адаптируем порог на основе результатов
            if len(relevant_docs) < len(docs) * 0.5:
                # Много нерелевантных - понижаем порог
                adaptive_threshold = max(0.3, adaptive_threshold - 0.05)
            elif len(relevant_docs) == len(docs):
                # Все релевантные - можем повысить порог
                adaptive_threshold = min(0.9, adaptive_threshold + 0.05)
            
            # Добавляем релевантные документы (без дубликатов)
            for doc in relevant_docs:
                doc_hash = self._get_doc_hash(doc)
                if doc_hash not in seen_docs:
                    seen_docs.add(doc_hash)
                    documents.append(doc)
            
            # Проверяем, достаточно ли документов найдено с хорошим качеством
            if len(documents) >= k * 0.7 and quality_score >= 0.7:  # Нашли 70% и качество >= 70%
                logger.info(f"Iteration {iteration + 1}: Found sufficient documents ({len(documents)}) with good quality ({quality_score:.2f}), stopping")
                break
            
            # Если нашли достаточно релевантных документов - останавливаемся
            if len(documents) >= initial_k and quality_score >= 0.75:
                logger.info(f"Iterative RAG: Found {len(documents)} relevant documents with quality {quality_score:.2f} after {iteration + 1} iterations")
                break
            
            # Если это не последняя итерация - переформулируем запрос
            if iteration < max_iterations - 1:
                current_query = self._reformulate_query(query, docs, iteration + 1, previous_queries)
                previous_queries.append(current_query)
                k = min(k * 2, 30)  # Увеличиваем k для следующей итерации
                logger.info(f"Iteration {iteration + 1}: Reformulated query: {current_query[:100]}..., increasing k to {k}, threshold: {adaptive_threshold:.2f}")
        
        # Ограничиваем результат
        result = documents[:initial_k * 2]
        logger.info(f"Iterative RAG: Final result: {len(result)} documents for case {case_id}")
        return result
    
    def _is_relevant(
        self,
        documents: List[Document],
        original_query: str,
        min_relevance_score: float = 0.5
    ) -> bool:
        """
        Проверяет, являются ли найденные документы релевантными
        
        Args:
            documents: List of documents to check
            original_query: Original search query
            min_relevance_score: Minimum relevance score
            
        Returns:
            True if documents are relevant
        """
        if not documents:
            return False
        
        # Проверяем similarity scores если доступны
        relevant_count = 0
        for doc in documents:
            metadata = doc.metadata if hasattr(doc, 'metadata') else {}
            similarity_score = metadata.get('similarity_score')
            
            # Если есть similarity_score, используем его
            if similarity_score is not None:
                # Для pgvector: меньший score = лучше (distance)
                # Преобразуем в relevance (1 - normalized_distance)
                if isinstance(similarity_score, (int, float)):
                    # Если score < 1.0, это хороший результат
                    if similarity_score < 1.0:
                        relevant_count += 1
            else:
                # Если нет score, считаем документ релевантным
                relevant_count += 1
        
        # Считаем релевантными, если хотя бы половина документов релевантна
        relevance_ratio = relevant_count / len(documents) if documents else 0
        return relevance_ratio >= min_relevance_score
    
    def _filter_relevant(
        self,
        documents: List[Document],
        original_query: str,
        min_relevance_score: float = 0.5
    ) -> List[Document]:
        """Фильтрует документы по релевантности (старый метод, используется как fallback)"""
        relevant = []
        
        for doc in documents:
            metadata = doc.metadata if hasattr(doc, 'metadata') else {}
            similarity_score = metadata.get('similarity_score')
            
            # Если есть similarity_score, проверяем его
            if similarity_score is not None:
                if isinstance(similarity_score, (int, float)):
                    # Для pgvector: меньший score = лучше
                    if similarity_score < 1.0:  # Порог для релевантности
                        relevant.append(doc)
            else:
                # Если нет score, считаем релевантным
                relevant.append(doc)
        
        return relevant
    
    def _filter_relevant_with_reranker(
        self,
        documents: List[Document],
        original_query: str,
        min_relevance_score: float = 0.5
    ) -> Tuple[List[Document], float]:
        """
        Фильтрует документы по релевантности с использованием cross-encoder reranker
        
        Args:
            documents: List of documents to filter
            original_query: Original search query
            min_relevance_score: Minimum relevance score threshold
            
        Returns:
            Tuple of (filtered documents, quality_score 0.0-1.0)
        """
        try:
            # Try to use cross-encoder reranker if available
            try:
                from sentence_transformers import CrossEncoder
                
                # Initialize reranker (lazy loading)
                if not hasattr(self, '_reranker'):
                    self._reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
                    logger.info("✅ Cross-encoder reranker initialized")
                
                # Prepare pairs for reranking
                pairs = [[original_query, doc.page_content[:512]] for doc in documents]  # Limit content length
                
                # Get relevance scores
                scores = self._reranker.predict(pairs)
                
                # Filter documents by scores
                relevant = []
                quality_scores = []
                for doc, score in zip(documents, scores):
                    quality_scores.append(float(score))
                    if score >= min_relevance_score:
                        relevant.append(doc)
                
                avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.5
                logger.debug(f"Reranker evaluation: {len(relevant)}/{len(documents)} relevant, avg quality: {avg_quality:.2f}")
                return relevant, avg_quality
                
            except ImportError:
                logger.warning("sentence-transformers not available, falling back to LLM evaluation")
                return self._filter_relevant_with_llm(documents, original_query, min_relevance_score)
            except Exception as e:
                logger.warning(f"Error using reranker: {e}, falling back to LLM evaluation")
                return self._filter_relevant_with_llm(documents, original_query, min_relevance_score)
        except Exception as e:
            logger.warning(f"Error in reranker evaluation: {e}, using simple filtering")
            relevant = self._filter_relevant(documents, original_query, min_relevance_score)
            quality_score = len(relevant) / len(documents) if documents else 0.0
            return relevant, quality_score
    
    def _filter_relevant_with_llm(
        self,
        documents: List[Document],
        original_query: str,
        min_relevance_score: float = 0.5
    ) -> Tuple[List[Document], float]:
        """
        Фильтрует документы по релевантности с использованием LLM для оценки качества
        
        Args:
            documents: List of documents to filter
            original_query: Original search query
            min_relevance_score: Minimum relevance score threshold
            
        Returns:
            Tuple of (filtered documents, quality_score 0.0-1.0)
        """
        # Check if LLM evaluation is enabled
        if not config.RAG_LLM_EVALUATION_ENABLED:
            logger.debug("LLM evaluation disabled, using similarity score fallback")
            return self._filter_relevant_with_similarity(documents, original_query, min_relevance_score)
        
        try:
            start_time = time.time()
            # Если документов мало, используем простую фильтрацию
            if len(documents) <= 3:
                relevant = self._filter_relevant(documents, original_query, min_relevance_score)
                quality_score = len(relevant) / len(documents) if documents else 0.0
                return relevant, quality_score
            
            # Используем LLM для оценки релевантности первых N документов
            docs_to_evaluate = documents[:10]  # Оцениваем первые 10
            
            evaluation_prompt = f"""Ты эксперт по оценке релевантности документов для юридического поиска.

Запрос пользователя: {original_query}

Оцени релевантность каждого документа (0.0 = нерелевантен, 1.0 = очень релевантен).

Документы:
{chr(10).join([f"{i+1}. {doc.page_content[:300]}..." for i, doc in enumerate(docs_to_evaluate)])}

Верни JSON массив оценок: [0.85, 0.92, 0.45, ...] (одно число для каждого документа в порядке).
"""
            
            messages = [
                SystemMessage(content="Ты эксперт по оценке релевантности документов. Верни только JSON массив чисел от 0.0 до 1.0."),
                HumanMessage(content=evaluation_prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content.strip() if hasattr(response, 'content') else str(response).strip()
            
            # Парсим оценки
            import json
            import re
            # Извлекаем JSON массив
            json_match = re.search(r'\[[\d\.,\s]+\]', response_text)
            if json_match:
                scores = json.loads(json_match.group())
            else:
                # Fallback: используем простую фильтрацию
                relevant = self._filter_relevant(documents, original_query, min_relevance_score)
                quality_score = len(relevant) / len(documents) if documents else 0.0
                return relevant, quality_score
            
            # Фильтруем документы по оценкам
            relevant = []
            quality_scores = []
            
            for i, doc in enumerate(docs_to_evaluate):
                score = scores[i] if i < len(scores) else 0.5
                quality_scores.append(score)
                if score >= min_relevance_score:
                    relevant.append(doc)
            
            # Добавляем остальные документы с простой фильтрацией
            for doc in documents[10:]:
                relevant_simple = self._filter_relevant([doc], original_query, min_relevance_score)
                if relevant_simple:
                    relevant.append(doc)
                    quality_scores.append(0.7)  # Средняя оценка для неоцененных
            
            # Вычисляем средний quality score
            avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.5
            
            elapsed_time = time.time() - start_time
            logger.info(
                f"LLM relevance evaluation: {len(relevant)}/{len(documents)} relevant, "
                f"avg quality: {avg_quality:.2f}, time: {elapsed_time:.2f}s, "
                f"query: {original_query[:50]}..."
            )
            return relevant, avg_quality
            
        except Exception as e:
            logger.warning(f"Error in LLM relevance evaluation: {e}, using similarity score fallback")
            # Fallback на фильтрацию по similarity_score
            return self._filter_relevant_with_similarity(documents, original_query, min_relevance_score)
    
    def _filter_relevant_with_similarity(
        self,
        documents: List[Document],
        original_query: str,
        min_relevance_score: float = 0.5
    ) -> Tuple[List[Document], float]:
        """
        Фильтрует документы по similarity_score из metadata (fallback метод)
        
        Args:
            documents: List of documents to filter
            original_query: Original search query (not used, kept for API compatibility)
            min_relevance_score: Minimum relevance score threshold
            
        Returns:
            Tuple of (filtered documents, quality_score 0.0-1.0)
        """
        relevant = []
        quality_scores = []
        
        for doc in documents:
            metadata = doc.metadata if hasattr(doc, 'metadata') else {}
            similarity_score = metadata.get('similarity_score')
            
            # Если есть similarity_score, используем его
            if similarity_score is not None:
                if isinstance(similarity_score, (int, float)):
                    # Для pgvector: меньший score = лучше (distance)
                    # Преобразуем в relevance (1 - normalized_distance)
                    # Если score < 1.0, это хороший результат
                    relevance = 1.0 - min(similarity_score, 1.0) if similarity_score < 1.0 else 0.0
                    quality_scores.append(relevance)
                    if relevance >= min_relevance_score:
                        relevant.append(doc)
                else:
                    # Если score не число, считаем релевантным
                    relevant.append(doc)
                    quality_scores.append(0.7)
            else:
                # Если нет score, считаем релевантным (fallback)
                relevant.append(doc)
                quality_scores.append(0.7)
        
        avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0.5
        logger.debug(f"Similarity score filtering: {len(relevant)}/{len(documents)} relevant, avg quality: {avg_quality:.2f}")
        return relevant, avg_quality
    
    def _reformulate_query(
        self,
        original_query: str,
        found_documents: List[Document],
        iteration: int,
        previous_queries: Optional[List[str]] = None
    ) -> str:
        """
        Переформулирует запрос на основе найденных документов и предыдущих итераций
        
        Args:
            original_query: Original search query
            found_documents: Documents found in previous iteration
            iteration: Current iteration number
            previous_queries: List of previous reformulated queries (for context)
            
        Returns:
            Reformulated query
        """
        try:
            # Если документы не найдены - используем более общий запрос
            if not found_documents:
                # Multi-step query expansion: генерируем несколько вариантов
                if iteration == 1 and not previous_queries:
                    # Первая итерация - генерируем расширенные варианты
                    expansion_prompt = f"""Ты эксперт по поиску в юридических документах.

Оригинальный запрос: {original_query}

Создай 3 варианта расширенного запроса:
1. С синонимами юридических терминов
2. С более широкими понятиями
3. С альтернативными формулировками

Верни только 3 варианта, каждый с новой строки, без нумерации."""
                    
                    messages = [
                        SystemMessage(content="Ты эксперт по расширению поисковых запросов для юридических документов."),
                        HumanMessage(content=expansion_prompt)
                    ]
                    
                    response = self.llm.invoke(messages)
                    expansion_text = response.content.strip() if hasattr(response, 'content') else str(response).strip()
                    
                    # Парсим варианты
                    queries = [q.strip() for q in expansion_text.split('\n') if q.strip() and len(q.strip()) > 10]
                    if queries:
                        # Используем первый вариант
                        reformulated = queries[0].strip('"').strip("'").strip()
                        logger.debug(f"Query expansion: {original_query[:50]}... → {reformulated[:50]}...")
                        return reformulated
                
                reformulation_prompt = f"""Ты эксперт по поиску в юридических документах.

Оригинальный запрос: {original_query}

Запрос не дал результатов. Переформулируй запрос более общим способом, используя:
- Синонимы юридических терминов
- Более широкие понятия
- Альтернативные формулировки

Верни только переформулированный запрос, без пояснений."""
            else:
                # Если документы найдены, но не релевантны - уточняем запрос
                docs_preview = "\n".join([
                    f"- {doc.page_content[:200]}..." 
                    for doc in found_documents[:3]
                ])
                
                # Используем контекст предыдущих запросов
                previous_context = ""
                if previous_queries:
                    previous_context = f"\n\nПредыдущие попытки поиска:\n" + "\n".join([f"- {q}" for q in previous_queries[-2:]])
                
                reformulation_prompt = f"""Ты эксперт по поиску в юридических документах.

Оригинальный запрос: {original_query}
{previous_context}

Найденные документы (но недостаточно релевантные):
{docs_preview}

Переформулируй запрос более точно, используя:
- Более специфичные термины
- Конкретные юридические понятия
- Уточнение контекста
- Избегай формулировок из предыдущих попыток

Верни только переформулированный запрос, без пояснений."""
            
            messages = [
                SystemMessage(content="Ты эксперт по переформулировке поисковых запросов для юридических документов."),
                HumanMessage(content=reformulation_prompt)
            ]
            
            response = self.llm.invoke(messages)
            reformulated = response.content.strip() if hasattr(response, 'content') else str(response).strip()
            
            # Очистка ответа (убираем кавычки, лишние символы)
            reformulated = reformulated.strip('"').strip("'").strip()
            
            logger.debug(f"Reformulated query: {original_query[:50]}... → {reformulated[:50]}...")
            return reformulated
            
        except Exception as e:
            logger.warning(f"Error reformulating query: {e}, using original query")
            return original_query
    
    def retrieve_adaptively(
        self,
        case_id: str,
        query: str,
        max_iterations: int = 5,
        db: Optional[Session] = None
    ) -> List[Document]:
        """
        Адаптивный retrieval с relevance feedback loop
        
        Улучшенная версия retrieve_iteratively с более умной рефинировкой
        на основе relevance feedback от найденных документов.
        
        Args:
            case_id: Case identifier
            query: Original search query
            max_iterations: Maximum number of search iterations
            db: Optional database session
            
        Returns:
            List of relevant documents
        """
        return self.retrieve_iteratively(
            case_id=case_id,
            query=query,
            max_iterations=max_iterations,
            initial_k=5,
            db=db,
            min_relevance_score=0.5
        )
    
    def _refine_query_with_feedback(
        self,
        original_query: str,
        found_docs: List[Document],
        iteration: int,
        previous_queries: Optional[List[str]] = None
    ) -> str:
        """
        Рефинирует query на основе relevance feedback от найденных документов
        
        Args:
            original_query: Original search query
            found_docs: Documents found in previous iteration
            iteration: Current iteration number
            previous_queries: List of previous queries
            
        Returns:
            Refined query
        """
        # Используем существующий метод _reformulate_query
        return self._reformulate_query(original_query, found_docs, iteration, previous_queries)
    
    def _is_sufficient(
        self,
        documents: List[Document],
        query: str,
        min_count: int = 3
    ) -> bool:
        """
        Проверяет, достаточно ли документов найдено
        
        Args:
            documents: List of documents
            query: Search query
            min_count: Minimum number of documents required
            
        Returns:
            True if sufficient documents found
        """
        if len(documents) < min_count:
            return False
        
        # Проверяем релевантность
        return self._is_relevant(documents, query, min_relevance_score=0.5)
    
    def _get_doc_hash(self, doc: Document) -> str:
        """Создает хеш документа для дедупликации"""
        content = doc.page_content[:200]  # Первые 200 символов
        metadata = doc.metadata if hasattr(doc, 'metadata') else {}
        source = metadata.get('source_file', '') + str(metadata.get('source_page', ''))
        return f"{content}_{source}"

