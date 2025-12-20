"""Document classifier agent node for LangGraph"""
from typing import Dict, Any, Optional
from app.services.yandex_llm import ChatYandexGPT
from langchain_core.prompts import ChatPromptTemplate
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService, DocumentClassificationModel
from app.services.yandex_classifier import YandexDocumentClassifier
from sqlalchemy.orm import Session
from app.models.case import File, Case
import logging

logger = logging.getLogger(__name__)


def document_classifier_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None,
    file_id: Optional[str] = None
) -> AnalysisState:
    """
    Document classifier agent node for classifying documents
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
        file_id: Optional file ID to classify (if None, classifies all files)
    
    Returns:
        Updated state with classification_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Document classifier agent: Starting classification for case {case_id}, file_id={file_id}")
        
        if not db:
            raise ValueError("Database session required for document classification")
        
        # Get case context
        case = db.query(Case).filter(Case.id == case_id).first()
        case_context = f"Тип дела: {case.case_type or 'Не указан'}\nОписание: {case.description or 'Нет описания'}" if case else ""
        
        # Get file(s) to classify
        if file_id:
            files = db.query(File).filter(File.id == file_id, File.case_id == case_id).all()
        else:
            files = db.query(File).filter(File.case_id == case_id).all()
        
        if not files:
            logger.warning(f"No files found for classification in case {case_id}")
            new_state = state.copy()
            new_state["classification_result"] = None
            return new_state
        
        # Пытаемся использовать Yandex AI Studio классификатор (10x быстрее и дешевле!)
        yandex_classifier = None
        # Проверяем наличие API ключа или IAM токена + classifier_id
        if (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN) and config.YANDEX_AI_STUDIO_CLASSIFIER_ID:
            try:
                yandex_classifier = YandexDocumentClassifier()
                if yandex_classifier.is_available():
                    logger.info("✅ Using Yandex AI Studio classifier (10x быстрее, 100x дешевле!)")
            except Exception as e:
                logger.warning(f"Failed to initialize Yandex classifier: {e}, falling back to LLM")
        
        # Initialize LLM with temperature=0 for deterministic classification (fallback)
        # Только YandexGPT, без fallback на OpenRouter
        llm = None
        if not yandex_classifier:
            if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN) or not config.YANDEX_FOLDER_ID:
                raise ValueError("YANDEX_API_KEY/YANDEX_IAM_TOKEN и YANDEX_FOLDER_ID должны быть настроены")
            
            llm = ChatYandexGPT(
                model_name=config.YANDEX_GPT_MODEL,
                temperature=0,  # Детерминизм критичен для классификации!
                max_tokens=2000
            )
        
        # Get classifier prompt (для LLM fallback)
        from app.services.langchain_agents.prompts import get_agent_prompt
        system_prompt = get_agent_prompt("document_classifier") if not yandex_classifier else None
        
        # Classify each file
        classifications = []
        
        for file in files:
            try:
                # Get document text
                document_text = file.original_text or ""
                if not document_text:
                    logger.warning(f"File {file.id} has no text content, skipping classification")
                    continue
                
                # Limit text to avoid token limits
                limited_text = document_text[:4000]
                
                # Используем Yandex AI Studio если доступен
                if yandex_classifier:
                    try:
                        # Yandex AI Studio классификация (быстро и дешево!)
                        # Синхронный вызов (requests уже синхронный)
                        yandex_result = yandex_classifier.classify(
                            text=limited_text,
                            classes=["contract", "letter", "privileged", "report", "other"]
                        )
                        
                        # Преобразуем результат Yandex в формат DocumentClassificationModel
                        doc_type = yandex_result["type"]
                        confidence = yandex_result["confidence"]
                        
                        # Определяем привилегированность на основе типа
                        is_privileged = doc_type == "privileged"
                        privilege_type = "attorney-client" if is_privileged else "none"
                        
                        # Определяем релевантность на основе типа
                        relevance_score = 80 if doc_type in ["contract", "privileged"] else 50 if doc_type == "letter" else 30
                        
                        classification = DocumentClassificationModel(
                            doc_type=doc_type,
                            relevance_score=relevance_score,
                            is_privileged=is_privileged,
                            privilege_type=privilege_type,
                            key_topics=[],  # Yandex не возвращает темы, можно добавить позже
                            confidence=confidence,
                            reasoning=f"Классифицировано через Yandex AI Studio. Уверенность: {confidence:.0%}. Стоимость: {yandex_result['cost_rub']:.2f}₽"
                        )
                        
                        logger.info(
                            f"✅ Yandex classified file {file.id}: {doc_type} "
                            f"(confidence: {confidence:.0%}, cost: {yandex_result['cost_rub']:.2f}₽)"
                        )
                    except Exception as yandex_error:
                        logger.warning(f"Yandex classifier failed for file {file.id}: {yandex_error}, using LLM fallback")
                        # Fallback to LLM
                        yandex_classifier = None
                
                # Fallback to LLM classification
                if not yandex_classifier:
                    # Create prompt for classification
                    user_prompt = f"""КОНТЕКСТ ДЕЛА:
{case_context}

ДОКУМЕНТ ДЛЯ АНАЛИЗА:
{limited_text}

Классифицируй этот документ."""
                    
                    # Try to use structured output
                    try:
                        structured_llm = llm.with_structured_output(DocumentClassificationModel)
                        prompt = ChatPromptTemplate.from_messages([
                            ("system", system_prompt),
                            ("human", user_prompt)
                        ])
                        chain = prompt | structured_llm
                        classification = chain.invoke({})
                    except Exception as e:
                        logger.warning(f"Structured output not supported, falling back to JSON parsing: {e}")
                        # Fallback to direct LLM call
                        from app.services.llm_service import LLMService
                        llm_service = LLMService()
                        response = llm_service.generate(system_prompt, user_prompt, temperature=0)
                        classification = ParserService.parse_document_classification(response)
                
                classifications.append({
                    "file_id": file.id,
                    "file_name": file.filename,
                    "doc_type": classification.doc_type,
                    "relevance_score": classification.relevance_score,
                    "is_privileged": classification.is_privileged,
                    "privilege_type": classification.privilege_type,
                    "key_topics": classification.key_topics,
                    "confidence": classification.confidence,
                    "reasoning": classification.reasoning
                })
                
                logger.info(
                    f"Classified file {file.id}: type={classification.doc_type}, "
                    f"relevance={classification.relevance_score}, "
                    f"privileged={classification.is_privileged}, "
                    f"confidence={classification.confidence}"
                )
                
                # Save to database
                from app.models.analysis import DocumentClassification
                doc_classification = DocumentClassification(
                    case_id=case_id,
                    file_id=file.id,
                    doc_type=classification.doc_type,
                    relevance_score=classification.relevance_score,
                    is_privileged="true" if classification.is_privileged else "false",
                    privilege_type=classification.privilege_type,
                    key_topics=classification.key_topics,
                    confidence=str(classification.confidence),
                    reasoning=classification.reasoning,
                    prompt_version="v1"
                )
                db.add(doc_classification)
                
            except Exception as e:
                logger.error(f"Error classifying file {file.id}: {e}", exc_info=True)
                # On error, default classification
                try:
                    db.rollback()
                except:
                    pass
                classifications.append({
                    "file_id": file.id,
                    "file_name": file.filename,
                    "doc_type": "unknown",
                    "relevance_score": 0,
                    "is_privileged": False,
                    "privilege_type": "none",
                    "key_topics": [],
                    "confidence": 0.0,
                    "reasoning": f"Ошибка при классификации: {str(e)}",
                    "error": str(e)
                })
        
        # Create result
        result_data = {
            "classifications": classifications,
            "total_files": len(files),
            "by_type": {},
            "privileged_count": len([c for c in classifications if c["is_privileged"]]),
            "high_relevance_count": len([c for c in classifications if c["relevance_score"] > 70])
        }
        
        # Group by type
        for classification in classifications:
            doc_type = classification["doc_type"]
            if doc_type not in result_data["by_type"]:
                result_data["by_type"][doc_type] = 0
            result_data["by_type"][doc_type] += 1
        
        # Commit all classifications
        if db:
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Error committing classifications: {e}", exc_info=True)
        
        logger.info(
            f"Document classifier agent: Classified {len(files)} files, "
            f"found {result_data['privileged_count']} potentially privileged, "
            f"{result_data['high_relevance_count']} highly relevant"
        )
        
        # Update state
        new_state = state.copy()
        new_state["classification_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Document classifier agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "document_classifier",
            "error": str(e)
        })
        new_state["classification_result"] = None
        return new_state

