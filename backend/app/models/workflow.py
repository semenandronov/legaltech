"""Workflow models for Agentic AI execution"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Boolean, Integer, DECIMAL
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class WorkflowDefinition(Base):
    """
    WorkflowDefinition - шаблон workflow для автономного выполнения задач.
    
    Workflow - это Agentic AI система, которая:
    1. Понимает задачу на natural language
    2. Планирует шаги выполнения
    3. Использует инструменты workflow-ядра
    4. Проверяет результаты
    5. Генерирует структурированный отчёт
    """
    __tablename__ = "workflow_definitions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Основная информация
    name = Column(String(255), nullable=False, unique=True)
    display_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Категория workflow
    category = Column(String(100), nullable=False, index=True)  # due_diligence, litigation, compliance, research, contract_analysis
    
    # Шаблон плана (опционально - для ускорения планирования)
    default_plan = Column(JSON, nullable=True)
    # Формат: {
    #   "goals": ["цель 1", "цель 2"],
    #   "steps": [
    #     {"id": "step_1", "name": "...", "tool": "tabular_review", "depends_on": []}
    #   ]
    # }
    
    # Доступные инструменты для этого workflow
    available_tools = Column(JSON, nullable=False, default=list)
    # Например: ["tabular_review", "legal_db", "rag", "playbook_check", "document_draft"]
    
    # Схема выходного формата (JSON Schema)
    output_schema = Column(JSON, nullable=True)
    
    # Промпты
    planning_prompt = Column(Text, nullable=True)  # Промпт для планирования
    summary_prompt = Column(Text, nullable=True)   # Промпт для резюмирования
    
    # Настройки
    max_steps = Column(Integer, default=50)  # Максимум шагов
    timeout_minutes = Column(Integer, default=60)  # Таймаут
    requires_approval = Column(Boolean, default=False)  # Требует одобрения перед выполнением
    
    # Видимость
    is_system = Column(Boolean, default=False)
    is_public = Column(Boolean, default=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Статистика
    usage_count = Column(Integer, default=0)
    avg_execution_time = Column(Integer, nullable=True)  # Среднее время в секундах
    success_rate = Column(DECIMAL(5, 2), nullable=True)  # Процент успешных выполнений
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", backref="workflow_definitions")
    executions = relationship("WorkflowExecution", back_populates="definition", cascade="all, delete-orphan")
    
    def to_dict(self, include_details: bool = False):
        """Convert to dictionary for API responses"""
        # Формируем config для совместимости с фронтендом
        # Фронтенд ожидает config.steps для отображения шагов workflow
        steps = []
        if self.default_plan and isinstance(self.default_plan, dict):
            plan_steps = self.default_plan.get("steps", [])
            for step in plan_steps:
                steps.append({
                    "id": step.get("id"),
                    "name": step.get("name"),
                    "tool": step.get("tool"),
                    "description": step.get("description", ""),
                    "depends_on": step.get("depends_on", [])
                })
        
        # Если нет default_plan, создаём steps из available_tools
        if not steps and self.available_tools:
            for i, tool in enumerate(self.available_tools):
                steps.append({
                    "id": f"step_{i+1}",
                    "name": tool,
                    "tool": tool,
                    "description": "",
                    "depends_on": []
                })
        
        result = {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "available_tools": self.available_tools or [],
            "is_system": self.is_system,
            "is_public": self.is_public,
            "user_id": self.user_id,
            "usage_count": self.usage_count,
            "avg_execution_time": self.avg_execution_time,
            "success_rate": float(self.success_rate) if self.success_rate else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            # Добавляем config для совместимости с фронтендом
            "config": {
                "steps": steps,
                "output_format": None,
                "require_approval": self.requires_approval
            },
            # Оценка времени выполнения
            "estimated_time": f"~{len(steps) * 2} мин" if steps else "~5 мин"
        }
        
        if include_details:
            result["default_plan"] = self.default_plan
            result["output_schema"] = self.output_schema
            result["planning_prompt"] = self.planning_prompt
            result["summary_prompt"] = self.summary_prompt
            result["max_steps"] = self.max_steps
            result["timeout_minutes"] = self.timeout_minutes
            result["requires_approval"] = self.requires_approval
        
        return result


class WorkflowExecution(Base):
    """
    WorkflowExecution - запуск workflow.
    
    Статусы:
    - pending: Ожидает начала
    - planning: Планирование шагов
    - awaiting_approval: Ожидает одобрения плана
    - executing: Выполнение шагов
    - validating: Валидация результатов
    - generating_report: Генерация отчёта
    - completed: Успешно завершено
    - failed: Ошибка
    - cancelled: Отменено
    """
    __tablename__ = "workflow_executions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Связи
    definition_id = Column(String, ForeignKey("workflow_definitions.id", ondelete="SET NULL"), nullable=True, index=True)
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Входные данные
    user_task = Column(Text, nullable=False)  # Задача пользователя на natural language
    input_config = Column(JSON, nullable=True)  # Дополнительные параметры
    selected_file_ids = Column(JSON, nullable=True)  # Список ID файлов для анализа
    
    # План выполнения (генерируется PlanningAgent)
    execution_plan = Column(JSON, nullable=True)
    # Формат: {
    #   "goals": [
    #     {"id": "goal_1", "description": "...", "subgoals": [...]}
    #   ],
    #   "steps": [
    #     {
    #       "id": "step_1",
    #       "name": "...",
    #       "tool": "tabular_review",
    #       "tool_params": {...},
    #       "depends_on": [],
    #       "expected_output": "..."
    #     }
    #   ]
    # }
    
    # Статус выполнения
    status = Column(String(50), nullable=False, default="pending", index=True)
    current_step_id = Column(String(100), nullable=True)
    progress_percent = Column(Integer, default=0)
    status_message = Column(Text, nullable=True)  # Текущее сообщение о статусе
    
    # Результаты
    results = Column(JSON, nullable=True)  # Структурированные результаты
    # Формат зависит от output_schema workflow
    
    # Артефакты (созданные документы, таблицы)
    artifacts = Column(JSON, nullable=True)
    # Формат: {
    #   "reports": [{"id": "...", "name": "...", "type": "pdf"}],
    #   "tables": [{"id": "...", "name": "..."}],
    #   "documents": [{"id": "...", "name": "..."}]
    # }
    
    # Итоговое резюме
    summary = Column(Text, nullable=True)
    
    # Ошибка
    error_message = Column(Text, nullable=True)
    error_step_id = Column(String(100), nullable=True)
    
    # Метрики выполнения
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    total_llm_calls = Column(Integer, default=0)
    total_tokens_used = Column(Integer, default=0)
    total_steps_completed = Column(Integer, default=0)
    total_steps_failed = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    definition = relationship("WorkflowDefinition", back_populates="executions")
    case = relationship("Case", backref="workflow_executions")
    user = relationship("User", backref="workflow_executions")
    steps = relationship("WorkflowStep", back_populates="execution", cascade="all, delete-orphan", order_by="WorkflowStep.sequence_number")
    
    def to_dict(self, include_details: bool = False):
        """Convert to dictionary for API responses"""
        result = {
            "id": self.id,
            "definition_id": self.definition_id,
            "case_id": self.case_id,
            "user_id": self.user_id,
            "user_task": self.user_task,
            "status": self.status,
            "current_step_id": self.current_step_id,
            "progress_percent": self.progress_percent,
            "status_message": self.status_message,
            "summary": self.summary,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_steps_completed": self.total_steps_completed,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        
        if include_details:
            result["input_config"] = self.input_config
            result["selected_file_ids"] = self.selected_file_ids
            result["execution_plan"] = self.execution_plan
            result["results"] = self.results
            result["artifacts"] = self.artifacts
            result["total_llm_calls"] = self.total_llm_calls
            result["total_tokens_used"] = self.total_tokens_used
            result["steps"] = [s.to_dict() for s in self.steps] if self.steps else []
        
        return result
    
    def calculate_progress(self):
        """Calculate progress percentage based on completed steps"""
        if not self.steps:
            return 0
        
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.status in ["completed", "skipped"])
        
        return int((completed / total) * 100)


class WorkflowStep(Base):
    """
    WorkflowStep - отдельный шаг выполнения workflow.
    
    Типы шагов (step_type):
    - tool_call: Вызов инструмента
    - analysis: Анализ результатов
    - validation: Валидация
    - aggregation: Агрегация данных
    - human_review: Ожидание проверки человеком
    
    Статусы:
    - pending: Ожидает выполнения
    - running: Выполняется
    - completed: Успешно завершено
    - failed: Ошибка
    - skipped: Пропущено
    - cancelled: Отменено
    """
    __tablename__ = "workflow_steps"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id = Column(String, ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Идентификатор шага в плане
    step_id = Column(String(100), nullable=False)  # Уникальный ID в рамках плана
    sequence_number = Column(Integer, nullable=False)  # Порядковый номер
    
    # Информация о шаге
    step_name = Column(String(255), nullable=False)
    step_type = Column(String(100), nullable=False)  # tool_call, analysis, validation, aggregation, human_review
    description = Column(Text, nullable=True)
    
    # Конфигурация инструмента
    tool_name = Column(String(100), nullable=True)  # tabular_review, legal_db, rag, playbook_check, summarize, extract_entities, document_draft
    tool_params = Column(JSON, nullable=True)  # Параметры вызова инструмента
    
    # Зависимости
    depends_on = Column(JSON, nullable=True)  # ["step_id_1", "step_id_2"]
    
    # Статус и результат
    status = Column(String(50), nullable=False, default="pending")
    result = Column(JSON, nullable=True)  # Результат выполнения
    output_summary = Column(Text, nullable=True)  # Краткое описание результата
    
    # Ошибка
    error = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    
    # Метрики
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    llm_calls = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    execution = relationship("WorkflowExecution", back_populates="steps")
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "step_id": self.step_id,
            "sequence_number": self.sequence_number,
            "step_name": self.step_name,
            "step_type": self.step_type,
            "description": self.description,
            "tool_name": self.tool_name,
            "tool_params": self.tool_params,
            "depends_on": self.depends_on or [],
            "status": self.status,
            "output_summary": self.output_summary,
            "error": self.error,
            "retry_count": self.retry_count,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# Константы для категорий workflow
WORKFLOW_CATEGORIES = [
    {"name": "due_diligence", "display_name": "Due Diligence", "description": "Анализ документов для M&A сделок"},
    {"name": "litigation", "display_name": "Litigation Discovery", "description": "Подготовка к судебным разбирательствам"},
    {"name": "compliance", "display_name": "Compliance Update", "description": "Проверка соответствия требованиям"},
    {"name": "research", "display_name": "Legal Research", "description": "Юридическое исследование"},
    {"name": "contract_analysis", "display_name": "Contract Analysis", "description": "Глубокий анализ контрактов"},
    {"name": "custom", "display_name": "Custom", "description": "Пользовательский workflow"},
]

# Доступные инструменты workflow
WORKFLOW_TOOLS = [
    {
        "name": "tabular_review",
        "display_name": "Tabular Review",
        "description": "Создание таблицы для массового анализа документов",
        "params_schema": {
            "type": "object",
            "properties": {
                "file_ids": {"type": "array", "items": {"type": "string"}, "description": "ID файлов для анализа"},
                "questions": {"type": "array", "items": {"type": "string"}, "description": "Вопросы/колонки для извлечения"},
                "review_name": {"type": "string", "description": "Название таблицы"}
            },
            "required": ["questions"]
        }
    },
    {
        "name": "legal_db",
        "display_name": "Справочник",
        "description": "Поиск по загруженному правовому справочнику",
        "params_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
                "max_results": {"type": "integer", "default": 10, "description": "Максимум результатов"},
                "get_full_text": {"type": "boolean", "default": False, "description": "Получить полный текст"},
                "doc_type": {"type": "string", "enum": ["law", "court_decision", "article", "commentary"]}
            },
            "required": ["query"]
        }
    },
    {
        "name": "rag",
        "display_name": "RAG Search",
        "description": "Семантический поиск по загруженным документам дела",
        "params_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос или вопрос"},
                "file_ids": {"type": "array", "items": {"type": "string"}, "description": "ID файлов (опционально)"},
                "top_k": {"type": "integer", "default": 10, "description": "Количество результатов"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "playbook_check",
        "display_name": "Playbook Check",
        "description": "Проверка документа против правил Playbook",
        "params_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "ID документа для проверки"},
                "playbook_id": {"type": "string", "description": "ID Playbook с правилами"}
            },
            "required": ["document_id", "playbook_id"]
        }
    },
    {
        "name": "document_draft",
        "display_name": "Document Draft",
        "description": "Создание черновика юридического документа",
        "params_schema": {
            "type": "object",
            "properties": {
                "document_type": {"type": "string", "enum": ["contract", "claim", "letter", "memo", "power_of_attorney", "agreement", "protocol", "act"], "description": "Тип документа"},
                "variables": {"type": "object", "description": "Данные для заполнения"},
                "instructions": {"type": "string", "description": "Дополнительные инструкции"},
                "title": {"type": "string", "description": "Название документа"}
            },
            "required": ["document_type"]
        }
    },
    {
        "name": "summarize",
        "display_name": "Summarize",
        "description": "Создание резюме документа или текста",
        "params_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Текст для резюмирования"},
                "file_id": {"type": "string", "description": "ID файла (альтернатива text)"},
                "max_length": {"type": "integer", "default": 500, "description": "Максимальная длина резюме"},
                "style": {"type": "string", "enum": ["brief", "detailed", "bullet_points"], "default": "brief"}
            }
        }
    },
    {
        "name": "extract_entities",
        "display_name": "Extract Entities",
        "description": "Извлечение именованных сущностей из текста",
        "params_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Текст для анализа"},
                "file_id": {"type": "string", "description": "ID файла (альтернатива text)"},
                "entity_types": {"type": "array", "items": {"type": "string"}, "description": "Типы сущностей: person, organization, date, money, location, contract_term"}
            }
        }
    },
]

# Алиасы отключены: поддерживаем только канонические имена инструментов.
WORKFLOW_TOOL_ALIASES = {}


def normalize_workflow_tool_name(tool_name: str) -> str:
    """Normalize workflow tool name to canonical value."""
    if not tool_name:
        return tool_name
    return WORKFLOW_TOOL_ALIASES.get(tool_name, tool_name)

# Предустановленные шаблоны workflow
SYSTEM_WORKFLOW_TEMPLATES = [
    {
        "name": "rf_contract_risk_review",
        "display_name": "РФ: Проверка договора на риски",
        "description": "Базовая проверка договора по праву РФ: условия, риски, соответствие playbook и итоговые правки.",
        "category": "contract_analysis",
        "available_tools": ["extract_entities", "summarize", "playbook_check", "legal_db", "document_draft"],
        "default_plan": {
            "goals": [
                "Извлечь ключевые условия договора",
                "Проверить соответствие внутренним правилам",
                "Подготовить итоговый пакет правок"
            ],
            "steps": [
                {"id": "extract_terms", "name": "Извлечь ключевые условия", "tool": "extract_entities", "depends_on": []},
                {"id": "contract_summary", "name": "Собрать структурное резюме", "tool": "summarize", "depends_on": ["extract_terms"]},
                {"id": "playbook_check", "name": "Проверить по playbook", "tool": "playbook_check", "depends_on": ["contract_summary"]},
                {"id": "law_links", "name": "Подобрать правовые обоснования", "tool": "legal_db", "depends_on": ["playbook_check"]},
                {"id": "final_draft", "name": "Сформировать итоговый документ", "tool": "document_draft", "depends_on": ["law_links"]},
            ]
        }
    },
    {
        "name": "rf_litigation_position",
        "display_name": "РФ: Подготовка правовой позиции",
        "description": "Подготовка позиции по спору в РФ: факты по материалам дела, нормы и итоговый проект документа.",
        "category": "litigation",
        "available_tools": ["rag", "legal_db", "summarize", "document_draft"],
        "default_plan": {
            "goals": [
                "Собрать фактическую базу по делу",
                "Найти релевантные нормы и практику",
                "Подготовить финальный документ позиции"
            ],
            "steps": [
                {"id": "fact_collection", "name": "Извлечь факты из материалов дела", "tool": "rag", "depends_on": []},
                {"id": "law_research", "name": "Подобрать нормы и практику", "tool": "legal_db", "depends_on": ["fact_collection"]},
                {"id": "position_summary", "name": "Собрать тезисы позиции", "tool": "summarize", "depends_on": ["law_research"]},
                {"id": "position_draft", "name": "Подготовить документ позиции", "tool": "document_draft", "depends_on": ["position_summary"]},
            ]
        }
    },
    {
        "name": "rf_legal_research_memo",
        "display_name": "РФ: Юридическое исследование и memo",
        "description": "Юридическое исследование по праву РФ с подбором норм/практики и итоговым memo.",
        "category": "research",
        "available_tools": ["legal_db", "rag", "summarize", "document_draft"],
        "default_plan": {
            "goals": [
                "Найти релевантные нормы и практику",
                "Собрать ключевые аргументы",
                "Подготовить итоговый memo"
            ],
            "steps": [
                {"id": "search_law", "name": "Поиск норм и практики", "tool": "legal_db", "depends_on": []},
                {"id": "collect_case_context", "name": "Сбор контекста из материалов дела", "tool": "rag", "depends_on": ["search_law"]},
                {"id": "research_summary", "name": "Сводный анализ", "tool": "summarize", "depends_on": ["collect_case_context"]},
                {"id": "research_memo", "name": "Подготовить итоговый memo", "tool": "document_draft", "depends_on": ["research_summary"]},
            ]
        }
    },
    {
        "name": "rf_bankruptcy_creditor_analysis",
        "display_name": "РФ Банкротство: Анализ требований кредитора",
        "description": "Анализ обоснованности требований кредитора в делах о банкротстве РФ и подготовка процессуальной позиции.",
        "category": "litigation",
        "available_tools": ["extract_entities", "legal_db", "summarize", "document_draft"],
        "default_plan": {
            "goals": [
                "Структурировать данные по требованию кредитора",
                "Проверить правовые основания по банкротству РФ",
                "Подготовить документ позиции"
            ],
            "steps": [
                {"id": "creditor_entities", "name": "Извлечь суммы, даты, основания", "tool": "extract_entities", "depends_on": []},
                {"id": "creditor_law", "name": "Подобрать нормы по банкротству РФ", "tool": "legal_db", "depends_on": ["creditor_entities"]},
                {"id": "creditor_summary", "name": "Сформировать правовой вывод", "tool": "summarize", "depends_on": ["creditor_law"]},
                {"id": "creditor_draft", "name": "Подготовить проект позиции", "tool": "document_draft", "depends_on": ["creditor_summary"]},
            ]
        }
    },
    {
        "name": "rf_bankruptcy_transaction_challenge",
        "display_name": "РФ Банкротство: Оспаривание сделок должника",
        "description": "Выявление подозрительных сделок и подготовка проекта документа об оспаривании в процедуре банкротства РФ.",
        "category": "litigation",
        "available_tools": ["rag", "tabular_review", "legal_db", "document_draft"],
        "default_plan": {
            "goals": [
                "Найти сделки с признаками оспаривания",
                "Собрать доказательную таблицу по сделкам",
                "Подготовить проект процессуального документа"
            ],
            "steps": [
                {"id": "tx_candidates", "name": "Выявить сделки-кандидаты", "tool": "rag", "depends_on": []},
                {"id": "tx_table", "name": "Собрать таблицу признаков оспаривания", "tool": "tabular_review", "depends_on": ["tx_candidates"]},
                {"id": "tx_law", "name": "Подобрать правовые основания", "tool": "legal_db", "depends_on": ["tx_table"]},
                {"id": "tx_draft", "name": "Подготовить проект заявления", "tool": "document_draft", "depends_on": ["tx_law"]},
            ]
        }
    },
]

