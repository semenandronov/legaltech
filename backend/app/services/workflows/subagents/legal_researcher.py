"""Legal Researcher SubAgent - Поиск в правовых базах данных"""
from typing import Dict, Any
from app.services.workflows.supervisor_agent import (
    BaseSubAgent, SubAgentSpec, SubAgentResult, ExecutionContext, TaskIntent
)
from app.services.llm_factory import create_llm
from langchain_core.prompts import ChatPromptTemplate
import logging

logger = logging.getLogger(__name__)


LEGAL_RESEARCH_PROMPT = """Ты - юридический исследователь. На основе контекста документа, 
определи какие правовые нормы и судебная практика могут быть релевантны.

КОНТЕКСТ/ЗАДАЧА:
{context}

Укажи:
1. Релевантные статьи законов (ГК РФ, ТК РФ, и т.д.)
2. Возможную судебную практику
3. Рекомендации по правовым вопросам

Ответь структурированно."""


class LegalResearcherAgent(BaseSubAgent):
    """Агент для поиска в правовых базах данных"""
    
    def __init__(self, db=None):
        self.db = db
        self.llm = None
        try:
            self.llm = create_llm(temperature=0.2, use_rate_limiting=False)
        except Exception as e:
            logger.warning(f"LegalResearcherAgent: Failed to init LLM: {e}")
    
    @property
    def spec(self) -> SubAgentSpec:
        return SubAgentSpec(
            name="legal_researcher",
            description="Поиск в правовых базах данных, законы и судебная практика",
            capabilities=[
                "Поиск релевантных законов",
                "Анализ судебной практики",
                "Правовые рекомендации"
            ],
            input_schema={
                "query": "str - тема исследования",
                "context": "str - контекст из документов"
            },
            output_schema={
                "laws": "List[Dict] - релевантные законы",
                "court_practice": "List[Dict] - судебная практика",
                "recommendations": "str - рекомендации"
            },
            estimated_duration=45,
            can_parallelize=True
        )
    
    def can_handle(self, intent: TaskIntent) -> bool:
        return intent == TaskIntent.RESEARCH
    
    async def execute(
        self,
        context: ExecutionContext,
        params: Dict[str, Any]
    ) -> SubAgentResult:
        """Провести правовое исследование"""
        try:
            query = params.get("query", context.user_task)
            
            # Получаем контекст из предыдущих результатов (если есть summarizer)
            doc_context = ""
            if "summarizer" in context.previous_results:
                doc_context = context.previous_results["summarizer"].get("summary", "")
            
            combined_context = f"Задача: {query}\n\nКонтекст документа:\n{doc_context}"
            
            if self.llm:
                prompt = ChatPromptTemplate.from_template(LEGAL_RESEARCH_PROMPT)
                chain = prompt | self.llm
                
                response = await chain.ainvoke({"context": combined_context})
                research_result = response.content if hasattr(response, 'content') else str(response)
            else:
                research_result = "Требуется LLM для проведения правового исследования"
            
            return SubAgentResult(
                agent_name=self.spec.name,
                success=True,
                data={
                    "research": research_result,
                    "query": query
                },
                summary=research_result[:400] + "..." if len(research_result) > 400 else research_result
            )
            
        except Exception as e:
            logger.error(f"LegalResearcherAgent error: {e}", exc_info=True)
            return SubAgentResult(
                agent_name=self.spec.name,
                success=False,
                data={},
                summary="Ошибка при исследовании",
                error=str(e)
            )

