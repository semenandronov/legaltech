"""RAG Searcher SubAgent - Семантический поиск и ответы на вопросы"""
from typing import Dict, Any
from app.services.workflows.supervisor_agent import (
    BaseSubAgent, SubAgentSpec, SubAgentResult, ExecutionContext, TaskIntent
)
import logging

logger = logging.getLogger(__name__)


class RAGSearcherAgent(BaseSubAgent):
    """Агент для семантического поиска по документам"""
    
    def __init__(self, db=None):
        self.db = db
    
    @property
    def spec(self) -> SubAgentSpec:
        return SubAgentSpec(
            name="rag_searcher",
            description="Семантический поиск и ответ на вопросы по документам",
            capabilities=[
                "Поиск релевантной информации",
                "Ответы на конкретные вопросы",
                "Цитирование источников"
            ],
            input_schema={
                "query": "str - вопрос или поисковый запрос",
                "file_ids": "List[str] - ID файлов для поиска",
                "top_k": "int - количество результатов"
            },
            output_schema={
                "answer": "str - ответ на вопрос",
                "sources": "List[Dict] - источники",
                "confidence": "float - уверенность"
            },
            estimated_duration=20,
            can_parallelize=True
        )
    
    def can_handle(self, intent: TaskIntent) -> bool:
        return intent == TaskIntent.ANSWER_QUESTION
    
    async def execute(
        self,
        context: ExecutionContext,
        params: Dict[str, Any]
    ) -> SubAgentResult:
        """Выполнить поиск и ответить на вопрос"""
        try:
            query = params.get("query", context.user_task)
            file_ids = params.get("file_ids", context.file_ids)
            top_k = params.get("top_k", 5)
            
            # Получаем case_id из документов
            case_id = None
            if context.documents:
                case_id = context.documents[0].get("case_id")
            
            if not case_id and self.db and file_ids:
                from app.models.case import File
                file = self.db.query(File).filter(File.id == file_ids[0]).first()
                if file:
                    case_id = file.case_id
            
            if not case_id:
                return SubAgentResult(
                    agent_name=self.spec.name,
                    success=False,
                    data={},
                    summary="Не удалось определить case_id",
                    error="case_id not found"
                )
            
            # Используем RAG сервис
            from app.services.rag_service import RAGService
            
            rag_service = RAGService()
            docs = rag_service.retrieve_context(
                case_id=case_id,
                query=query,
                k=top_k,
                db=self.db,
                file_ids=file_ids
            )
            
            if not docs:
                return SubAgentResult(
                    agent_name=self.spec.name,
                    success=True,
                    data={"answer": "Релевантная информация не найдена", "sources": []},
                    summary="Информация не найдена в документах"
                )
            
            # Генерируем ответ
            answer = rag_service.generate_answer(
                question=query,
                documents=docs,
                db=self.db
            )
            
            sources = [
                {
                    "content": doc.page_content[:200],
                    "metadata": doc.metadata
                }
                for doc in docs[:3]
            ]
            
            return SubAgentResult(
                agent_name=self.spec.name,
                success=True,
                data={
                    "answer": answer,
                    "sources": sources,
                    "query": query
                },
                summary=answer[:300] + "..." if len(answer) > 300 else answer
            )
            
        except Exception as e:
            logger.error(f"RAGSearcherAgent error: {e}", exc_info=True)
            return SubAgentResult(
                agent_name=self.spec.name,
                success=False,
                data={},
                summary="Ошибка при поиске",
                error=str(e)
            )


