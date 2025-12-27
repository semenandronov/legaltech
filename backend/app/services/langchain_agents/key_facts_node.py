"""Key facts agent node for LangGraph"""
from typing import Dict, Any
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_parsers import ParserService
from sqlalchemy.orm import Session
from app.models.analysis import AnalysisResult
from langchain_core.messages import HumanMessage
import logging
import json

logger = logging.getLogger(__name__)


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
        
        # Проверяем, поддерживает ли LLM function calling
        use_tools = hasattr(llm, 'bind_tools')
        
        if use_tools and rag_service:
            # GigaChat с function calling - агент сам вызовет retrieve_documents_tool
            logger.info("Using GigaChat with function calling for key_facts agent")
            
            prompt = get_agent_prompt("key_facts")
            
            # Создаем агента с tools
            agent = create_legal_agent(llm, tools, system_prompt=prompt)
            
            # Создаем запрос для агента
            user_query = f"Извлеки ключевые факты из документов дела {case_id}. Используй retrieve_documents_tool для поиска релевантных документов. Верни результат в формате JSON массива фактов с полями: fact_type, value, description, source_document, source_page, confidence, reasoning."
            
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
            
            logger.info("Using direct RAG approach (YandexGPT or GigaChat without tools)")
            
            # Используем helper для прямого вызова LLM с RAG
            from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag, extract_json_from_response
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            
            # Create callback for logging
            callback = AnalysisCallbackHandler(agent_name="key_facts")
            
            prompt = get_agent_prompt("key_facts")
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
        
        # Извлекаем JSON из ответа
        from app.services.langchain_agents.llm_helper import extract_json_from_response
        
        # Try to extract JSON from response
        key_facts_data = extract_json_from_response(response_text)
        
        # If we have key facts data, parse it
        if key_facts_data:
            parsed_facts = ParserService.parse_key_facts(json.dumps(key_facts_data) if isinstance(key_facts_data, (list, dict)) else str(key_facts_data))
        else:
            # Fallback: use RAG to extract key facts
            if not rag_service:
                raise ValueError("RAG service required for key facts extraction")
            
            query = "Извлеки ключевые факты: стороны спора, суммы, даты, суть спора, судья, суд"
            relevant_docs = rag_service.retrieve_context(case_id, query, k=20)
            
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
                # Fallback to direct LLM call and parsing
                from app.services.llm_service import LLMService
                llm_service = LLMService()
                response = llm_service.generate(system_prompt, user_prompt, temperature=0)
                parsed_facts = ParserService.parse_key_facts(response)
        
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
        
        # Update state
        new_state = state.copy()
        new_state["key_facts_result"] = result_data
        
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
