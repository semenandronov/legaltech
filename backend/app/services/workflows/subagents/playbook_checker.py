"""Playbook Checker SubAgent - Проверка документов на риски"""
from typing import Dict, Any
from app.services.workflows.supervisor_agent import (
    BaseSubAgent, SubAgentSpec, SubAgentResult, ExecutionContext, TaskIntent
)
import logging

logger = logging.getLogger(__name__)


class PlaybookCheckerAgent(BaseSubAgent):
    """Агент для проверки документов на соответствие правилам"""
    
    def __init__(self, db=None):
        self.db = db
    
    @property
    def spec(self) -> SubAgentSpec:
        return SubAgentSpec(
            name="playbook_checker",
            description="Проверяет документы на соответствие правилам и выявляет риски",
            capabilities=[
                "Проверка на стандартные риски",
                "Выявление проблемных условий",
                "Рекомендации по исправлению"
            ],
            input_schema={
                "file_ids": "List[str] - ID документов для проверки",
                "playbook_id": "str - ID playbook (опционально)"
            },
            output_schema={
                "issues": "List[Dict] - найденные проблемы",
                "risk_level": "str - уровень риска",
                "recommendations": "List[str] - рекомендации"
            },
            estimated_duration=60,
            can_parallelize=True
        )
    
    def can_handle(self, intent: TaskIntent) -> bool:
        return intent in [TaskIntent.CHECK_RISKS, TaskIntent.FULL_ANALYSIS]
    
    async def execute(
        self,
        context: ExecutionContext,
        params: Dict[str, Any]
    ) -> SubAgentResult:
        """Проверить документы на риски"""
        try:
            file_ids = params.get("file_ids", context.file_ids)
            playbook_id = params.get("playbook_id")
            
            if not file_ids:
                return SubAgentResult(
                    agent_name=self.spec.name,
                    success=False,
                    data={},
                    summary="Не указаны файлы для проверки",
                    error="No file_ids provided"
                )
            
            # Используем PlaybookChecker сервис
            from app.services.playbook_checker import PlaybookChecker
            
            checker = PlaybookChecker(self.db)
            
            all_issues = []
            all_recommendations = []
            
            for file_id in file_ids:
                try:
                    # Получаем файл
                    from app.models.case import File
                    file = self.db.query(File).filter(File.id == file_id).first()
                    
                    if not file or not file.original_text:
                        continue
                    
                    # Проверяем
                    result = await checker.check_document(
                        document_text=file.original_text,
                        document_id=file_id,
                        playbook_id=playbook_id
                    )
                    
                    if result.get("issues"):
                        all_issues.extend(result["issues"])
                    if result.get("recommendations"):
                        all_recommendations.extend(result["recommendations"])
                        
                except Exception as e:
                    logger.warning(f"Failed to check file {file_id}: {e}")
            
            # Определяем уровень риска
            if len(all_issues) > 5:
                risk_level = "high"
            elif len(all_issues) > 2:
                risk_level = "medium"
            elif all_issues:
                risk_level = "low"
            else:
                risk_level = "none"
            
            summary = f"Найдено проблем: {len(all_issues)}, уровень риска: {risk_level}"
            
            return SubAgentResult(
                agent_name=self.spec.name,
                success=True,
                data={
                    "issues": all_issues,
                    "risk_level": risk_level,
                    "recommendations": all_recommendations,
                    "files_checked": len(file_ids)
                },
                summary=summary
            )
            
        except Exception as e:
            logger.error(f"PlaybookCheckerAgent error: {e}", exc_info=True)
            return SubAgentResult(
                agent_name=self.spec.name,
                success=False,
                data={},
                summary="Ошибка при проверке",
                error=str(e)
            )

