"""Extract Entities Tool for Workflows"""
from typing import Dict, Any, List
from app.services.workflows.tool_registry import BaseTool, ToolResult
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
import logging
import json
import re

logger = logging.getLogger(__name__)


ENTITY_EXTRACTION_PROMPT = """Извлеки именованные сущности из следующего текста.

ТЕКСТ:
{text}

ТИПЫ СУЩНОСТЕЙ ДЛЯ ИЗВЛЕЧЕНИЯ:
{entity_types}

Верни результат в формате JSON:
{{
    "entities": [
        {{
            "type": "тип сущности",
            "value": "значение",
            "context": "контекст где найдено (1-2 предложения)"
        }}
    ],
    "summary": "краткое описание найденных сущностей"
}}

Извлеки ВСЕ релевантные сущности указанных типов."""


class ExtractEntitiesTool(BaseTool):
    """
    Tool for extracting named entities from text.
    
    Identifies people, organizations, dates, amounts, and other entities.
    """
    
    name = "extract_entities"
    display_name = "Extract Entities"
    description = "Извлечение именованных сущностей (люди, организации, даты, суммы)"
    
    # Default entity types
    DEFAULT_ENTITY_TYPES = [
        "PERSON (люди, имена)",
        "ORGANIZATION (компании, организации)",
        "DATE (даты, периоды)",
        "MONEY (суммы, платежи)",
        "LOCATION (места, адреса)",
        "DOCUMENT (документы, контракты)",
        "LEGAL_TERM (юридические термины)"
    ]
    
    def __init__(self, db):
        super().__init__(db)
        self.llm = None
        try:
            # Use use_rate_limiting=False for LangChain | operator compatibility
            self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
        except Exception as e:
            logger.warning(f"Failed to initialize LLM: {e}")
    
    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        """Validate parameters"""
        errors = []
        
        if not params.get("text") and not params.get("file_id") and not params.get("file_ids"):
            errors.append("Требуется text, file_id или file_ids")
        
        return errors
    
    async def execute(self, params: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        Execute entity extraction
        
        Params:
            text: Text to extract entities from
            file_id: Single file ID to extract from
            file_ids: List of file IDs to extract from (from workflow)
            entity_types: List of entity types to extract (optional)
            
        Context:
            previous_results: Results from previous steps
        """
        try:
            if not self.llm:
                return ToolResult(
                    success=False,
                    error="LLM not initialized"
                )
            
            # Get text
            text = params.get("text", "")
            
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
                    logger.info(f"ExtractEntitiesTool: Loaded text from {len(files)} files")
            
            # Load from single file if file_id provided
            if not text and params.get("file_id"):
                from app.models.case import File
                file = self.db.query(File).filter(File.id == params.get("file_id")).first()
                if file:
                    text = file.original_text or ""
            
            if not text:
                return ToolResult(
                    success=False,
                    error="No text to process"
                )
            
            # Truncate if needed
            max_length = 20000
            if len(text) > max_length:
                text = text[:max_length]
            
            # Get entity types
            entity_types = params.get("entity_types", self.DEFAULT_ENTITY_TYPES)
            if isinstance(entity_types, list):
                entity_types_str = "\n".join(f"- {t}" for t in entity_types)
            else:
                entity_types_str = str(entity_types)
            
            # Create prompt and execute
            prompt = ChatPromptTemplate.from_template(ENTITY_EXTRACTION_PROMPT)
            chain = prompt | self.llm
            
            response = await chain.ainvoke({
                "text": text,
                "entity_types": entity_types_str
            })
            
            # Parse response
            entities = self._parse_response(response.content)
            
            # Group by type
            by_type = {}
            for entity in entities.get("entities", []):
                etype = entity.get("type", "OTHER")
                if etype not in by_type:
                    by_type[etype] = []
                by_type[etype].append(entity)
            
            return ToolResult(
                success=True,
                data={
                    "entities": entities.get("entities", []),
                    "by_type": by_type,
                    "total_count": len(entities.get("entities", [])),
                    "summary": entities.get("summary", "")
                },
                output_summary=f"Извлечено {len(entities.get('entities', []))} сущностей: " +
                              ", ".join(f"{k}: {len(v)}" for k, v in by_type.items()),
                llm_calls=1
            )
            
        except Exception as e:
            logger.error(f"ExtractEntitiesTool error: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e)
            )
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response"""
        try:
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        
        return {"entities": [], "summary": "Failed to parse response"}

