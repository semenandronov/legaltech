"""Structured Output Handler with automatic retry for agent outputs

Provides automatic parsing and validation of LLM responses using Pydantic models
with automatic retry on validation errors.
"""
from typing import Type, Optional, Any, Dict, List
from pydantic import BaseModel, ValidationError
from langchain_core.output_parsers import PydanticOutputParser, OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from app.services.llm_factory import create_llm
from app.services.langchain_agents.llm_helper import extract_json_from_response
import logging

logger = logging.getLogger(__name__)

# Try to import retry parsers
OUTPUT_FIXING_PARSER_AVAILABLE = False
RETRY_OUTPUT_PARSER_AVAILABLE = False

try:
    from langchain_core.output_parsers import OutputFixingParser
    OUTPUT_FIXING_PARSER_AVAILABLE = True
except ImportError:
    logger.debug("OutputFixingParser not available")

try:
    from langchain_core.output_parsers import RetryOutputParser
    RETRY_OUTPUT_PARSER_AVAILABLE = True
except ImportError:
    logger.debug("RetryOutputParser not available")


class StructuredOutputHandler:
    """
    Handler for parsing and validating LLM outputs using Pydantic models.
    
    Provides automatic retry on validation errors by using LLM to fix the output.
    """
    
    def __init__(
        self,
        model_class: Type[BaseModel],
        max_retries: int = 3,
        llm: Optional[Any] = None
    ):
        """
        Initialize structured output handler.
        
        Args:
            model_class: Pydantic model class for structured output
            max_retries: Maximum number of retry attempts
            llm: LLM instance for fixing errors (if None, creates new one)
        """
        self.model_class = model_class
        self.max_retries = max_retries
        self.llm = llm
        
        # Create base parser
        try:
            self.base_parser = PydanticOutputParser(pydantic_object=model_class)
        except Exception as e:
            logger.warning(f"Could not create PydanticOutputParser: {e}")
            self.base_parser = None
    
    def parse_with_retry(
        self,
        llm_response: str,
        llm: Optional[Any] = None,
        system_prompt: Optional[str] = None
    ) -> BaseModel:
        """
        Parse LLM response with automatic retry on validation errors.
        
        Args:
            llm_response: LLM response text
            llm: LLM instance for fixing errors (overrides instance llm if provided)
            system_prompt: Optional system prompt for retry attempts
        
        Returns:
            Parsed Pydantic model instance
            
        Raises:
            ValidationError: If parsing fails after all retries
            OutputParserException: If output cannot be parsed
        """
        llm_instance = llm or self.llm
        
        # Try using LangChain retry parsers if available
        if RETRY_OUTPUT_PARSER_AVAILABLE and llm_instance and self.base_parser:
            try:
                # Create fixing parser
                if OUTPUT_FIXING_PARSER_AVAILABLE:
                    fixing_parser = OutputFixingParser.from_llm(
                        parser=self.base_parser,
                        llm=llm_instance
                    )
                else:
                    fixing_parser = self.base_parser
                
                # Create retry parser
                retry_parser = RetryOutputParser.from_llm(
                    parser=fixing_parser,
                    llm=llm_instance,
                    max_retries=self.max_retries
                )
                
                try:
                    return retry_parser.parse(llm_response)
                except Exception as e:
                    logger.debug(f"RetryOutputParser failed: {e}, trying manual retry")
                    # Fall through to manual retry
            except Exception as e:
                logger.debug(f"Could not use RetryOutputParser: {e}, using manual retry")
        
        # Manual retry logic
        return self._parse_with_manual_retry(
            llm_response,
            llm_instance,
            system_prompt
        )
    
    def _parse_with_manual_retry(
        self,
        llm_response: str,
        llm: Optional[Any],
        system_prompt: Optional[str]
    ) -> BaseModel:
        """Manual retry logic when LangChain parsers are not available."""
        
        # Try direct parsing first
        if self.base_parser:
            try:
                return self.base_parser.parse(llm_response)
            except Exception as e:
                logger.debug(f"Direct parsing failed: {e}")
        
        # Try JSON extraction and manual validation
        json_data = extract_json_from_response(llm_response)
        if json_data:
            try:
                return self.model_class(**json_data)
            except ValidationError as e:
                logger.debug(f"Validation error: {e}")
                # Will retry if LLM available
            except Exception as e:
                logger.debug(f"Error creating model: {e}")
                # Will retry if LLM available
        
        # If we have LLM, try to fix and retry
        if llm:
            return self._retry_with_llm_fix(
                llm_response,
                llm,
                system_prompt,
                json_data
            )
        
        # Last attempt: try to create model with minimal data
        if json_data:
            try:
                # Try to create partial model
                if isinstance(json_data, dict):
                    return self.model_class(**json_data)
                elif isinstance(json_data, list) and len(json_data) > 0:
                    # If list, try first item
                    return self.model_class(**json_data[0])
            except Exception:
                pass
        
        # If all else fails, raise error
        raise OutputParserException(
            f"Could not parse output as {self.model_class.__name__}"
        )
    
    def _retry_with_llm_fix(
        self,
        original_response: str,
        llm: Any,
        system_prompt: Optional[str],
        parsed_json: Optional[Any]
    ) -> BaseModel:
        """Use LLM to fix parsing errors and retry."""
        
        error_message = f"Failed to parse output as {self.model_class.__name__}"
        if parsed_json:
            error_message += f". Extracted JSON: {parsed_json}"
        
        # Create fixing prompt
        fixing_prompt = f"""Исправь следующий ответ LLM, чтобы он соответствовал схеме {self.model_class.__name__}.

Оригинальный ответ:
{original_response[:2000]}

Схема ожидает объект типа {self.model_class.__name__}.
Верни исправленный JSON, который соответствует этой схеме.

Исправленный JSON:"""

        if system_prompt:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=fixing_prompt)
            ]
        else:
            messages = [HumanMessage(content=fixing_prompt)]
        
        # Try up to max_retries times
        for attempt in range(self.max_retries):
            try:
                response = llm.invoke(messages)
                fixed_text = response.content if hasattr(response, 'content') else str(response)
                
                # Try to parse fixed response
                fixed_json = extract_json_from_response(fixed_text)
                if fixed_json:
                    try:
                        return self.model_class(**fixed_json)
                    except ValidationError as e:
                        logger.debug(f"Retry {attempt + 1}/{self.max_retries} validation error: {e}")
                        if attempt < self.max_retries - 1:
                            # Update prompt with error details
                            fixing_prompt = f"""{fixing_prompt}

Ошибка валидации: {str(e)[:500]}
Попробуй исправить еще раз:"""
                            messages = [HumanMessage(content=fixing_prompt)]
                            continue
                else:
                    logger.debug(f"Retry {attempt + 1}/{self.max_retries} failed: could not extract JSON")
                    if attempt < self.max_retries - 1:
                        continue
            except Exception as e:
                logger.debug(f"Retry {attempt + 1}/{self.max_retries} error: {e}")
                if attempt < self.max_retries - 1:
                    continue
        
        # All retries failed
        raise OutputParserException(
            f"Failed to parse output as {self.model_class.__name__} after {self.max_retries} retries"
        )
    
    def parse_list(
        self,
        llm_response: str,
        llm: Optional[Any] = None,
        system_prompt: Optional[str] = None
    ) -> List[BaseModel]:
        """
        Parse LLM response as a list of models.
        
        Args:
            llm_response: LLM response text
            llm: LLM instance for fixing errors
            system_prompt: Optional system prompt for retry attempts
        
        Returns:
            List of parsed Pydantic model instances
        """
        # Extract JSON
        json_data = extract_json_from_response(llm_response)
        
        if not json_data:
            # Try to fix with LLM
            if llm or self.llm:
                llm_instance = llm or self.llm or create_llm(temperature=0.1)
                fixed_text = self._retry_with_llm_fix(
                    llm_response,
                    llm_instance,
                    system_prompt,
                    None
                )
                json_data = extract_json_from_response(fixed_text.content if hasattr(fixed_text, 'content') else str(fixed_text))
            
            if not json_data:
                raise OutputParserException("Could not extract JSON from response")
        
        # Parse list
        if isinstance(json_data, list):
            results = []
            for item in json_data:
                try:
                    if isinstance(item, dict):
                        results.append(self.model_class(**item))
                    else:
                        results.append(self.model_class(**{"data": item}))
                except ValidationError as e:
                    logger.warning(f"Validation error for item: {e}, skipping")
                    continue
            return results
        elif isinstance(json_data, dict):
            # Single item, wrap in list
            try:
                return [self.model_class(**json_data)]
            except ValidationError as e:
                raise OutputParserException(f"Validation error: {e}")
        else:
            raise OutputParserException(f"Expected list or dict, got {type(json_data)}")













