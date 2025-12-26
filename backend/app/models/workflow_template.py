"""Workflow Template models for predefined analysis workflows"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Boolean, Integer
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class WorkflowTemplate(Base):
    """
    WorkflowTemplate model - stores predefined analysis workflows.
    
    Similar to Harvey's Workflows feature that provides
    structured templates for common legal tasks like M&A Due Diligence,
    Litigation Review, Contract Analysis, etc.
    """
    __tablename__ = "workflow_templates"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Basic info
    name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=False, index=True)
    
    # Workflow definition
    # Format: [{"step_id": "1", "name": "...", "prompt": "...", "agent": "...", "required": true}]
    steps = Column(JSON, nullable=False, default=list)
    
    # Associated prompts for each step
    # Format: {"step_id": "prompt_template_id"}
    prompts = Column(JSON, default=dict)
    
    # Associated tabular review template
    tabular_template_id = Column(
        String, 
        ForeignKey("tabular_column_templates.id", ondelete="SET NULL"), 
        nullable=True
    )
    
    # Review table columns for this workflow
    # Format: [{"name": "column_name", "prompt": "extraction prompt", "type": "text"}]
    review_columns = Column(JSON, default=list)
    
    # Visibility
    is_system = Column(Boolean, default=False)  # System-provided template
    is_public = Column(Boolean, default=False)  # Shared with all users
    
    # Ownership for custom templates
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Usage tracking
    usage_count = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="workflow_templates")
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "steps": self.steps or [],
            "prompts": self.prompts or {},
            "tabular_template_id": self.tabular_template_id,
            "review_columns": self.review_columns or [],
            "is_system": self.is_system,
            "is_public": self.is_public,
            "user_id": self.user_id,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def increment_usage(self):
        """Increment usage count"""
        self.usage_count = (self.usage_count or 0) + 1


# Default system workflows
DEFAULT_WORKFLOWS = [
    {
        "name": "ma_due_diligence",
        "display_name": "M&A Due Diligence",
        "description": "Комплексная проверка документов для сделок M&A. Включает анализ корпоративных документов, договоров, рисков и обязательств.",
        "category": "due_diligence",
        "steps": [
            {
                "step_id": "1",
                "name": "Классификация документов",
                "description": "Автоматическая классификация загруженных документов по типам",
                "agent": "classification",
                "required": True,
            },
            {
                "step_id": "2", 
                "name": "Извлечение ключевых сущностей",
                "description": "Извлечение названий компаний, имен, дат, сумм",
                "agent": "entity_extraction",
                "required": True,
            },
            {
                "step_id": "3",
                "name": "Анализ корпоративной структуры",
                "description": "Проверка учредительных документов и структуры владения",
                "agent": "key_facts",
                "required": True,
            },
            {
                "step_id": "4",
                "name": "Анализ договорных обязательств",
                "description": "Выявление ключевых обязательств по договорам",
                "agent": "key_facts",
                "required": True,
            },
            {
                "step_id": "5",
                "name": "Оценка рисков",
                "description": "Выявление юридических и финансовых рисков",
                "agent": "risk",
                "required": True,
            },
            {
                "step_id": "6",
                "name": "Итоговый отчет",
                "description": "Формирование сводного отчета по due diligence",
                "agent": "summary",
                "required": True,
            },
        ],
        "review_columns": [
            {"name": "Тип документа", "prompt": "Определи тип документа", "type": "text"},
            {"name": "Дата", "prompt": "Укажи дату документа", "type": "date"},
            {"name": "Стороны", "prompt": "Перечисли стороны документа", "type": "text"},
            {"name": "Ключевые условия", "prompt": "Выдели ключевые условия", "type": "text"},
            {"name": "Риски", "prompt": "Укажи выявленные риски", "type": "text"},
            {"name": "Статус", "prompt": "Укажи статус документа (действующий/недействующий)", "type": "text"},
        ],
    },
    {
        "name": "litigation_review",
        "display_name": "Litigation Review",
        "description": "Анализ материалов судебного дела. Построение хронологии, выявление ключевых фактов и противоречий.",
        "category": "litigation",
        "steps": [
            {
                "step_id": "1",
                "name": "Классификация документов",
                "description": "Классификация процессуальных документов",
                "agent": "classification",
                "required": True,
            },
            {
                "step_id": "2",
                "name": "Построение хронологии",
                "description": "Создание таймлайна событий по материалам дела",
                "agent": "timeline",
                "required": True,
            },
            {
                "step_id": "3",
                "name": "Выделение ключевых фактов",
                "description": "Извлечение ключевых фактов из документов",
                "agent": "key_facts",
                "required": True,
            },
            {
                "step_id": "4",
                "name": "Поиск противоречий",
                "description": "Выявление противоречий между документами и показаниями",
                "agent": "discrepancy",
                "required": True,
            },
            {
                "step_id": "5",
                "name": "Анализ доказательной базы",
                "description": "Оценка силы доказательств",
                "agent": "risk",
                "required": False,
            },
            {
                "step_id": "6",
                "name": "Сводный анализ",
                "description": "Формирование аналитической записки по делу",
                "agent": "summary",
                "required": True,
            },
        ],
        "review_columns": [
            {"name": "Тип документа", "prompt": "Определи тип процессуального документа", "type": "text"},
            {"name": "Дата", "prompt": "Укажи дату документа", "type": "date"},
            {"name": "От кого", "prompt": "От какой стороны документ", "type": "text"},
            {"name": "Ключевые утверждения", "prompt": "Выдели ключевые утверждения", "type": "text"},
            {"name": "Ссылки на доказательства", "prompt": "Укажи ссылки на доказательства", "type": "text"},
        ],
    },
    {
        "name": "contract_analysis",
        "display_name": "Contract Analysis",
        "description": "Детальный анализ договоров. Извлечение условий, сроков, обязательств и рисков.",
        "category": "contract",
        "steps": [
            {
                "step_id": "1",
                "name": "Извлечение реквизитов",
                "description": "Извлечение сторон, дат, номеров договоров",
                "agent": "entity_extraction",
                "required": True,
            },
            {
                "step_id": "2",
                "name": "Анализ условий",
                "description": "Детальный анализ условий договора",
                "agent": "key_facts",
                "required": True,
            },
            {
                "step_id": "3",
                "name": "Выявление рисков",
                "description": "Анализ рисков для сторон договора",
                "agent": "risk",
                "required": True,
            },
            {
                "step_id": "4",
                "name": "Резюме",
                "description": "Краткое резюме договора",
                "agent": "summary",
                "required": True,
            },
        ],
        "review_columns": [
            {"name": "Номер договора", "prompt": "Укажи номер договора", "type": "text"},
            {"name": "Дата заключения", "prompt": "Укажи дату заключения", "type": "date"},
            {"name": "Срок действия", "prompt": "Укажи срок действия договора", "type": "text"},
            {"name": "Стороны", "prompt": "Перечисли стороны договора", "type": "text"},
            {"name": "Предмет договора", "prompt": "Опиши предмет договора", "type": "text"},
            {"name": "Цена", "prompt": "Укажи цену или порядок определения цены", "type": "text"},
            {"name": "Ключевые обязательства", "prompt": "Выдели ключевые обязательства сторон", "type": "text"},
            {"name": "Ответственность", "prompt": "Укажи условия об ответственности", "type": "text"},
        ],
    },
    {
        "name": "regulatory_compliance",
        "display_name": "Regulatory Compliance",
        "description": "Проверка документов на соответствие регуляторным требованиям.",
        "category": "compliance",
        "steps": [
            {
                "step_id": "1",
                "name": "Классификация документов",
                "description": "Определение типов регуляторных документов",
                "agent": "classification",
                "required": True,
            },
            {
                "step_id": "2",
                "name": "Извлечение требований",
                "description": "Извлечение регуляторных требований",
                "agent": "key_facts",
                "required": True,
            },
            {
                "step_id": "3",
                "name": "Проверка соответствия",
                "description": "Сопоставление с применимыми требованиями",
                "agent": "discrepancy",
                "required": True,
            },
            {
                "step_id": "4",
                "name": "Оценка рисков несоответствия",
                "description": "Анализ рисков при несоответствии",
                "agent": "risk",
                "required": True,
            },
            {
                "step_id": "5",
                "name": "Отчет о соответствии",
                "description": "Формирование отчета о соответствии",
                "agent": "summary",
                "required": True,
            },
        ],
        "review_columns": [
            {"name": "Документ", "prompt": "Название документа", "type": "text"},
            {"name": "Применимое требование", "prompt": "Какому требованию должен соответствовать", "type": "text"},
            {"name": "Статус соответствия", "prompt": "Соответствует/Не соответствует/Частично", "type": "text"},
            {"name": "Комментарий", "prompt": "Комментарий по соответствию", "type": "text"},
        ],
    },
]

