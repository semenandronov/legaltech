"""Helper functions for direct LLM calls without agents"""
from typing import List, Dict, Any, Optional, Type
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.output_parsers import PydanticOutputParser

# OutputFixingParser and RetryOutputParser may not be available in all langchain_core versions
OUTPUT_FIXING_PARSER_AVAILABLE = False
RETRY_OUTPUT_PARSER_AVAILABLE = False

try:
    from langchain_core.output_parsers import OutputFixingParser
    OUTPUT_FIXING_PARSER_AVAILABLE = True
except ImportError:
    logger.warning("OutputFixingParser not available in langchain_core")

try:
    from langchain_core.output_parsers import RetryOutputParser
    RETRY_OUTPUT_PARSER_AVAILABLE = True
except ImportError:
    logger.warning("RetryOutputParser not available in langchain_core, will use PydanticOutputParser only")
from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel
from app.services.llm_factory import create_llm
from app.services.rag_service import RAGService
from app.config import config
from sqlalchemy.orm import Session
import logging
import json

logger = logging.getLogger(__name__)


def direct_llm_call_with_rag(
    case_id: str,
    system_prompt: str,
    user_query: str,
    rag_service: RAGService,
    db: Optional[Session] = None,
    k: int = 20,
    temperature: float = 0.1,
    model: Optional[str] = None,
    callbacks: Optional[List[Any]] = None
) -> str:
    """
    Прямой вызов LLM с RAG контекстом (без агентов и инструментов)
    
    Args:
        case_id: Case ID
        system_prompt: System prompt for LLM
        user_query: User query
        rag_service: RAG service instance
        db: Optional database session
        k: Number of documents to retrieve
        temperature: Temperature for generation
        model: Model name (optional)
    
    Returns:
        LLM response text
    """
    # Инициализируем LLM через factory (GigaChat)
    llm = create_llm(
        model=model,
        temperature=temperature
    )
    
    # Получаем релевантные документы через RAG
    relevant_docs = rag_service.retrieve_context(case_id, user_query, k=k, db=db)
    
    if not relevant_docs:
        logger.warning(f"No documents found for query in case {case_id}")
        # Все равно вызываем LLM, но без контекста
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"{user_query}\n\nПримечание: Релевантные документы не найдены.")
        ]
    else:
        # Формируем промпт с контекстом
        # Filter documents by relevance if similarity_score is available
        filtered_docs = []
        for doc in relevant_docs:
            metadata = doc.metadata if hasattr(doc, 'metadata') else {}
            similarity_score = metadata.get('similarity_score', 0.0)
            # Keep documents with similarity > 0.5 or if no score is available
            if similarity_score is None or similarity_score > 0.5:
                filtered_docs.append(doc)
        
        # Use filtered docs or all docs if filtering removed everything
        docs_to_use = filtered_docs if filtered_docs else relevant_docs
        
        # Format sources with improved structure
        sources_text = rag_service.format_sources_for_prompt(docs_to_use)
        
        # Improved prompt structure
        full_user_prompt = f"""{user_query}

=== КОНТЕКСТ ИЗ ДОКУМЕНТОВ ===
{sources_text}

=== ИНСТРУКЦИИ ===
- Внимательно проанализируй контекст из документов выше
- Извлекай информацию только из предоставленного контекста
- Указывай точные источники (файл, страница, строка) для каждого факта
- Верни результат в формате JSON, если это требуется задачей"""
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=full_user_prompt)
        ]
    
    # Прямой вызов LLM
    try:
        if callbacks:
            response = llm.invoke(messages, config={"callbacks": callbacks})
        else:
            response = llm.invoke(messages)
        response_text = response.content if hasattr(response, 'content') else str(response)
        return response_text
    except Exception as e:
        logger.error(f"Error in direct LLM call: {e}", exc_info=True)
        raise


def extract_json_from_response(response_text: str) -> Optional[Any]:
    """
    Извлекает JSON из текстового ответа LLM
    
    Args:
        response_text: LLM response text
    
    Returns:
        Parsed JSON object or None if extraction failed
    """
    try:
        # Пробуем найти JSON в markdown блоке
        if "```json" in response_text:
            json_text = response_text.split("```json")[1].split("```")[0].strip()
            return json.loads(json_text)
        elif "```" in response_text:
            # Пробуем любой code block
            parts = response_text.split("```")
            for i in range(1, len(parts), 2):
                try:
                    return json.loads(parts[i].strip())
                except:
                    continue
        
        # Пробуем найти JSON массив или объект
        if "[" in response_text and "]" in response_text:
            start = response_text.find("[")
            end = response_text.rfind("]") + 1
            if start >= 0 and end > start:
                json_text = response_text[start:end]
                return json.loads(json_text)
        
        if "{" in response_text and "}" in response_text:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                json_text = response_text[start:end]
                return json.loads(json_text)
        
        # Пробуем распарсить весь текст как JSON
        return json.loads(response_text.strip())
    except Exception as e:
        logger.debug(f"Could not extract JSON from response: {e}")
        return None


def create_fixing_parser(
    pydantic_model: Type[BaseModel],
    llm: Optional[Any] = None,  # ChatGigaChat
    max_retries: int = 3
):
    """
    Create a parser with automatic error fixing and retry logic.
    
    Args:
        pydantic_model: Pydantic model class for structured output
        llm: LLM instance for fixing errors (if None, creates new one)
        max_retries: Maximum number of retry attempts
        
    Returns:
        Parser instance (RetryOutputParser if available, otherwise PydanticOutputParser)
    """
    if llm is None:
        llm = create_llm(temperature=0.1)
    
    # Create base parser
    base_parser = PydanticOutputParser(pydantic_object=pydantic_model)
    
    # Wrap in fixing parser (uses LLM to fix parsing errors) if available
    if OUTPUT_FIXING_PARSER_AVAILABLE:
        try:
            fixing_parser = OutputFixingParser.from_llm(parser=base_parser, llm=llm)
        except Exception as e:
            logger.warning(f"Could not create OutputFixingParser, using base parser: {e}")
            fixing_parser = base_parser
    else:
        # OutputFixingParser not available, use base parser directly
        fixing_parser = base_parser
    
    # Wrap in retry parser (retries on errors) if available
    if RETRY_OUTPUT_PARSER_AVAILABLE:
        try:
            retry_parser = RetryOutputParser.from_llm(
                parser=fixing_parser,
                llm=llm,
                max_retries=max_retries
            )
            return retry_parser
        except Exception as e:
            logger.warning(f"Could not create RetryOutputParser, using fixing parser: {e}")
            return fixing_parser
    else:
        # RetryOutputParser not available, return fixing parser (or base parser)
        return fixing_parser


def parse_with_fixing(
    response_text: str,
    pydantic_model: Type[BaseModel],
    llm: Optional[Any] = None,  # ChatGigaChat
    max_retries: int = 3,
    is_list: bool = True
) -> Optional[Any]:
    """
    Parse LLM response with automatic error fixing and retry.
    
    Args:
        response_text: LLM response text
        pydantic_model: Pydantic model class for structured output
        llm: LLM instance for fixing errors
        max_retries: Maximum number of retry attempts
        is_list: Whether to expect a list of models (default: True)
        
    Returns:
        Parsed Pydantic model instance(s) or None if parsing failed
        Returns list if is_list=True, single instance if is_list=False
    """
    try:
        if is_list:
            # For list models, we need to parse as list
            from typing import List
            from langchain_core.output_parsers import PydanticOutputParser
            list_parser = PydanticOutputParser(pydantic_object=List[pydantic_model])
            if OUTPUT_FIXING_PARSER_AVAILABLE and llm:
                try:
                    fixing_parser = OutputFixingParser.from_llm(parser=list_parser, llm=llm)
                except Exception as e:
                    logger.warning(f"Could not create OutputFixingParser, using base parser: {e}")
                    fixing_parser = list_parser
            else:
                fixing_parser = list_parser
            
            if RETRY_OUTPUT_PARSER_AVAILABLE and llm:
                try:
                    retry_parser = RetryOutputParser.from_llm(parser=fixing_parser, llm=llm, max_retries=max_retries)
                except Exception as e:
                    logger.warning(f"Could not create RetryOutputParser, using fixing parser: {e}")
                    retry_parser = fixing_parser
            else:
                retry_parser = fixing_parser
            return retry_parser.parse(response_text)
        else:
            parser = create_fixing_parser(pydantic_model, llm, max_retries)
            return parser.parse(response_text)
    except OutputParserException as e:
        logger.warning(f"Parser error after retries: {e}")
        # Fallback to manual JSON extraction
        json_data = extract_json_from_response(response_text)
        if json_data:
            try:
                if isinstance(json_data, list):
                    if is_list:
                        # Return list of parsed models
                        return [pydantic_model(**item if isinstance(item, dict) else item) for item in json_data]
                    else:
                        # Return first item
                        return pydantic_model(**json_data[0] if isinstance(json_data[0], dict) else json_data[0])
                elif isinstance(json_data, dict):
                    if is_list:
                        # Single dict, wrap in list
                        return [pydantic_model(**json_data)]
                    else:
                        return pydantic_model(**json_data)
            except Exception as parse_error:
                logger.error(f"Failed to parse JSON data into model: {parse_error}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in parse_with_fixing: {e}", exc_info=True)
        return None

