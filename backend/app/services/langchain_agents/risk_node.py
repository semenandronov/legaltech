"""Risk analysis agent node for LangGraph"""
from typing import Dict, Any
from app.services.llm_factory import create_llm
from app.services.langchain_agents.agent_factory import create_legal_agent, safe_agent_invoke
from app.config import config
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from sqlalchemy.orm import Session
from app.models.analysis import AnalysisResult
from app.models.case import Case
from langchain_core.messages import HumanMessage
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)


def risk_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Risk analysis agent node for analyzing risks based on discrepancies
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with risk_result
    """
    case_id = state["case_id"]
    
    try:
        logger.info(f"Risk agent: Starting analysis for case {case_id}")
        
        # Check if discrepancy result is available (dependency)
        discrepancy_result = state.get("discrepancy_result")
        if not discrepancy_result:
            logger.warning(f"Risk agent: No discrepancy result available for case {case_id}, skipping")
            new_state = state.copy()
            new_state["risk_result"] = None
            return new_state
        
        # Initialize tools if needed
        if rag_service and document_processor:
            initialize_tools(rag_service, document_processor)
        
        # Get tools - include iterative search tool for critical agents
        from app.services.langchain_agents.tools import get_critical_agent_tools
        tools = get_critical_agent_tools()
        
        # Initialize LLM через factory (GigaChat)
        llm = create_llm(temperature=0.1)
        
        # Проверяем, поддерживает ли LLM function calling
        use_tools = hasattr(llm, 'bind_tools')
        
        # Get case info
        case_info = ""
        case_type = "general"
        if db:
            case = db.query(Case).filter(Case.id == case_id).first()
            if case:
                case_info = f"Тип дела: {case.case_type or 'Не указан'}\nОписание: {case.description or 'Нет описания'}\n"
                case_type = case.case_type.lower().replace(" ", "_").replace("-", "_") if case.case_type else "general"
        
        # Загружаем сохраненные паттерны рисков для этого типа дела
        known_risks_text = ""
        try:
            from app.services.langchain_agents.pattern_loader import PatternLoader
            pattern_loader = PatternLoader(db)
            
            # Загружаем известные риски асинхронно
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If loop is running, create task but don't await (fallback to sync)
                    known_risks_patterns = []
                else:
                    known_risks_patterns = loop.run_until_complete(
                        pattern_loader.load_risk_patterns(case_type, limit=20)
                    )
            except RuntimeError:
                known_risks_patterns = asyncio.run(
                    pattern_loader.load_risk_patterns(case_type, limit=20)
                )
            
            if known_risks_patterns:
                known_risks_text = pattern_loader.format_patterns_for_prompt(
                    known_risks_patterns,
                    pattern_type="risks"
                )
                logger.info(f"Loaded {len(known_risks_patterns)} known risk patterns for case type: {case_type}")
        except Exception as e:
            logger.warning(f"Failed to load risk patterns: {e}")
            known_risks_text = ""
        
        # Формируем запрос с данными о противоречиях
        discrepancies_text = json.dumps(discrepancy_result.get("discrepancies", []), ensure_ascii=False, indent=2)
        
        if use_tools and rag_service:
            # GigaChat с function calling - агент сам вызовет retrieve_documents_tool
            logger.info("Using GigaChat with function calling for risk agent")
            
            prompt = get_agent_prompt("risk")
            
            # Добавляем известные риски в промпт, если они есть
            if known_risks_text:
                prompt = prompt + "\n\n" + known_risks_text
            
            # Создаем агента с tools
            agent = create_legal_agent(llm, tools, system_prompt=prompt)
            
            # Создаем запрос для агента
            user_query = f"""Проанализируй риски следующего дела:

{case_info}

Найденные противоречия:
{discrepancies_text}

Используй retrieve_documents_iterative_tool для поиска дополнительных документов, если нужно. Сначала проверь известные типичные риски (указаны в системном промпте), затем ищи новые, специфичные для данного дела. Извлеки конкретные риски с обоснованием. Верни результат в формате JSON массива объектов с полями: risk_name, risk_category, probability, impact, description, evidence, recommendation, reasoning, confidence."""
            
            initial_message = HumanMessage(content=user_query)
            
            # Вызываем агента (он сам решит, когда вызывать tools)
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            callback = AnalysisCallbackHandler(agent_name="risk")
            
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
                raise ValueError("RAG service required for risk analysis")
            
            logger.info("Using direct RAG approach (GigaChat without tools)")
            
            # Используем helper для прямого вызова LLM с RAG
            from app.services.langchain_agents.llm_helper import direct_llm_call_with_rag, extract_json_from_response, parse_with_fixing
            from app.services.langchain_parsers import ParserService, RiskModel
            from app.services.langchain_agents.callbacks import AnalysisCallbackHandler
            
            # Create callback for logging
            callback = AnalysisCallbackHandler(agent_name="risk")
            
            user_query = f"""Проанализируй риски следующего дела:

{case_info}

Найденные противоречия:
{discrepancies_text}

Извлеки конкретные риски с обоснованием. Верни результат в формате JSON массива объектов с полями: risk_name, risk_category, probability, impact, description, evidence, recommendation, reasoning, confidence."""
            
            prompt = get_agent_prompt("risk")
            response_text = direct_llm_call_with_rag(
                case_id=case_id,
                system_prompt=prompt,
                user_query=user_query,
                rag_service=rag_service,
                db=db,
                k=20,
                temperature=0.1,
                callbacks=[callback]
            )
        
        # Parse risks
        from app.services.langchain_agents.llm_helper import extract_json_from_response, parse_with_fixing
        from app.services.langchain_parsers import ParserService, RiskModel
        
        parsed_risks = None
        try:
            # Try to use structured parsing with fixing
            parsed_risks = parse_with_fixing(response_text, RiskModel, llm=llm, max_retries=3, is_list=True)
        except Exception as e:
            logger.warning(f"Could not parse risks with fixing parser: {e}, trying manual parsing")
        
        # Fallback to manual parsing
        if not parsed_risks:
            try:
                risk_data = extract_json_from_response(response_text)
                if risk_data:
                    parsed_risks = ParserService.parse_risks(
                        json.dumps(risk_data) if isinstance(risk_data, (list, dict)) else str(risk_data)
                    )
                else:
                    parsed_risks = ParserService.parse_risks(response_text)
            except Exception as e:
                logger.error(f"Error parsing risks: {e}")
                parsed_risks = []
        
        # Save to database
        result_id = None
        if db:
            # Convert risks to dict for storage
            risks_data = []
            if parsed_risks:
                for risk in parsed_risks:
                    if hasattr(risk, 'dict'):
                        risks_data.append(risk.dict())
                    elif hasattr(risk, 'model_dump'):
                        risks_data.append(risk.model_dump())
                    elif isinstance(risk, dict):
                        risks_data.append(risk)
                    else:
                        risks_data.append({
                            "risk_name": getattr(risk, 'risk_name', ''),
                            "risk_category": getattr(risk, 'risk_category', ''),
                            "probability": getattr(risk, 'probability', 'MEDIUM'),
                            "impact": getattr(risk, 'impact', 'MEDIUM'),
                            "description": getattr(risk, 'description', ''),
                            "evidence": getattr(risk, 'evidence', []),
                            "recommendation": getattr(risk, 'recommendation', ''),
                            "reasoning": getattr(risk, 'reasoning', ''),
                            "confidence": getattr(risk, 'confidence', 0.8)
                        })
            
            risk_analysis_result = AnalysisResult(
                case_id=case_id,
                analysis_type="risk_analysis",
                result_data={
                    "risks": risks_data,
                    "total_risks": len(risks_data),
                    "discrepancies": discrepancy_result
                },
                status="completed"
            )
            db.add(risk_analysis_result)
            db.commit()
            result_id = risk_analysis_result.id
        
        logger.info(f"Risk agent: Completed analysis for case {case_id}, found {len(parsed_risks) if parsed_risks else 0} risks")
        
        # Save risks to LangGraph Store for future reference
        if db and parsed_risks:
            try:
                from app.services.langchain_agents.store_service import LangGraphStoreService
                import asyncio
                
                store_service = LangGraphStoreService(db)
                
                # Get case type for namespace
                case_type = "general"
                if db:
                    case = db.query(Case).filter(Case.id == case_id).first()
                    if case and case.case_type:
                        case_type = case.case_type.lower().replace(" ", "_")
                
                # Save each risk pattern
                for risk in parsed_risks:
                    risk_name = risk.risk_name if hasattr(risk, 'risk_name') else risk.get('risk_name', 'Unknown Risk')
                    namespace = f"risk_patterns/{case_type}"
                    
                    risk_value = {
                        "risk_name": risk_name,
                        "risk_category": risk.risk_category if hasattr(risk, 'risk_category') else risk.get('risk_category', ''),
                        "probability": risk.probability if hasattr(risk, 'probability') else risk.get('probability', 'MEDIUM'),
                        "impact": risk.impact if hasattr(risk, 'impact') else risk.get('impact', 'MEDIUM'),
                        "description": risk.description if hasattr(risk, 'description') else risk.get('description', ''),
                        "evidence": risk.evidence if hasattr(risk, 'evidence') else risk.get('evidence', []),
                        "recommendation": risk.recommendation if hasattr(risk, 'recommendation') else risk.get('recommendation', ''),
                        "confidence": risk.confidence if hasattr(risk, 'confidence') else risk.get('confidence', 0.8)
                    }
                    
                    metadata = {
                        "case_id": case_id,
                        "saved_at": datetime.now().isoformat(),
                        "source": "risk_agent"
                    }
                    
                    # Use asyncio.run for async call from sync function
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # If loop is running, use create_task
                            asyncio.create_task(store_service.save_pattern(
                                namespace=namespace,
                                key=risk_name,
                                value=risk_value,
                                metadata=metadata
                            ))
                        else:
                            loop.run_until_complete(store_service.save_pattern(
                                namespace=namespace,
                                key=risk_name,
                                value=risk_value,
                                metadata=metadata
                            ))
                    except RuntimeError:
                        # No event loop, create new one
                        asyncio.run(store_service.save_pattern(
                            namespace=namespace,
                            key=risk_name,
                            value=risk_value,
                            metadata=metadata
                        ))
                
                logger.info(f"Saved {len(parsed_risks)} risk patterns to Store")
            except Exception as e:
                logger.warning(f"Failed to save risks to Store: {e}")
        
        # Create result
        result_data = {
            "risks": [
                {
                    "risk_name": r.risk_name if hasattr(r, 'risk_name') else r.get('risk_name', ''),
                    "risk_category": r.risk_category if hasattr(r, 'risk_category') else r.get('risk_category', ''),
                    "probability": r.probability if hasattr(r, 'probability') else r.get('probability', 'MEDIUM'),
                    "impact": r.impact if hasattr(r, 'impact') else r.get('impact', 'MEDIUM'),
                    "description": r.description if hasattr(r, 'description') else r.get('description', ''),
                    "evidence": r.evidence if hasattr(r, 'evidence') else r.get('evidence', []),
                    "recommendation": r.recommendation if hasattr(r, 'recommendation') else r.get('recommendation', ''),
                    "reasoning": r.reasoning if hasattr(r, 'reasoning') else r.get('reasoning', ''),
                    "confidence": r.confidence if hasattr(r, 'confidence') else r.get('confidence', 0.8)
                }
                for r in (parsed_risks if parsed_risks else [])
            ],
            "total_risks": len(parsed_risks) if parsed_risks else 0,
            "discrepancies": discrepancy_result,
            "result_id": result_id
        }
        
        # Update state
        new_state = state.copy()
        new_state["risk_result"] = result_data
        
        return new_state
        
    except Exception as e:
        logger.error(f"Risk agent error for case {case_id}: {e}", exc_info=True)
        # Add error to state
        new_state = state.copy()
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({
            "agent": "risk",
            "error": str(e)
        })
        new_state["risk_result"] = None
        return new_state
