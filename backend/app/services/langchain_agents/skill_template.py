"""Skill Template for standardizing agent skills"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from app.services.langchain_agents.skill_registry import SkillMetadata, SkillStatus
import logging

logger = logging.getLogger(__name__)


@dataclass
class SkillTemplate:
    """Шаблон для создания навыка агента"""
    
    name: str
    description: str
    version: str = "1.0.0"
    author: str = "unknown"
    status: SkillStatus = SkillStatus.ACTIVE
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    agent_type: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    
    # Prompt template
    prompt_template: str = ""
    system_prompt: str = ""
    
    # Code generation
    node_function_template: str = ""
    agent_factory_config: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_metadata(self) -> SkillMetadata:
        """Преобразовать в SkillMetadata для реестра"""
        return SkillMetadata(
            name=self.name,
            description=self.description,
            version=self.version,
            author=self.author,
            status=self.status,
            tags=self.tags.copy(),
            dependencies=self.dependencies.copy(),
            agent_type=self.agent_type,
            tools=self.tools.copy()
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь для сериализации"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "status": self.status.value,
            "tags": self.tags,
            "dependencies": self.dependencies,
            "agent_type": self.agent_type,
            "tools": self.tools,
            "prompt_template": self.prompt_template,
            "system_prompt": self.system_prompt,
            "node_function_template": self.node_function_template,
            "agent_factory_config": self.agent_factory_config,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillTemplate":
        """Создать из словаря"""
        if "status" in data and isinstance(data["status"], str):
            data["status"] = SkillStatus(data["status"])
        return cls(**data)
    
    def validate(self) -> tuple[bool, List[str]]:
        """
        Валидировать шаблон
        
        Returns:
            Кортеж (валиден, список ошибок)
        """
        errors = []
        
        if not self.name:
            errors.append("Name is required")
        
        if not self.description:
            errors.append("Description is required")
        
        if not self.prompt_template and not self.system_prompt:
            errors.append("Either prompt_template or system_prompt is required")
        
        if self.agent_type and not self.node_function_template:
            errors.append("node_function_template is required when agent_type is set")
        
        return len(errors) == 0, errors


class SkillTemplateBuilder:
    """Builder для создания SkillTemplate"""
    
    def __init__(self):
        self.template = SkillTemplate(
            name="",
            description=""
        )
    
    def with_name(self, name: str) -> "SkillTemplateBuilder":
        """Установить имя"""
        self.template.name = name
        return self
    
    def with_description(self, description: str) -> "SkillTemplateBuilder":
        """Установить описание"""
        self.template.description = description
        return self
    
    def with_version(self, version: str) -> "SkillTemplateBuilder":
        """Установить версию"""
        self.template.version = version
        return self
    
    def with_author(self, author: str) -> "SkillTemplateBuilder":
        """Установить автора"""
        self.template.author = author
        return self
    
    def with_status(self, status: SkillStatus) -> "SkillTemplateBuilder":
        """Установить статус"""
        self.template.status = status
        return self
    
    def with_tags(self, *tags: str) -> "SkillTemplateBuilder":
        """Добавить теги"""
        self.template.tags.extend(tags)
        return self
    
    def with_dependencies(self, *dependencies: str) -> "SkillTemplateBuilder":
        """Добавить зависимости"""
        self.template.dependencies.extend(dependencies)
        return self
    
    def with_agent_type(self, agent_type: str) -> "SkillTemplateBuilder":
        """Установить тип агента"""
        self.template.agent_type = agent_type
        return self
    
    def with_tools(self, *tools: str) -> "SkillTemplateBuilder":
        """Добавить инструменты"""
        self.template.tools.extend(tools)
        return self
    
    def with_prompt_template(self, prompt: str) -> "SkillTemplateBuilder":
        """Установить шаблон промпта"""
        self.template.prompt_template = prompt
        return self
    
    def with_system_prompt(self, prompt: str) -> "SkillTemplateBuilder":
        """Установить системный промпт"""
        self.template.system_prompt = prompt
        return self
    
    def with_node_function_template(self, template: str) -> "SkillTemplateBuilder":
        """Установить шаблон функции узла"""
        self.template.node_function_template = template
        return self
    
    def with_agent_factory_config(self, config: Dict[str, Any]) -> "SkillTemplateBuilder":
        """Установить конфигурацию фабрики агентов"""
        self.template.agent_factory_config = config
        return self
    
    def with_metadata(self, key: str, value: Any) -> "SkillTemplateBuilder":
        """Добавить метаданные"""
        self.template.metadata[key] = value
        return self
    
    def build(self) -> SkillTemplate:
        """Построить шаблон"""
        is_valid, errors = self.template.validate()
        if not is_valid:
            raise ValueError(f"Invalid template: {', '.join(errors)}")
        return self.template


def create_standard_template(
    name: str,
    description: str,
    agent_type: str,
    prompt: str,
    tools: Optional[List[str]] = None
) -> SkillTemplate:
    """
    Создать стандартный шаблон навыка
    
    Args:
        name: Имя навыка
        description: Описание навыка
        agent_type: Тип агента
        prompt: Системный промпт
        tools: Список инструментов
    
    Returns:
        SkillTemplate
    """
    builder = SkillTemplateBuilder()
    builder.with_name(name)
    builder.with_description(description)
    builder.with_agent_type(agent_type)
    builder.with_system_prompt(prompt)
    
    if tools:
        builder.with_tools(*tools)
    
    # Стандартный шаблон функции узла
    node_template = f'''def {name}_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    {description}
    """
    # Implementation here
    pass'''
    
    builder.with_node_function_template(node_template)
    
    return builder.build()

