"""LangChain chains for Legal AI Vault"""
from typing import List, Dict, Any, Optional
from langchain.chains import LLMChain, SequentialChain
from langchain.chains.combine_documents.stuff import StuffDocumentsChain
from langchain.chains.combine_documents.map_reduce import MapReduceDocumentsChain
from langchain.chains.retrieval_qa.base import RetrievalQA
from langchain.prompts import PromptTemplate, ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain.schema import Document
from langchain.chains.question_answering import load_qa_chain
from app.config import config
from app.services.document_processor import DocumentProcessor
import logging
import os

logger = logging.getLogger(__name__)


class ChainService:
    """Service for LangChain chains"""
    
    def __init__(self, document_processor: DocumentProcessor = None):
        """Initialize chain service"""
        self.document_processor = document_processor or DocumentProcessor()
        self.llm = ChatOpenAI(
            model=config.OPENROUTER_MODEL,
            openai_api_key=config.OPENROUTER_API_KEY,
            openai_api_base=config.OPENROUTER_BASE_URL,
            temperature=0.7,
            max_tokens=2000
        )
    
    def create_retrieval_qa_chain(self, case_id: str) -> RetrievalQA:
        """
        Create RetrievalQA chain for RAG
        
        Args:
            case_id: Case identifier
            
        Returns:
            RetrievalQA instance
        """
        # Load vector store
        if case_id not in self.document_processor.vector_stores:
            persist_directory = self.document_processor._get_persist_directory(case_id)
            if os.path.exists(persist_directory):
                self.document_processor.load_vector_store(case_id, persist_directory)
            else:
                raise ValueError(f"Vector store not found for case {case_id}")
        
        retriever = self.document_processor.vector_stores[case_id].as_retriever(
            search_kwargs={"k": 5}
        )
        
        # Create prompt template
        prompt_template = """Используй следующие документы для ответа на вопрос.
Если ответ не найден в документах, скажи честно.

Документы:
{context}

Вопрос: {question}

Ответ (обязательно укажи источники в формате [Документ: filename.pdf, стр. X]):"""
        
        prompt = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question"]
        )
        
        # Create QA chain
        qa_chain = load_qa_chain(
            llm=self.llm,
            chain_type="stuff",
            prompt=prompt
        )
        
        # Create RetrievalQA chain
        chain = RetrievalQA(
            combine_documents_chain=qa_chain,
            retriever=retriever,
            return_source_documents=True
        )
        
        return chain
    
    def create_sequential_analysis_chain(self) -> SequentialChain:
        """
        Create sequential chain for multi-step analysis
        
        Returns:
            SequentialChain instance
        """
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
    
    def run_retrieval_qa(self, case_id: str, question: str) -> Dict[str, Any]:
        """
        Run RetrievalQA chain
        
        Args:
            case_id: Case identifier
            question: User question
            
        Returns:
            Dictionary with answer and sources
        """
        try:
            chain = self.create_retrieval_qa_chain(case_id)
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

