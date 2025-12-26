"""Prompt Library models for reusable prompts"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Boolean, Integer
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class PromptTemplate(Base):
    """
    PromptTemplate model - stores reusable prompt templates.
    
    Similar to Harvey's Prompts feature that allows users to
    save and reuse frequently used queries.
    """
    __tablename__ = "prompt_templates"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Ownership - null for system prompts
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Categorization
    category = Column(String(100), nullable=False, index=True)  # contract, litigation, research, etc.
    subcategory = Column(String(100), nullable=True)
    
    # Content
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    prompt_text = Column(Text, nullable=False)
    
    # Variables - placeholders that can be filled in
    # Format: [{"name": "party_name", "type": "text", "description": "Название стороны", "required": true}]
    variables = Column(JSON, default=list)
    
    # Tags for search
    tags = Column(JSON, default=list)  # ["due diligence", "M&A"]
    
    # Visibility
    is_public = Column(Boolean, default=False)  # Shared with all users
    is_system = Column(Boolean, default=False)  # System-provided template
    
    # Usage tracking
    usage_count = Column(Integer, default=0)
    last_used_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="prompt_templates")
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "category": self.category,
            "subcategory": self.subcategory,
            "title": self.title,
            "description": self.description,
            "prompt_text": self.prompt_text,
            "variables": self.variables or [],
            "tags": self.tags or [],
            "is_public": self.is_public,
            "is_system": self.is_system,
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def render(self, variables: dict) -> str:
        """
        Render prompt with provided variables
        
        Args:
            variables: Dictionary of variable name -> value
            
        Returns:
            Rendered prompt text
        """
        result = self.prompt_text
        
        for var_def in (self.variables or []):
            var_name = var_def.get("name")
            if var_name and var_name in variables:
                placeholder = f"{{{{{var_name}}}}}"
                result = result.replace(placeholder, str(variables[var_name]))
        
        return result
    
    def increment_usage(self):
        """Increment usage count and update last used timestamp"""
        self.usage_count = (self.usage_count or 0) + 1
        self.last_used_at = datetime.utcnow()


class PromptCategory(Base):
    """
    PromptCategory model - defines available categories for prompts.
    """
    __tablename__ = "prompt_categories"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), nullable=False, unique=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)  # Icon name for UI
    order_index = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "icon": self.icon,
            "order_index": self.order_index,
        }


# Default system categories
DEFAULT_CATEGORIES = [
    {
        "name": "contract",
        "display_name": "Договоры",
        "description": "Анализ договоров и контрактов",
        "icon": "file-text",
        "order_index": 1,
    },
    {
        "name": "litigation",
        "display_name": "Судебные дела",
        "description": "Анализ судебных материалов",
        "icon": "gavel",
        "order_index": 2,
    },
    {
        "name": "due_diligence",
        "display_name": "Due Diligence",
        "description": "Проверка документов для сделок",
        "icon": "search",
        "order_index": 3,
    },
    {
        "name": "research",
        "display_name": "Исследование",
        "description": "Юридическое исследование",
        "icon": "book-open",
        "order_index": 4,
    },
    {
        "name": "compliance",
        "display_name": "Compliance",
        "description": "Проверка соответствия требованиям",
        "icon": "shield-check",
        "order_index": 5,
    },
    {
        "name": "custom",
        "display_name": "Прочее",
        "description": "Другие запросы",
        "icon": "folder",
        "order_index": 99,
    },
]

# Default system prompts
DEFAULT_PROMPTS = [
    {
        "category": "contract",
        "title": "Выделить ключевые условия",
        "description": "Извлекает основные условия из договора",
        "prompt_text": "Проанализируй договор и выдели следующие ключевые условия:\n1. Стороны договора\n2. Предмет договора\n3. Цена и порядок оплаты\n4. Сроки исполнения\n5. Ответственность сторон\n6. Порядок расторжения\n\nДля каждого условия укажи конкретные формулировки из документа.",
        "variables": [],
        "tags": ["договор", "условия", "анализ"],
    },
    {
        "category": "contract",
        "title": "Найти риски в договоре",
        "description": "Анализирует договор на наличие рисков для {{party_name}}",
        "prompt_text": "Проанализируй договор с точки зрения рисков для {{party_name}}. Выдели:\n1. Финансовые риски\n2. Юридические риски\n3. Операционные риски\n4. Репутационные риски\n\nДля каждого риска укажи:\n- Описание риска\n- Конкретный пункт договора\n- Рекомендации по минимизации",
        "variables": [{"name": "party_name", "type": "text", "description": "Название стороны", "required": True}],
        "tags": ["договор", "риски", "анализ"],
    },
    {
        "category": "litigation",
        "title": "Хронология событий",
        "description": "Составляет хронологию событий по материалам дела",
        "prompt_text": "Составь подробную хронологию событий на основе представленных документов. Для каждого события укажи:\n1. Дату (или период)\n2. Описание события\n3. Участников\n4. Источник информации (документ)\n\nОтсортируй события в хронологическом порядке.",
        "variables": [],
        "tags": ["суд", "хронология", "события"],
    },
    {
        "category": "litigation",
        "title": "Найти противоречия",
        "description": "Ищет противоречия между документами или показаниями",
        "prompt_text": "Проанализируй представленные документы и найди все противоречия:\n1. Противоречия в фактах\n2. Противоречия в датах\n3. Противоречия в суммах\n4. Противоречия между документами\n\nДля каждого противоречия укажи:\n- Суть противоречия\n- Источники (документы)\n- Возможное объяснение\n- Юридическое значение",
        "variables": [],
        "tags": ["суд", "противоречия", "анализ"],
    },
    {
        "category": "due_diligence",
        "title": "Проверка корпоративных документов",
        "description": "Проверяет полноту и корректность корпоративных документов",
        "prompt_text": "Проведи проверку корпоративных документов {{company_name}}:\n1. Учредительные документы (устав, учредительный договор)\n2. Решения органов управления\n3. Реестр участников/акционеров\n4. Полномочия подписантов\n\nДля каждой категории укажи:\n- Наличие документа\n- Актуальность\n- Выявленные проблемы\n- Рекомендации",
        "variables": [{"name": "company_name", "type": "text", "description": "Название компании", "required": True}],
        "tags": ["due diligence", "корпоративные документы"],
    },
    {
        "category": "research",
        "title": "Обзор судебной практики",
        "description": "Анализирует релевантную судебную практику",
        "prompt_text": "Проанализируй судебную практику по вопросу: {{legal_question}}\n\nПредоставь:\n1. Основные позиции судов\n2. Ключевые прецеденты\n3. Тенденции в практике\n4. Рекомендации по стратегии\n\nОснови анализ на представленных документах и материалах.",
        "variables": [{"name": "legal_question", "type": "text", "description": "Юридический вопрос", "required": True}],
        "tags": ["исследование", "судебная практика"],
    },
    {
        "category": "compliance",
        "title": "Проверка на соответствие регуляторным требованиям",
        "description": "Проверяет документы на соответствие требованиям законодательства",
        "prompt_text": "Проверь представленные документы на соответствие требованиям {{regulation_name}}:\n\n1. Обязательные элементы\n2. Сроки и порядок\n3. Формы и форматы\n4. Подписи и полномочия\n\nСоставь чек-лист соответствия с указанием статуса каждого требования.",
        "variables": [{"name": "regulation_name", "type": "text", "description": "Название регуляции/закона", "required": True}],
        "tags": ["compliance", "регуляторные требования"],
    },
]

