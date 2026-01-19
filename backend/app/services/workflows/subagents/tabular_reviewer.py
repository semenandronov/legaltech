"""Tabular Reviewer SubAgent - Сравнительный анализ документов"""
from typing import Dict, Any, List
from app.services.workflows.supervisor_agent import (
    BaseSubAgent, SubAgentSpec, SubAgentResult, ExecutionContext, TaskIntent
)
import logging

logger = logging.getLogger(__name__)


class TabularReviewerAgent(BaseSubAgent):
    """Агент для создания сравнительных таблиц из документов"""
    
    def __init__(self, db=None):
        self.db = db
    
    @property
    def spec(self) -> SubAgentSpec:
        return SubAgentSpec(
            name="tabular_reviewer",
            description="Создаёт сравнительную таблицу из нескольких документов",
            capabilities=[
                "Сравнение документов",
                "Извлечение данных в таблицу",
                "Выявление различий"
            ],
            input_schema={
                "file_ids": "List[str] - ID документов для сравнения",
                "columns": "List[str] - колонки для извлечения"
            },
            output_schema={
                "table": "List[Dict] - данные таблицы",
                "columns": "List[str] - колонки",
                "summary": "str - краткое описание"
            },
            estimated_duration=90,
            can_parallelize=False  # Требует все документы сразу
        )
    
    def can_handle(self, intent: TaskIntent) -> bool:
        return intent == TaskIntent.COMPARE
    
    async def execute(
        self,
        context: ExecutionContext,
        params: Dict[str, Any]
    ) -> SubAgentResult:
        """Создать сравнительную таблицу"""
        try:
            file_ids = params.get("file_ids", context.file_ids)
            columns = params.get("columns", [])
            
            if not file_ids or len(file_ids) < 2:
                return SubAgentResult(
                    agent_name=self.spec.name,
                    success=False,
                    data={},
                    summary="Для сравнения нужно минимум 2 документа",
                    error="Need at least 2 documents"
                )
            
            # Используем TabularReviewService
            from app.services.tabular_review_service import TabularReviewService
            
            service = TabularReviewService(self.db)
            
            # Получаем case_id
            case_id = None
            if context.documents:
                case_id = context.documents[0].get("case_id")
            
            if not case_id and self.db:
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
            
            # Создаём review
            result = await service.create_review(
                case_id=case_id,
                file_ids=file_ids,
                columns=columns or ["Название", "Дата", "Стороны", "Сумма", "Срок"]
            )
            
            table_data = result.get("rows", [])
            used_columns = result.get("columns", columns)
            
            summary = f"Создана таблица: {len(table_data)} строк, {len(used_columns)} колонок"
            
            return SubAgentResult(
                agent_name=self.spec.name,
                success=True,
                data={
                    "table": table_data,
                    "columns": used_columns,
                    "files_count": len(file_ids)
                },
                summary=summary,
                artifacts=[{
                    "type": "tabular_review",
                    "data": result
                }]
            )
            
        except Exception as e:
            logger.error(f"TabularReviewerAgent error: {e}", exc_info=True)
            return SubAgentResult(
                agent_name=self.spec.name,
                success=False,
                data={},
                summary="Ошибка при создании таблицы",
                error=str(e)
            )


