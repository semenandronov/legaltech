"""Natural Language Workflow Parser - parses NL descriptions into WorkflowTemplate"""
from typing import Dict, Any, List, Optional
from app.models.workflow_template import WorkflowTemplate
from app.services.llm_factory import create_llm
from langchain_core.messages import HumanMessage, SystemMessage
import json
import logging
import uuid

logger = logging.getLogger(__name__)


class WorkflowNLParser:
    """
    Парсит natural language описание workflow в WorkflowTemplate
    
    Использует LLM для извлечения шагов, зависимостей и структуры workflow.
    """
    
    def __init__(self):
        """Initialize WorkflowNLParser"""
        try:
            self.llm = create_llm(temperature=0.1)
            logger.info("✅ WorkflowNLParser initialized with GigaChat")
        except Exception as e:
            logger.error(f"Failed to initialize LLM for WorkflowNLParser: {e}")
            raise
    
    def parse_workflow_description(
        self,
        description: str,
        user_id: str,
        display_name: str = None,
        category: str = "custom"
    ) -> WorkflowTemplate:
        """
        Парсит NL описание workflow в WorkflowTemplate
        
        Args:
            description: Natural language описание workflow
                        Пример: "Проведи due diligence: сначала классифицируй документы,
                                затем извлеки ключевые факты и риски, в конце создай отчет"
            user_id: User ID для создания workflow
            display_name: Display name (опционально, будет сгенерировано)
            category: Category для workflow
            
        Returns:
            WorkflowTemplate instance
        """
        logger.info(f"Parsing workflow description: {description[:100]}...")
        
        try:
            # Create prompt for LLM
            prompt = self._create_parsing_prompt(description)
            
            # Call LLM
            messages = [
                SystemMessage(content=self._get_system_prompt()),
                HumanMessage(content=prompt)
            ]
            
            response = self.llm.invoke(messages)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON response
            try:
                workflow_json = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code block
                import re
                json_match = re.search(r'```json\n(.*?)\n```', response_text, re.DOTALL)
                if json_match:
                    workflow_json = json.loads(json_match.group(1))
                else:
                    # Try to find JSON object in text
                    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if json_match:
                        workflow_json = json.loads(json_match.group(0))
                    else:
                        raise ValueError("Could not parse JSON from LLM response")
            
            # Create WorkflowTemplate
            workflow = self._create_workflow_from_parsed(
                workflow_json,
                description,
                user_id,
                display_name,
                category
            )
            
            logger.info(f"Successfully parsed workflow: {workflow.display_name} with {len(workflow.steps)} steps")
            return workflow
            
        except Exception as e:
            logger.error(f"Error parsing workflow description: {e}", exc_info=True)
            # Return fallback workflow
            return self._create_fallback_workflow(description, user_id, display_name, category)
    
    def _get_system_prompt(self) -> str:
        """Get system prompt for workflow parsing"""
        return """Ты эксперт по созданию workflow шаблонов для юридического анализа.

Твоя задача - преобразовать natural language описание workflow в структурированный JSON с шагами.

Доступные типы агентов:
- classification (document_classifier) - классификация документов
- entity_extraction - извлечение сущностей
- timeline - извлечение хронологии
- key_facts - извлечение ключевых фактов
- discrepancy - поиск противоречий
- risk - анализ рисков (требует discrepancy)
- summary - генерация резюме (требует key_facts)
- privilege_check - проверка привилегий
- relationship - построение графа связей (требует entity_extraction)

ВАЖНО: Учитывай зависимости между агентами:
- risk требует discrepancy
- summary требует key_facts
- relationship требует entity_extraction

Верни ТОЛЬКО валидный JSON без дополнительного текста."""

    def _create_parsing_prompt(self, description: str) -> str:
        """Create parsing prompt from description"""
        return f"""Преобразуй следующее описание workflow в структурированный JSON.

Описание: {description}

Верни JSON в следующем формате:
{{
  "name": "slug_name",
  "display_name": "Отображаемое название",
  "description": "Описание workflow",
  "steps": [
    {{
      "step_id": "1",
      "name": "Название шага",
      "description": "Описание шага",
      "agent": "classification|entity_extraction|timeline|key_facts|discrepancy|risk|summary|privilege_check|relationship",
      "required": true
    }},
    ...
  ]
}}

Учти зависимости между агентами:
- Если упоминается risk, добавь discrepancy перед ним
- Если упоминается summary, добавь key_facts перед ним
- Если упоминается relationship, добавь entity_extraction перед ним"""

    def _create_workflow_from_parsed(
        self,
        workflow_json: Dict[str, Any],
        original_description: str,
        user_id: str,
        display_name: str = None,
        category: str = "custom"
    ) -> WorkflowTemplate:
        """Create WorkflowTemplate from parsed JSON"""
        # Generate name if not provided
        name = workflow_json.get("name")
        if not name:
            # Generate slug from display_name
            import re
            display = workflow_json.get("display_name", "workflow")
            name = re.sub(r'[^a-z0-9]+', '_', display.lower()).strip('_')
        
        # Use provided display_name or from JSON
        final_display_name = display_name or workflow_json.get("display_name", name)
        
        # Create WorkflowTemplate
        workflow = WorkflowTemplate(
            id=str(uuid.uuid4()),
            name=name,
            display_name=final_display_name,
            description=workflow_json.get("description", original_description),
            category=category,
            steps=workflow_json.get("steps", []),
            user_id=user_id,
            auto_generated=True,
            natural_language_source=original_description,
            is_system=False,
            is_public=False
        )
        
        return workflow
    
    def _create_fallback_workflow(
        self,
        description: str,
        user_id: str,
        display_name: str = None,
        category: str = "custom"
    ) -> WorkflowTemplate:
        """Create fallback workflow if parsing fails"""
        import re
        name = re.sub(r'[^a-z0-9]+', '_', (display_name or "workflow").lower()).strip('_')
        
        # Default steps
        default_steps = [
            {
                "step_id": "1",
                "name": "Классификация документов",
                "description": "Классификация документов",
                "agent": "classification",
                "required": True
            },
            {
                "step_id": "2",
                "name": "Извлечение ключевых фактов",
                "description": "Извлечение ключевых фактов",
                "agent": "key_facts",
                "required": True
            },
            {
                "step_id": "3",
                "name": "Резюме",
                "description": "Генерация резюме",
                "agent": "summary",
                "required": True
            }
        ]
        
        return WorkflowTemplate(
            id=str(uuid.uuid4()),
            name=name,
            display_name=display_name or "Сгенерированный workflow",
            description=description,
            category=category,
            steps=default_steps,
            user_id=user_id,
            auto_generated=True,
            natural_language_source=description,
            is_system=False,
            is_public=False
        )


