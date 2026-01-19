"""Document Drafter SubAgent - Создание черновиков документов"""
from typing import Dict, Any
from app.services.workflows.supervisor_agent import (
    BaseSubAgent, SubAgentSpec, SubAgentResult, ExecutionContext, TaskIntent
)
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
import logging

logger = logging.getLogger(__name__)


DRAFT_PROMPT = """Создай черновик документа на основе предоставленной информации.

ТИП ДОКУМЕНТА: {document_type}

КОНТЕКСТ/ИСХОДНЫЕ ДАННЫЕ:
{context}

ТРЕБОВАНИЯ:
{requirements}

Создай профессиональный черновик документа."""


class DocumentDrafterAgent(BaseSubAgent):
    """Агент для создания черновиков документов"""
    
    def __init__(self, db=None):
        self.db = db
        self.llm = None
        try:
            self.llm = create_llm(temperature=0.4, use_rate_limiting=False)
        except Exception as e:
            logger.warning(f"DocumentDrafterAgent: Failed to init LLM: {e}")
    
    @property
    def spec(self) -> SubAgentSpec:
        return SubAgentSpec(
            name="document_drafter",
            description="Создаёт черновики документов на основе контекста",
            capabilities=[
                "Создание юридических документов",
                "Адаптация шаблонов",
                "Генерация текста по требованиям"
            ],
            input_schema={
                "document_type": "str - тип документа",
                "context": "str - контекст/исходные данные",
                "requirements": "str - требования к документу"
            },
            output_schema={
                "draft": "str - текст черновика",
                "sections": "List[str] - разделы документа"
            },
            estimated_duration=60,
            can_parallelize=True
        )
    
    def can_handle(self, intent: TaskIntent) -> bool:
        return intent == TaskIntent.CREATE_DOCUMENT
    
    async def execute(
        self,
        context: ExecutionContext,
        params: Dict[str, Any]
    ) -> SubAgentResult:
        """Создать черновик документа"""
        try:
            document_type = params.get("document_type", "документ")
            requirements = params.get("requirements", context.user_task)
            
            # Получаем контекст из предыдущих результатов
            doc_context = ""
            if "summarizer" in context.previous_results:
                doc_context = context.previous_results["summarizer"].get("summary", "")
            if "entity_extractor" in context.previous_results:
                entities = context.previous_results["entity_extractor"]
                if entities:
                    doc_context += f"\n\nИзвлечённые данные: {entities}"
            
            if not doc_context:
                doc_context = "Контекст не предоставлен"
            
            if self.llm:
                prompt = ChatPromptTemplate.from_template(DRAFT_PROMPT)
                chain = prompt | self.llm
                
                response = await chain.ainvoke({
                    "document_type": document_type,
                    "context": doc_context,
                    "requirements": requirements
                })
                
                draft = response.content if hasattr(response, 'content') else str(response)
            else:
                draft = "Требуется LLM для создания черновика документа"
            
            return SubAgentResult(
                agent_name=self.spec.name,
                success=True,
                data={
                    "draft": draft,
                    "document_type": document_type
                },
                summary=f"Создан черновик: {document_type}",
                artifacts=[{
                    "type": "document_draft",
                    "content": draft,
                    "document_type": document_type
                }]
            )
            
        except Exception as e:
            logger.error(f"DocumentDrafterAgent error: {e}", exc_info=True)
            return SubAgentResult(
                agent_name=self.spec.name,
                success=False,
                data={},
                summary="Ошибка при создании документа",
                error=str(e)
            )

