"""Workflow Templates - готовые сценарии работы для типовых задач"""
from typing import Dict, List, Any
from pydantic import BaseModel, Field


class WorkflowStep(BaseModel):
    """Шаг в workflow"""
    agent: str = Field(..., description="Имя агента для выполнения шага")
    name: str = Field(..., description="Название шага")
    description: str = Field(..., description="Описание шага")
    requires_approval: bool = Field(False, description="Требуется ли одобрение перед выполнением (использует interrupt_before)")


class WorkflowTemplate(BaseModel):
    """Шаблон workflow - предопределённый сценарий работы"""
    id: str = Field(..., description="Уникальный идентификатор шаблона")
    name: str = Field(..., description="Название workflow")
    description: str = Field(..., description="Описание workflow")
    steps: List[WorkflowStep] = Field(..., description="Список шагов для выполнения")
    estimated_time: str = Field(..., description="Примерное время выполнения (например, '5-10 минут')")
    output_format: str = Field("report", description="Формат выходных данных")


# Определения workflow templates
WORKFLOW_TEMPLATES: Dict[str, WorkflowTemplate] = {
    "due_diligence": WorkflowTemplate(
        id="due_diligence",
        name="Due Diligence",
        description="Полная проверка документов сделки. Выполняет комплексный анализ всех документов с поиском рисков и противоречий.",
        steps=[
            WorkflowStep(
                agent="document_classifier",
                name="Классификация",
                description="Определение типов документов и их категоризация"
            ),
            WorkflowStep(
                agent="entity_extraction",
                name="Сущности",
                description="Извлечение сторон, дат, сумм и других ключевых сущностей"
            ),
            WorkflowStep(
                agent="timeline",
                name="Хронология",
                description="Построение временной шкалы событий"
            ),
            WorkflowStep(
                agent="discrepancy",
                name="Противоречия",
                description="Поиск несоответствий и противоречий между документами",
                requires_approval=True  # Требует одобрения перед анализом рисков
            ),
            WorkflowStep(
                agent="risk",
                name="Риски",
                description="Анализ юридических рисков на основе найденных противоречий",
                requires_approval=True  # Требует одобрения перед формированием отчёта
            ),
            WorkflowStep(
                agent="summary",
                name="Отчёт",
                description="Формирование итогового отчёта по результатам проверки"
            ),
        ],
        estimated_time="5-10 минут"
    ),
    "contract_review": WorkflowTemplate(
        id="contract_review",
        name="Анализ договора",
        description="Быстрый анализ договорных обязательств и условий. Подходит для первичной оценки договоров.",
        steps=[
            WorkflowStep(
                agent="key_facts",
                name="Ключевые условия",
                description="Извлечение основных положений и условий договора"
            ),
            WorkflowStep(
                agent="entity_extraction",
                name="Стороны",
                description="Извлечение сторон договора и их обязательств"
            ),
            WorkflowStep(
                agent="risk",
                name="Риски",
                description="Анализ рисков и потенциальных проблемных пунктов"
            ),
        ],
        estimated_time="3-5 минут"
    ),
    "litigation_prep": WorkflowTemplate(
        id="litigation_prep",
        name="Подготовка к судебному процессу",
        description="Анализ материалов дела для судебного процесса. Включает проверку привилегий, восстановление хронологии и анализ позиции.",
        steps=[
            WorkflowStep(
                agent="privilege_check",
                name="Привилегии",
                description="Проверка документов на адвокатскую тайну и привилегии"
            ),
            WorkflowStep(
                agent="timeline",
                name="Хронология",
                description="Восстановление хронологии событий"
            ),
            WorkflowStep(
                agent="key_facts",
                name="Факты",
                description="Извлечение юридически значимых фактов"
            ),
            WorkflowStep(
                agent="discrepancy",
                name="Противоречия",
                description="Поиск слабых мест в позиции противной стороны",
                requires_approval=True
            ),
            WorkflowStep(
                agent="relationship",
                name="Связи",
                description="Построение графа связей между участниками процесса"
            ),
        ],
        estimated_time="7-12 минут"
    ),
    "entity_analysis": WorkflowTemplate(
        id="entity_analysis",
        name="Анализ сущностей",
        description="Извлечение и анализ всех сущностей в деле. Подходит для первоначального изучения дела.",
        steps=[
            WorkflowStep(
                agent="document_classifier",
                name="Классификация",
                description="Классификация документов"
            ),
            WorkflowStep(
                agent="entity_extraction",
                name="Извлечение сущностей",
                description="Извлечение людей, организаций, дат, сумм"
            ),
            WorkflowStep(
                agent="relationship",
                name="Связи",
                description="Построение графа связей между сущностями"
            ),
        ],
        estimated_time="3-5 минут"
    ),
    "risk_assessment": WorkflowTemplate(
        id="risk_assessment",
        name="Оценка рисков",
        description="Комплексная оценка рисков в деле. Включает поиск противоречий и анализ рисков.",
        steps=[
            WorkflowStep(
                agent="key_facts",
                name="Ключевые факты",
                description="Извлечение ключевых фактов дела"
            ),
            WorkflowStep(
                agent="discrepancy",
                name="Противоречия",
                description="Поиск противоречий и несоответствий",
                requires_approval=True
            ),
            WorkflowStep(
                agent="risk",
                name="Анализ рисков",
                description="Комплексный анализ юридических рисков"
            ),
        ],
        estimated_time="4-6 минут"
    ),
}


def get_workflow_template(template_id: str) -> WorkflowTemplate:
    """
    Получить workflow template по ID
    
    Args:
        template_id: ID шаблона
        
    Returns:
        WorkflowTemplate
        
    Raises:
        ValueError: Если шаблон не найден
    """
    template = WORKFLOW_TEMPLATES.get(template_id)
    if not template:
        raise ValueError(f"Workflow template '{template_id}' not found. Available templates: {list(WORKFLOW_TEMPLATES.keys())}")
    return template


def list_workflow_templates() -> List[WorkflowTemplate]:
    """
    Получить список всех доступных workflow templates
    
    Returns:
        Список WorkflowTemplate
    """
    return list(WORKFLOW_TEMPLATES.values())


