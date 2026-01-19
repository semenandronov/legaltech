"""Summarizer SubAgent - Создание резюме документов"""
from typing import Dict, Any
from app.services.workflows.supervisor_agent import (
    BaseSubAgent, SubAgentSpec, SubAgentResult, ExecutionContext, TaskIntent
)
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
import logging

logger = logging.getLogger(__name__)


SUMMARIZE_PROMPT = """Создай {style} резюме документа.

ДОКУМЕНТ:
{text}

Резюме должно содержать:
1. Тип документа
2. Основные стороны/участники
3. Ключевые положения
4. Важные даты и суммы (если есть)

Ответь структурированно и по делу."""


class SummarizerAgent(BaseSubAgent):
    """Агент для создания резюме документов"""
    
    def __init__(self, db=None):
        self.db = db
        self.llm = None
        try:
            self.llm = create_llm(temperature=0.3, use_rate_limiting=False)
        except Exception as e:
            logger.warning(f"SummarizerAgent: Failed to init LLM: {e}")
    
    @property
    def spec(self) -> SubAgentSpec:
        return SubAgentSpec(
            name="summarizer",
            description="Создаёт краткое или детальное резюме документа",
            capabilities=[
                "Понимание содержания документа",
                "Выделение ключевых положений",
                "Определение типа документа",
                "Идентификация сторон"
            ],
            input_schema={
                "file_ids": "List[str] - ID файлов для анализа",
                "style": "str - 'brief' или 'detailed'"
            },
            output_schema={
                "summary": "str - текст резюме",
                "document_type": "str - тип документа",
                "key_points": "List[str] - ключевые положения"
            },
            estimated_duration=30,
            can_parallelize=True
        )
    
    def can_handle(self, intent: TaskIntent) -> bool:
        return intent in [TaskIntent.UNDERSTAND, TaskIntent.FULL_ANALYSIS]
    
    async def execute(
        self,
        context: ExecutionContext,
        params: Dict[str, Any]
    ) -> SubAgentResult:
        """Создать резюме документов"""
        try:
            file_ids = params.get("file_ids", context.file_ids)
            style = params.get("style", "detailed")
            
            if not file_ids:
                return SubAgentResult(
                    agent_name=self.spec.name,
                    success=False,
                    data={},
                    summary="Не указаны файлы для анализа",
                    error="No file_ids provided"
                )
            
            # Загрузить текст документов
            text = await self._load_documents_text(file_ids)
            
            if not text:
                return SubAgentResult(
                    agent_name=self.spec.name,
                    success=False,
                    data={},
                    summary="Не удалось загрузить документы",
                    error="Failed to load documents"
                )
            
            # Ограничить размер текста
            if len(text) > 15000:
                text = text[:15000] + "\n...[текст обрезан]..."
            
            # Генерировать резюме
            if self.llm:
                prompt = ChatPromptTemplate.from_template(SUMMARIZE_PROMPT)
                chain = prompt | self.llm
                
                response = await chain.ainvoke({
                    "style": "детальное" if style == "detailed" else "краткое",
                    "text": text
                })
                
                summary = response.content if hasattr(response, 'content') else str(response)
            else:
                # Fallback без LLM
                summary = f"Документ содержит {len(text)} символов. Требуется LLM для анализа."
            
            return SubAgentResult(
                agent_name=self.spec.name,
                success=True,
                data={
                    "summary": summary,
                    "text_length": len(text),
                    "style": style
                },
                summary=summary[:500] + "..." if len(summary) > 500 else summary
            )
            
        except Exception as e:
            logger.error(f"SummarizerAgent error: {e}", exc_info=True)
            return SubAgentResult(
                agent_name=self.spec.name,
                success=False,
                data={},
                summary=f"Ошибка при создании резюме",
                error=str(e)
            )
    
    async def _load_documents_text(self, file_ids: list) -> str:
        """Загрузить текст документов из БД"""
        if not self.db:
            return ""
        
        try:
            from app.models.case import File
            
            files = self.db.query(File).filter(File.id.in_(file_ids)).all()
            
            texts = []
            for f in files:
                if f.original_text:
                    texts.append(f"[{f.filename}]\n{f.original_text}")
            
            return "\n\n---\n\n".join(texts)
            
        except Exception as e:
            logger.error(f"Failed to load documents: {e}")
            return ""


