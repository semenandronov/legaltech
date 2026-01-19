"""Entity Extractor SubAgent - Извлечение сущностей из документов"""
from typing import Dict, Any, List
from app.services.workflows.supervisor_agent import (
    BaseSubAgent, SubAgentSpec, SubAgentResult, ExecutionContext, TaskIntent
)
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
import logging
import json
import re

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT = """Извлеки из документа следующие сущности:
- Персоны (ФИО, роли)
- Организации (названия, ИНН если есть)
- Даты (в формате ДД.ММ.ГГГГ)
- Денежные суммы (с валютой)
- Адреса

ДОКУМЕНТ:
{text}

Ответь в формате JSON:
{{
    "persons": [
        {{"name": "ФИО", "role": "роль в документе"}}
    ],
    "organizations": [
        {{"name": "название", "inn": "ИНН или null"}}
    ],
    "dates": [
        {{"date": "ДД.ММ.ГГГГ", "context": "контекст даты"}}
    ],
    "amounts": [
        {{"value": "сумма", "currency": "валюта", "context": "контекст"}}
    ],
    "addresses": [
        {{"address": "адрес", "type": "тип (юридический/фактический)"}}
    ]
}}"""


class EntityExtractorAgent(BaseSubAgent):
    """Агент для извлечения именованных сущностей"""
    
    def __init__(self, db=None):
        self.db = db
        self.llm = None
        try:
            self.llm = create_llm(temperature=0.1, use_rate_limiting=False)
        except Exception as e:
            logger.warning(f"EntityExtractorAgent: Failed to init LLM: {e}")
    
    @property
    def spec(self) -> SubAgentSpec:
        return SubAgentSpec(
            name="entity_extractor",
            description="Извлекает структурированные данные: имена, даты, суммы, адреса",
            capabilities=[
                "Извлечение персон (ФИО)",
                "Извлечение организаций",
                "Извлечение дат",
                "Извлечение денежных сумм",
                "Извлечение адресов"
            ],
            input_schema={
                "file_ids": "List[str] - ID файлов",
                "entity_types": "List[str] - типы сущностей для извлечения"
            },
            output_schema={
                "persons": "List[Dict] - персоны",
                "organizations": "List[Dict] - организации",
                "dates": "List[Dict] - даты",
                "amounts": "List[Dict] - суммы",
                "addresses": "List[Dict] - адреса"
            },
            estimated_duration=45,
            can_parallelize=True
        )
    
    def can_handle(self, intent: TaskIntent) -> bool:
        return intent in [TaskIntent.EXTRACT_DATA, TaskIntent.FULL_ANALYSIS, TaskIntent.UNDERSTAND]
    
    async def execute(
        self,
        context: ExecutionContext,
        params: Dict[str, Any]
    ) -> SubAgentResult:
        """Извлечь сущности из документов"""
        try:
            file_ids = params.get("file_ids", context.file_ids)
            
            if not file_ids:
                return SubAgentResult(
                    agent_name=self.spec.name,
                    success=False,
                    data={},
                    summary="Не указаны файлы для анализа",
                    error="No file_ids provided"
                )
            
            # Загрузить текст
            text = await self._load_documents_text(file_ids)
            
            if not text:
                return SubAgentResult(
                    agent_name=self.spec.name,
                    success=False,
                    data={},
                    summary="Не удалось загрузить документы",
                    error="Failed to load documents"
                )
            
            # Ограничить размер
            if len(text) > 12000:
                text = text[:12000] + "\n...[текст обрезан]..."
            
            # Извлечь сущности
            if self.llm:
                prompt = ChatPromptTemplate.from_template(EXTRACTION_PROMPT)
                chain = prompt | self.llm
                
                response = await chain.ainvoke({"text": text})
                content = response.content if hasattr(response, 'content') else str(response)
                
                entities = self._parse_entities(content)
            else:
                entities = self._fallback_extraction(text)
            
            # Формируем summary
            summary_parts = []
            if entities.get("persons"):
                summary_parts.append(f"Персоны: {len(entities['persons'])}")
            if entities.get("organizations"):
                summary_parts.append(f"Организации: {len(entities['organizations'])}")
            if entities.get("dates"):
                summary_parts.append(f"Даты: {len(entities['dates'])}")
            if entities.get("amounts"):
                summary_parts.append(f"Суммы: {len(entities['amounts'])}")
            
            summary = "Извлечено: " + ", ".join(summary_parts) if summary_parts else "Сущности не найдены"
            
            return SubAgentResult(
                agent_name=self.spec.name,
                success=True,
                data=entities,
                summary=summary
            )
            
        except Exception as e:
            logger.error(f"EntityExtractorAgent error: {e}", exc_info=True)
            return SubAgentResult(
                agent_name=self.spec.name,
                success=False,
                data={},
                summary="Ошибка при извлечении сущностей",
                error=str(e)
            )
    
    def _parse_entities(self, content: str) -> Dict[str, List]:
        """Парсинг JSON с сущностями"""
        try:
            # Найти JSON
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        
        return {
            "persons": [],
            "organizations": [],
            "dates": [],
            "amounts": [],
            "addresses": []
        }
    
    def _fallback_extraction(self, text: str) -> Dict[str, List]:
        """Fallback извлечение без LLM (regex)"""
        entities = {
            "persons": [],
            "organizations": [],
            "dates": [],
            "amounts": [],
            "addresses": []
        }
        
        # Даты
        date_pattern = r'\d{2}[./-]\d{2}[./-]\d{4}'
        for match in re.findall(date_pattern, text):
            entities["dates"].append({"date": match, "context": ""})
        
        # Суммы
        amount_pattern = r'(\d[\d\s]*(?:,\d{2})?)\s*(руб|рублей|₽|USD|\$|EUR|€)'
        for match in re.findall(amount_pattern, text, re.IGNORECASE):
            entities["amounts"].append({"value": match[0].strip(), "currency": match[1]})
        
        return entities
    
    async def _load_documents_text(self, file_ids: list) -> str:
        """Загрузить текст документов"""
        if not self.db:
            return ""
        
        try:
            from app.models.case import File
            
            files = self.db.query(File).filter(File.id.in_(file_ids)).all()
            texts = [f.original_text for f in files if f.original_text]
            
            return "\n\n".join(texts)
            
        except Exception as e:
            logger.error(f"Failed to load documents: {e}")
            return ""

