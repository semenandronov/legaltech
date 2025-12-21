"""LangChain chains for Legal AI Vault"""
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
import logging

from langchain_core.prompts import PromptTemplate, ChatPromptTemplate
from langchain_core.documents import Document
from app.config import config
from app.services.document_processor import DocumentProcessor
from app.services.yandex_llm import ChatYandexGPT
# YandexIndexRetriever removed - using pgvector retriever instead

logger = logging.getLogger(__name__)

# Try to import modern chain creation functions
create_retrieval_chain = None
create_stuff_documents_chain = None

try:
    from langchain.chains.combine_documents import create_stuff_documents_chain
    from langchain.chains.retrieval import create_retrieval_chain
    logger.debug("create_retrieval_chain and create_stuff_documents_chain imported")
except ImportError:
    try:
        from langchain.chains.combine_documents import create_stuff_documents_chain
        from langchain.chains.retrieval import create_retrieval_chain
        logger.debug("create_retrieval_chain and create_stuff_documents_chain imported from alternative path")
    except ImportError:
        logger.warning("create_retrieval_chain and create_stuff_documents_chain not available")

# Try to import chain classes with multiple fallback strategies
LLMChain = None
SequentialChain = None
StuffDocumentsChain = None
MapReduceDocumentsChain = None
RetrievalQA = None
load_qa_chain = None

try:
    # Try standard langchain.chains imports
    from langchain.chains import LLMChain, SequentialChain
    from langchain.chains.combine_documents.stuff import StuffDocumentsChain
    from langchain.chains.combine_documents.map_reduce import MapReduceDocumentsChain
    from langchain.chains.retrieval_qa.base import RetrievalQA
    from langchain.chains.question_answering import load_qa_chain
    logger.debug("Chain classes imported from langchain.chains")
except ImportError:
    try:
        # Try alternative import paths for LangChain 1.x
        from langchain.chains.llm import LLMChain
        from langchain.chains.sequential import SequentialChain
        from langchain.chains.combine_documents.stuff import StuffDocumentsChain
        from langchain.chains.combine_documents.map_reduce import MapReduceDocumentsChain
        from langchain.chains import RetrievalQA
        from langchain.chains.question_answering import load_qa_chain
        logger.debug("Chain classes imported from alternative paths")
    except ImportError:
        logger.warning(
            "Chain classes are not available. ChainService functionality will be limited. "
            "Please ensure langchain is properly installed."
        )


class ChainService:
    """Service for LangChain chains"""
    
    def __init__(self, document_processor: DocumentProcessor = None):
        """Initialize chain service"""
        self.document_processor = document_processor or DocumentProcessor()
        # Use ChatYandexGPT instead of ChatOpenAI
        self.llm = ChatYandexGPT(
            temperature=0.7,
            max_tokens=2000
        )
    
    def create_retrieval_qa_chain(self, case_id: str, db: Optional[Session] = None) -> RetrievalQA:
        """
        Create RetrievalQA chain for RAG
        
        Args:
            case_id: Case identifier
            db: Optional database session
            
        Returns:
            RetrievalQA instance
        """
        if RetrievalQA is None or load_qa_chain is None:
            raise ImportError(
                "RetrievalQA and load_qa_chain are not available. "
                "Please ensure langchain is properly installed."
            )
        
        # This method is deprecated - YandexIndexRetriever is no longer used (migrated to pgvector)
        # Use RAGService.generate_with_sources instead
        raise NotImplementedError(
            "ChainService.create_retrieval_qa_chain is deprecated. "
            "YandexIndexRetriever is no longer used (migrated to pgvector). "
            "Use RAGService.generate_with_sources instead."
        )
    
    def create_sequential_analysis_chain(self) -> SequentialChain:
        """
        Create sequential chain for multi-step analysis
        
        Returns:
            SequentialChain instance
        """
        if LLMChain is None or SequentialChain is None:
            raise ImportError(
                "LLMChain and SequentialChain are not available. "
                "Please ensure langchain is properly installed."
            )
        
        # Step 1: Extract facts
        facts_template = """Извлеки ключевые факты из следующего текста:
{text}

Верни структурированный список фактов в формате:
- Факт 1: описание
- Факт 2: описание"""
        
        facts_prompt = PromptTemplate(
            input_variables=["text"],
            template=facts_template
        )
        facts_chain = LLMChain(llm=self.llm, prompt=facts_prompt, output_key="facts")
        
        # Step 2: Analyze risks
        risks_template = """На основе следующих фактов проанализируй риски:
{facts}

Верни анализ рисков в формате:
- Риск 1: описание, уровень (HIGH/MEDIUM/LOW)
- Риск 2: описание, уровень"""
        
        risks_prompt = PromptTemplate(
            input_variables=["facts"],
            template=risks_template
        )
        risks_chain = LLMChain(llm=self.llm, prompt=risks_prompt, output_key="risks")
        
        # Step 3: Generate summary
        summary_template = """На основе фактов и рисков создай краткое резюме:
Факты:
{facts}

Риски:
{risks}

Резюме:"""
        
        summary_prompt = PromptTemplate(
            input_variables=["facts", "risks"],
            template=summary_template
        )
        summary_chain = LLMChain(llm=self.llm, prompt=summary_prompt, output_key="summary")
        
        # Create sequential chain
        sequential_chain = SequentialChain(
            chains=[facts_chain, risks_chain, summary_chain],
            input_variables=["text"],
            output_variables=["facts", "risks", "summary"],
            verbose=True
        )
        
        return sequential_chain
    
    def create_map_reduce_chain(self) -> MapReduceDocumentsChain:
        """
        Create MapReduce chain for processing large documents
        
        Returns:
            MapReduceDocumentsChain instance
        """
        if LLMChain is None or StuffDocumentsChain is None or MapReduceDocumentsChain is None:
            raise ImportError(
                "LLMChain, StuffDocumentsChain, and MapReduceDocumentsChain are not available. "
                "Please ensure langchain is properly installed."
            )
        
        # Map step: analyze each chunk
        map_template = """Проанализируй следующий фрагмент документа и извлеки ключевую информацию:

{text}

Ключевая информация:"""
        
        map_prompt = PromptTemplate(
            input_variables=["text"],
            template=map_template
        )
        map_chain = LLMChain(llm=self.llm, prompt=map_prompt)
        
        # Reduce step: combine all analyses
        reduce_template = """Объедини следующие анализы фрагментов в единый анализ:

{text}

Объединенный анализ:"""
        
        reduce_prompt = PromptTemplate(
            input_variables=["text"],
            template=reduce_template
        )
        reduce_chain = LLMChain(llm=self.llm, prompt=reduce_prompt)
        
        # Combine documents
        combine_documents_chain = StuffDocumentsChain(
            llm_chain=reduce_chain,
            document_variable_name="text"
        )
        
        # Create MapReduce chain
        map_reduce_chain = MapReduceDocumentsChain(
            llm_chain=map_chain,
            combine_document_chain=combine_documents_chain,
            document_variable_name="text",
            return_intermediate_steps=False
        )
        
        return map_reduce_chain
    
    def run_retrieval_qa(self, case_id: str, question: str, db: Optional[Session] = None) -> Dict[str, Any]:
        """
        Run RetrievalQA chain
        
        Args:
            case_id: Case identifier
            question: User question
            db: Optional database session
            
        Returns:
            Dictionary with answer and sources
        """
        try:
            chain = self.create_retrieval_qa_chain(case_id, db=db)
            result = chain({"query": question})
            
            return {
                "answer": result.get("result", ""),
                "sources": [
                    {
                        "file": doc.metadata.get("source_file", "unknown"),
                        "page": doc.metadata.get("source_page"),
                        "content": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
                    }
                    for doc in result.get("source_documents", [])
                ]
            }
        except Exception as e:
            logger.error(f"Error in RetrievalQA chain for case {case_id}: {e}")
            raise
    
    def run_sequential_analysis(self, text: str) -> Dict[str, Any]:
        """
        Run sequential analysis chain
        
        Args:
            text: Text to analyze
            
        Returns:
            Dictionary with facts, risks, and summary
        """
        try:
            chain = self.create_sequential_analysis_chain()
            result = chain({"text": text})
            return result
        except Exception as e:
            logger.error(f"Error in sequential analysis chain: {e}")
            raise
    
    def run_map_reduce(self, documents: List[Document]) -> str:
        """
        Run MapReduce chain on documents
        
        Args:
            documents: List of documents to process
            
        Returns:
            Combined analysis result
        """
        try:
            chain = self.create_map_reduce_chain()
            result = chain.invoke({"input_documents": documents})
            return result.get("output_text", "")
        except Exception as e:
            logger.error(f"Error in MapReduce chain: {e}")
            raise
    
    def create_rag_chain(self, case_id: str, retriever, db: Optional[Session] = None):
        """
        Create RAG chain using create_retrieval_chain and create_stuff_documents_chain
        
        This is the modern LangChain approach for RAG.
        
        Args:
            case_id: Case identifier
            retriever: LangChain retriever instance (e.g., from pgvector)
            db: Optional database session
            
        Returns:
            Runnable chain for RAG
        """
        if create_retrieval_chain is None or create_stuff_documents_chain is None:
            logger.warning("create_retrieval_chain not available, returning None")
            return None
        
        # Create prompt for RAG
        RAG_PROMPT = ChatPromptTemplate.from_messages([
            ("system", """Ты эксперт по анализу юридических документов.
Ты отвечаешь на вопросы на основе документов из векторного хранилища.

ВАЖНО:
- ВСЕГДА указывай конкретные источники в формате: [Документ: filename.pdf, стр. 5, строки 12-15]
- Если информация не найдена в документах - скажи честно
- Не давай юридических советов, только анализ фактов из документов
- Используй точные цитаты из документов когда это возможно"""),
            ("human", "Контекст:\n{context}\n\nВопрос: {question}")
        ])
        
        # Create document chain
        document_chain = create_stuff_documents_chain(
            llm=self.llm,
            prompt=RAG_PROMPT
        )
        
        # Create retrieval chain
        rag_chain = create_retrieval_chain(
            retriever=retriever,
            combine_docs_chain=document_chain
        )
        
        logger.info(f"Created RAG chain for case {case_id}")
        return rag_chain

