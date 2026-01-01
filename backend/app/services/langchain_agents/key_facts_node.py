"""Key facts agent node for LangGraph"""
from typing import Dict, Any, List
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService
from app.services.regex_extractor import RegexExtractor
from app.services.citation_verifier import CitationVerifier
from sqlalchemy.orm import Session
from app.models.analysis import AnalysisResult
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.documents import Document
import logging
import json

logger = logging.getLogger(__name__)


def _merge_regex_and_llm_facts(
    llm_facts: List,
    regex_facts: List[Dict[str, Any]]
) -> List:
    """
    Объединяет результаты regex и LLM для key facts
    
    Args:
        llm_facts: Факты, извлеченные LLM
        regex_facts: Факты, извлеченные regex (даты и суммы)
        
    Returns:
        Объединенный список фактов с улучшенным confidence scoring
    """
    # Создаем словарь фактов из regex для быстрого поиска
    regex_facts_map = {}
    for fact in regex_facts:
        key = (fact.get("fact_type"), str(fact.get("value", "")))
        if key not in regex_facts_map:
            regex_facts_map[key] = []
        regex_facts_map[key].append(fact)
    
    # Обогащаем факты LLM информацией из regex
    enriched_facts = []
    for fact in llm_facts:
        # Получаем тип и значение факта
        fact_type = None
        fact_value = None
        
        if hasattr(fact, 'fact_type'):
            fact_type = fact.fact_type
            fact_value = getattr(fact, 'value', None)
        elif isinstance(fact, dict):
            fact_type = fact.get('fact_type')
            fact_value = fact.get('value')
        
        # Проверяем совпадение с regex
        if fact_type and fact_value:
            key = (fact_type, str(fact_value))
            if key in regex_facts_map:
                matching_facts = regex_facts_map[key]
                # Находим совпадение по документу если возможно
                source_match = False
                if hasattr(fact, 'source_document'):
                    fact_source = fact.source_document
                    for regex_fact in matching_facts:
                        if regex_fact.get('source_document') == fact_source:
                            source_match = True
                            break
                elif isinstance(fact, dict):
                    fact_source = fact.get('source_document')
                    for regex_fact in matching_facts:
                        if regex_fact.get('source_document') == fact_source:
                            source_match = True
                            break
                
                # Повышаем confidence если есть совпадение
                if hasattr(fact, 'confidence'):
                    if source_match:
                        fact.confidence = min(1.0, fact.confidence + 0.15)
                    else:
                        fact.confidence = min(1.0, fact.confidence + 0.1)
                elif isinstance(fact, dict):
                    if source_match:
                        fact['confidence'] = min(1.0, fact.get('confidence', 0.8) + 0.15)
                    else:
                        fact['confidence'] = min(1.0, fact.get('confidence', 0.8) + 0.1)
        
        enriched_facts.append(fact)
    
    # Добавляем факты из regex, которых нет в LLM (только для дат и сумм)
    seen_keys = set()
    for fact in enriched_facts:
        fact_type = None
        fact_value = None
        if hasattr(fact, 'fact_type'):
            fact_type = fact.fact_type
            fact_value = getattr(fact, 'value', None)
        elif isinstance(fact, dict):
            fact_type = fact.get('fact_type')
            fact_value = fact.get('value')
        
        if fact_type and fact_value:
            seen_keys.add((fact_type, str(fact_value)))
    
    # Добавляем уникальные факты из regex
    for fact in regex_facts:
        key = (fact.get("fact_type"), str(fact.get("value", "")))
        if key not in seen_keys and fact.get("fact_type") in ["date", "amount"]:
            enriched_facts.append(fact)
    
    return enriched_facts


def key_facts_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Key facts agent node for extracting key facts from documents
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with key_facts_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Key facts agent: Starting extraction for case {case_id}")
        
        # Initialize tools if needed
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
        
        # Get tools
        tools = get_all_tools()
        
        # Initialize LLM через factory (GigaChat)
        llm = create_llm(temperature=0.1)
        
        # Initialize Memory Manager for context between requests
        from app.services.langchain_agents.memory_manager import AgentMemoryManager
        memory_manager = AgentMemoryManager(case_id, llm)
        
        # Get context from memory
        memory_context = memory_manager.get_context_for_agent("key_facts", "")
        
        # Проверяем, поддерживает ли LLM function calling
        use_tools = hasattr(llm, 'bind_tools')
        
        # Get case type for pattern loading
        case_type = "general"
        if db:
            from app.models.case import Case
            case = db.query(Case).filter(Case.id == case_id).first()
            if case and case.case_type:
                case_type = case.case_type.lower().replace(" ", "_").replace("-", "_")
        
        # Загружаем сохраненные паттерны ключевых фактов для этого типа дела
        known_facts_text = ""
        try:
            from app.services.langchain_agents.pattern_loader import PatternLoader
            pattern_loader = PatternLoader(db)
            
            import asyncio
            try:
                # Try to get existing event loop
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Event loop is running, cannot use it - skip pattern loading
                        known_facts_patterns = []
                    else:
                        known_facts_patterns = loop.run_until_complete(
                            pattern_loader.load_key_facts_patterns(case_type, limit=20)
                        )
                except RuntimeError:
                    # No event loop exists, create a new one
                    known_facts_patterns = asyncio.run(
                        pattern_loader.load_key_facts_patterns(case_type, limit=20)
                    )
            except Exception as e:
                logger.warning(f"Failed to load key facts patterns (async issue): {e}")
                known_facts_patterns = []
            
            if known_facts_patterns:
                known_facts_text = pattern_loader.format_patterns_for_prompt(
                    known_facts_patterns,
                    pattern_type="facts"
                )
                logger.info(f"Loaded {len(known_facts_patterns)} known key facts patterns for case type: {case_type}")
        except Exception as e:
            logger.warning(f"Failed to load key facts patterns: {e}")
            known_facts_text = ""
        
        if use_tools and rag_service:
            # GigaChat с function calling - агент сам вызовет retrieve_documents_tool
            logger.info("Using GigaChat with function calling for key_facts agent")
            
            base_prompt = get_agent_prompt("key_facts")
            
            # Add memory context to prompt if available
            if memory_context:
                base_prompt = f"""{base_prompt}

Предыдущий контекст из памяти:
{memory_context}

Используй этот контекст для улучшения анализа, но не дублируй уже извлеченные факты."""
            
            # Добавляем известные факты в промпт, если они есть
            if known_facts_text:
                prompt = base_prompt + "\n\n" + known_facts_text
            else:
                prompt = base_prompt
            
            # Создаем агента с tools
            agent = create_legal_agent(llm, tools, system_prompt=prompt)
            
            # Создаем запрос для агента
            user_query = f"Извлеки ключевые факты из документов дела {case_id}. Используй retrieve_documents_tool для поиска релевантных документов. Сначала проверь известные типичные факты для этого типа дела (указаны в системном промпте), затем извлекай специфичные для данного дела. Верни результат в формате JSON массива фактов с полями: fact_type, value, description, source_document, source_page, confidence, reasoning."
            
            initial_message = HumanMessage(content=user_query)
            
            # Вызываем агента (он сам решит, когда вызывать tools)
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            callback = AnalysisCallbackHandler(agent_name="key_facts")
            
            result = safe_agent_invoke(
                agent,
                llm,
                {
                    "messages": [initial_message],
                    "case_id": case_id
                },
                config={"recursion_limit": 15, "callbacks": [callback]}
            )
            
            # Извлекаем ответ
            if isinstance(result, dict):
                messages = result.get("messages", [])
                if messages:
                    response_message = messages[-1]
                    response_text = response_message.content if hasattr(response_message, 'content') else str(response_message)
                else:
                    response_text = str(result)
            else:
                response_text = str(result)
        else:
            # GigaChat без tools - используем прямой RAG подход
            if not rag_service:
                raise ValueError("RAG service required for key facts extraction")
            
            logger.info("Using direct RAG approach (GigaChat without tools)")
            
            # Используем helper для прямого вызова LLM с RAG
            from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag, extract_json_from_response
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            
            # Create callback for logging
            callback = AnalysisCallbackHandler(agent_name="key_facts")
            
            base_prompt = get_agent_prompt("key_facts")
            
            # Add memory context to prompt if available
            if memory_context:
                prompt = f"""{base_prompt}

Предыдущий контекст из памяти:
{memory_context}

Используй этот контекст для улучшения анализа, но не дублируй уже извлеченные факты."""
            else:
                prompt = base_prompt
            
            user_query = f"Извлеки ключевые факты из документов дела {case_id}. Верни результат в формате JSON массива фактов с полями: fact_type, value, description, source_document, source_page, confidence, reasoning."
            
            response_text = direct_llm_call_with_rag(
                case_id=case_id,
                system_prompt=prompt,
                user_query=user_query,
                rag_service=rag_service,
                db=db,
                k=30,
                temperature=0.1,
                callbacks=[callback]
            )
        
        # Pre-processing: используем regex для предварительного извлечения дат/сумм
        regex_extractor = RegexExtractor()
        regex_facts = []
        
        try:
            # Получаем документы для pre-processing
            if rag_service:
                preprocess_docs = rag_service.retrieve_context(
                    case_id=case_id,
                    query="суммы даты стороны факты",
                    k=50,
                    db=db
                )
                
                # Извлекаем даты и суммы из всех документов с помощью regex
                for doc in preprocess_docs:
                    if hasattr(doc, 'page_content'):
                        dates = regex_extractor.extract_dates(doc.page_content)
                        amounts = regex_extractor.extract_amounts(doc.page_content)
                        
                        # Добавляем даты как факты
                        for date_info in dates:
                            regex_facts.append({
                                "fact_type": "date",
                                "value": date_info.get("date"),
                                "description": date_info.get("original_text"),
                                "source_document": doc.metadata.get("source_file", "unknown"),
                                "source_page": doc.metadata.get("source_page"),
                                "confidence": date_info.get("confidence", 0.8),
                                "reasoning": f"Извлечено regex: {date_info.get('original_text')}"
                            })
                        
                        # Добавляем суммы как факты
                        for amount_info in amounts:
                            regex_facts.append({
                                "fact_type": "amount",
                                "value": f"{amount_info.get('amount')} {amount_info.get('currency', 'RUB')}",
                                "description": amount_info.get("original_text"),
                                "source_document": doc.metadata.get("source_file", "unknown"),
                                "source_page": doc.metadata.get("source_page"),
                                "confidence": amount_info.get("confidence", 0.8),
                                "reasoning": f"Извлечено regex: {amount_info.get('original_text')}"
                            })
                
                logger.info(f"Regex extracted {len(regex_facts)} facts as pre-processing step")
        except Exception as e:
            logger.warning(f"Error in regex pre-processing: {e}, continuing without regex facts")
        
        # Извлекаем JSON из ответа
        from app.services.langchain_agents.llm_helper import extract_json_from_response
        
        # Try to extract JSON from response
        key_facts_data = extract_json_from_response(response_text)
        
        # Initialize parsed_facts and relevant_docs
        parsed_facts = None
        relevant_docs = []
        
        # If we have key facts data, parse it
        if key_facts_data:
            parsed_facts = ParserService.parse_key_facts(json.dumps(key_facts_data) if isinstance(key_facts_data, (list, dict)) else str(key_facts_data))
        else:
            # Fallback: use RAG to extract key facts
            if not rag_service:
                raise ValueError("RAG service required for key facts extraction")
            
            query = "Извлеки ключевые факты: стороны спора, суммы, даты, суть спора, судья, суд"
            relevant_docs = rag_service.retrieve_context(case_id, query, k=20, db=db)
        
        # Verify citations: проверяем что факты реально присутствуют в документах
        if parsed_facts and rag_service:
            try:
                citation_verifier = CitationVerifier(similarity_threshold=0.7)
                # Получаем source documents для верификации
                verify_docs = rag_service.retrieve_context(
                    case_id=case_id,
                    query="",
                    k=100,  # Получаем больше документов для верификации
                    db=db
                )
                
                # Верифицируем каждый факт
                for fact in parsed_facts:
                    verification_result = citation_verifier.verify_extracted_fact(
                        fact=fact if isinstance(fact, dict) else {
                            "reasoning": getattr(fact, 'reasoning', None),
                            "description": getattr(fact, 'description', None),
                            "value": getattr(fact, 'value', None)
                        },
                        source_documents=verify_docs,
                        tolerance=100
                    )
                    
                    # Устанавливаем verification_status
                    verification_status = "verified" if verification_result.get("verified", False) else "unverified"
                    if hasattr(fact, 'verification_status'):
                        fact.verification_status = verification_status
                        # Снижаем confidence если не верифицировано
                        if not verification_result.get("verified", False):
                            current_confidence = getattr(fact, 'confidence', 0.8)
                            fact.confidence = max(0.3, current_confidence - 0.2)
                    elif isinstance(fact, dict):
                        fact['verification_status'] = verification_status
                        if not verification_result.get("verified", False):
                            current_confidence = fact.get('confidence', 0.8)
                            fact['confidence'] = max(0.3, current_confidence - 0.2)
                
                logger.info(f"Citation verification completed for {len(parsed_facts)} key facts")
            except Exception as e:
                logger.warning(f"Error during citation verification: {e}, continuing without verification")
            
            # Use LLM with structured output for key facts extraction
            from langchain_core.prompts import ChatPromptTemplate
            from app.services.langchain_parsers import KeyFactModel
            from typing import List
            
            sources_text = rag_service.format_sources_for_prompt(relevant_docs)
            system_prompt = get_agent_prompt("key_facts")
            user_prompt = f"Извлеки ключевые факты из следующих документов:\n\n{sources_text}"
            
            # Try to use structured output if supported
            try:
                structured_llm = llm.with_structured_output(List[KeyFactModel])
                prompt = ChatPromptTemplate.from_messages([
                    ("system", system_prompt),
                    ("human", user_prompt)
                ])
                chain = prompt | structured_llm
                parsed_facts = chain.invoke({})
            except Exception as e:
                logger.warning(f"Structured output not supported, falling back to JSON parsing: {e}")
                # Fallback to direct LLM call and parsing using GigaChat
                try:
                    # Используем GigaChat LLM напрямую через invoke с сообщениями
                    # SystemMessage и HumanMessage уже импортированы в начале файла
                    messages = [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=user_prompt)
                    ]
                    response = llm.invoke(messages)
                    response_text = response.content if hasattr(response, 'content') else str(response)
                    parsed_facts = ParserService.parse_key_facts(response_text)
                except Exception as fallback_error:
                    logger.error(f"Fallback LLM call failed: {fallback_error}, using empty facts")
                    parsed_facts = []
        
        # Convert to structured format
        facts_data = {
            "parties": [],
            "amounts": [],
            "dates": [],
            "other": []
        }
        
        for fact_model in parsed_facts:
            fact_dict = {
                "fact_type": fact_model.fact_type,
                "value": fact_model.value,
                "description": fact_model.description,
                "source_document": fact_model.source_document,
                "source_page": fact_model.source_page,
                "confidence": fact_model.confidence,
                "reasoning": fact_model.reasoning if hasattr(fact_model, 'reasoning') else ""
            }
            
            # Categorize facts
            if fact_model.fact_type in ["plaintiff", "defendant", "party"]:
                facts_data["parties"].append(fact_dict)
            elif fact_model.fact_type in ["amount", "payment", "penalty", "cost"]:
                facts_data["amounts"].append(fact_dict)
            elif fact_model.fact_type in ["date", "deadline", "event_date"]:
                facts_data["dates"].append(fact_dict)
            else:
                facts_data["other"].append(fact_dict)
        
        # Save to database
        result_id = None
        if db:
            result = AnalysisResult(
                case_id=case_id,
                analysis_type="key_facts",
                result_data=facts_data,
                status="completed"
            )
            db.add(result)
            db.commit()
            result_id = result.id
        
        logger.info(f"Key facts agent: Extracted {len(parsed_facts)} facts for case {case_id}")
        
        # Create result
        result_data = {
            "facts": facts_data,
            "result_id": result_id,
            "total_facts": len(parsed_facts)
        }
        
        # Save to file system (DeepAgents pattern)
        try:
            from app.services.langchain_agents.file_system_helper import save_agent_result_to_file
            save_agent_result_to_file(state, "key_facts", result_data)
        except Exception as fs_error:
            logger.debug(f"Failed to save key_facts result to file: {fs_error}")
        
        # Update state
        new_state = state.copy()
        new_state["key_facts_result"] = result_data
        
        # Save to memory for context in future requests
        try:
            result_summary = f"Extracted {len(parsed_facts)} key facts for case {case_id}"
            memory_manager.save_to_memory("key_facts", user_query, result_summary)
        except Exception as mem_error:
            logger.debug(f"Failed to save key_facts to memory: {mem_error}")
        
        return new_state
        
    except Exception as e:
        logger.error(f"Key facts agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "key_facts",
            "error": str(e)
        })
        new_state["key_facts_result"] = None
        return new_state
