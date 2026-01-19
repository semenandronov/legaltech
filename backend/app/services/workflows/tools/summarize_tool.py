"""Summarize Tool for Workflows"""
from typing import Dict, Any, List
from app.services.workflows.tool_registry import BaseTool, ToolResult
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
import logging

logger = logging.getLogger(__name__)


SUMMARIZE_PROMPT_BRIEF = """Создай краткое резюме следующего текста.

ТЕКСТ:
{text}

{additional_instructions}

Создай краткое структурированное резюме на русском языке (3-5 предложений). Выдели только самое важное."""


SUMMARIZE_PROMPT_DETAILED = """Создай подробное резюме следующего текста.

ТЕКСТ:
{text}

{additional_instructions}

Создай подробное структурированное резюме на русском языке:
1. Основная тема и цель документа
2. Ключевые положения и факты
3. Важные даты, суммы, сроки
4. Стороны и участники
5. Выводы и рекомендации"""


SUMMARIZE_PROMPT_BULLETS = """Создай резюме в виде списка ключевых пунктов.

ТЕКСТ:
{text}

{additional_instructions}

Создай резюме в формате маркированного списка на русском языке:
• Каждый пункт - одна важная мысль или факт
• Используй краткие, чёткие формулировки
• Выдели 5-10 ключевых пунктов"""


class SummarizeTool(BaseTool):
    """
    Tool for summarizing text or documents.
    
    Creates concise summaries with different styles:
    - brief: Краткое резюме (3-5 предложений)
    - detailed: Подробное структурированное резюме
    - bullet_points: Список ключевых пунктов
    """
    
    name = "summarize"
    display_name = "Summarize"
    description = "Создание резюме документа или текста"
    
    def __init__(self, db):
        super().__init__(db)
        self.llm = None
        try:
            self.llm = create_llm(temperature=0.3)
            logger.info("SummarizeTool: LLM initialized")
        except Exception as e:
            logger.warning(f"SummarizeTool: Failed to initialize LLM: {e}")
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("text") and not params.get("file_id") and not params.get("file_ids") and not params.get("data"):
            errors.append("Требуется text, file_id, file_ids или data")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute summarization
        
        Params:
            text: Text to summarize
            file_id: Single file ID to load text from
            file_ids: List of file IDs to load and summarize (from workflow)
            data: Data object to summarize (will be converted to string)
            max_length: Maximum summary length in words (optional)
            style: Summary style - "brief", "detailed", "bullet_points" (default: "brief")
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
            source = "text"
            
            # Load from multiple files if file_ids provided (workflow mode)
            if not text and params.get("file_ids"):
                from app.models.case import File
                file_ids = params.get("file_ids", [])
                files = self.db.query(File).filter(File.id.in_(file_ids)).all()
                if files:
                    text_parts = []
                    for file in files:
                        if file.original_text:
                            text_parts.append(f"[{file.filename}]\n{file.original_text}")
                    text = "\n\n---\n\n".join(text_parts)
                    source = f"files:{len(files)}"
                    logger.info(f"SummarizeTool: Loaded text from {len(files)} files, total length: {len(text)}")
                else:
                    return ToolResult(
                        success=False,
                        error=f"Files not found: {file_ids}"
                    )
            
            # Load from single file if file_id provided
            if not text and params.get("file_id"):
                from app.models.case import File
                file = self.db.query(File).filter(File.id == params.get("file_id")).first()
                if file:
                    text = file.original_text or ""
                    source = f"file:{file.filename}"
                    logger.info(f"SummarizeTool: Loaded text from file {file.filename}, length: {len(text)}")
                else:
                    return ToolResult(
                        success=False,
                        error=f"File not found: {params.get('file_id')}"
                    )
            
            # Convert data to text
            if not text and params.get("data"):
                import json
                data = params.get("data")
                if isinstance(data, (dict, list)):
                    text = json.dumps(data, ensure_ascii=False, indent=2)
                else:
                    text = str(data)
                source = "data"
            
            # Use previous results if available
            if not text and context.get("previous_results"):
                import json
                text = json.dumps(context.get("previous_results"), ensure_ascii=False, indent=2)
                source = "previous_results"
            
            if not text:
                return ToolResult(
                    success=False,
                    error="No text to summarize"
                )
            
            # Truncate if too long
            max_input = 30000
            original_length = len(text)
            if len(text) > max_input:
                text = text[:max_input] + "\n...[текст обрезан]..."
                logger.info(f"SummarizeTool: Text truncated from {original_length} to {max_input}")
            
            # Build additional instructions
            additional = ""
            if params.get("focus"):
                additional += f"Особое внимание удели: {params.get('focus')}\n"
            if params.get("max_length"):
                additional += f"Ограничь резюме примерно {params.get('max_length')} словами.\n"
            
            # Select prompt based on style
            style = params.get("style", "brief")
            if style == "detailed":
                prompt_template = SUMMARIZE_PROMPT_DETAILED
            elif style == "bullet_points":
                prompt_template = SUMMARIZE_PROMPT_BULLETS
            else:
                prompt_template = SUMMARIZE_PROMPT_BRIEF
            
            # Create prompt and execute
            prompt = ChatPromptTemplate.from_template(prompt_template)
            chain = prompt | self.llm
            
            logger.info(f"SummarizeTool: Generating {style} summary for {source}")
            
            response = await chain.ainvoke({
                "text": text,
                "additional_instructions": additional
            })
            
            summary = response.content
            
            return ToolResult(
                success=True,
                data={
                    "summary": summary,
                    "style": style,
                    "source": source,
                    "input_length": original_length,
                    "output_length": len(summary),
                    "word_count": len(summary.split())
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

