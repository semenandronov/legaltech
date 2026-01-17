"""Summarize Tool for Workflows"""
from typing import Dict, Any, List
from app.services.workflows.tool_registry import BaseTool, ToolResult
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
import logging

logger = logging.getLogger(__name__)


SUMMARIZE_PROMPT = """Создай краткое резюме следующего текста или данных.

ТЕКСТ/ДАННЫЕ:
{text}

{additional_instructions}

Создай структурированное резюме на русском языке. Выдели ключевые моменты."""


class SummarizeTool(BaseTool):
    """
    Tool for summarizing text or data.
    
    Creates concise summaries of documents or analysis results.
    """
    
    name = "summarize"
    display_name = "Summarize"
    description = "Создание резюме документа или данных"
    
    def __init__(self, db):
        super().__init__(db)
        self.llm = None
        try:
            self.llm = create_llm(temperature=0.3)
        except Exception as e:
            logger.warning(f"Failed to initialize LLM: {e}")
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("text") and not params.get("data"):
            errors.append("Требуется text или data")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute summarization
        
        Params:
            text: Text to summarize
            data: Data object to summarize (will be converted to string)
            max_length: Maximum summary length (optional)
            focus: What to focus on in the summary (optional)
            
        Context:
            previous_results: Results from previous steps
        """
        try:
            if not self.llm:
                return ToolResult(
                    success=False,
                    error="LLM not initialized"
                )
            
            # Get text to summarize
            text = params.get("text", "")
            if not text and params.get("data"):
                import json
                data = params.get("data")
                if isinstance(data, (dict, list)):
                    text = json.dumps(data, ensure_ascii=False, indent=2)
                else:
                    text = str(data)
            
            # Use previous results if available
            if not text and context.get("previous_results"):
                import json
                text = json.dumps(context.get("previous_results"), ensure_ascii=False, indent=2)
            
            if not text:
                return ToolResult(
                    success=False,
                    error="No text to summarize"
                )
            
            # Truncate if too long
            max_input = 30000
            if len(text) > max_input:
                text = text[:max_input] + "\n...[текст обрезан]..."
            
            # Build additional instructions
            additional = ""
            if params.get("focus"):
                additional += f"Особое внимание удели: {params.get('focus')}\n"
            if params.get("max_length"):
                additional += f"Ограничь резюме {params.get('max_length')} словами.\n"
            
            # Create prompt and execute
            prompt = ChatPromptTemplate.from_template(SUMMARIZE_PROMPT)
            chain = prompt | self.llm
            
            response = await chain.ainvoke({
                "text": text,
                "additional_instructions": additional
            })
            
            summary = response.content
            
            return ToolResult(
                success=True,
                data={
                    "summary": summary,
                    "input_length": len(text),
                    "output_length": len(summary)
                },
                output_summary=summary[:500] + "..." if len(summary) > 500 else summary,
                llm_calls=1
            )
            
        except Exception as e:
            logger.error(f"SummarizeTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )

