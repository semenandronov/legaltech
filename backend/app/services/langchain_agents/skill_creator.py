"""Skill Creator - генерация кода агентов из шаблонов"""
from typing import Dict, Any, Optional, List
from pathlib import Path
from app.services.langchain_agents.skill_template import SkillTemplate
from app.services.langchain_agents.skill_registry import SkillRegistry, get_skill_registry
import logging
import re

logger = logging.getLogger(__name__)


class SkillCodeGenerator:
    """Генератор кода для навыков из шаблонов"""
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        Инициализировать генератор кода
        
        Args:
            output_dir: Директория для генерации файлов
        """
        self.output_dir = output_dir or Path("backend/app/services/langchain_agents")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_node_file(self, template: SkillTemplate) -> str:
        """
        Сгенерировать файл узла агента из шаблона
        
        Args:
            template: Шаблон навыка
        
        Returns:
            Путь к созданному файлу
        """
        node_name = template.name
        
        # Генерируем содержимое файла
        content = f'''"""Agent node for {template.description}"""
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
import logging

logger = logging.getLogger(__name__)


def {node_name}_agent_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    {template.description}
    
    Args:
        state: Current graph state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with {node_name}_result
    """
    case_id = state.get("case_id", "unknown")
    logger.info(f"[{node_name.title()}] Starting {template.description.lower()} for case {{case_id}}")
    
    new_state = dict(state)
    
    try:
        # TODO: Implement agent logic here
        # Use template.prompt_template or template.system_prompt for agent prompt
        # Use template.tools for available tools
        
        # Example structure:
        # 1. Get context from state
        # 2. Create agent with tools
        # 3. Execute agent
        # 4. Parse results
        # 5. Update state
        
        result = {{
            "status": "completed",
            "result": "Not implemented yet"
        }}
        
        new_state["{node_name}_result"] = result
        logger.info(f"[{node_name.title()}] Completed for case {{case_id}}")
        
    except Exception as e:
        logger.error(f"[{node_name.title()}] Error: {{e}}", exc_info=True)
        new_state["{node_name}_result"] = {{
            "status": "error",
            "error": str(e)
        }}
        if "errors" not in new_state:
            new_state["errors"] = []
        new_state["errors"].append({{
            "agent": "{node_name}",
            "error": str(e)
        }})
    
    return new_state
'''
        
        # Сохраняем файл
        file_path = self.output_dir / f"{node_name}_node.py"
        file_path.write_text(content, encoding="utf-8")
        logger.info(f"Generated node file: {file_path}")
        
        return str(file_path)
    
    def generate_prompt_file(self, template: SkillTemplate) -> str:
        """
        Сгенерировать файл с промптом (если нужен отдельный файл)
        
        Args:
            template: Шаблон навыка
        
        Returns:
            Путь к созданному файлу (или пустая строка если не нужен)
        """
        # Промпты обычно хранятся в prompts.py, но можно создать отдельный файл
        # Для простоты пропускаем отдельный файл промпта
        return ""
    
    def update_prompts_file(self, template: SkillTemplate, prompts_file: Path) -> bool:
        """
        Обновить файл prompts.py, добавив промпт для навыка
        
        Args:
            template: Шаблон навыка
            prompts_file: Путь к файлу prompts.py
        
        Returns:
            True если успешно обновлен
        """
        if not prompts_file.exists():
            logger.warning(f"Prompts file not found: {prompts_file}")
            return False
        
        # Читаем текущий файл
        content = prompts_file.read_text(encoding="utf-8")
        
        # Проверяем, есть ли уже промпт для этого навыка
        prompt_name = f"{template.name.upper()}_PROMPT"
        if prompt_name in content:
            logger.info(f"Prompt {prompt_name} already exists in prompts file")
            return True
        
        # Добавляем новый промпт в конец файла
        prompt_text = template.system_prompt or template.prompt_template
        new_prompt = f'''\n\n# {template.description}
{prompt_name} = """{prompt_text}"""
'''
        
        content += new_prompt
        prompts_file.write_text(content, encoding="utf-8")
        logger.info(f"Added prompt {prompt_name} to prompts file")
        
        return True
    
    def generate_all(self, template: SkillTemplate) -> Dict[str, str]:
        """
        Сгенерировать все файлы для навыка
        
        Args:
            template: Шаблон навыка
        
        Returns:
            Словарь с путями к созданным файлам
        """
        generated_files = {}
        
        # Генерируем файл узла
        node_file = self.generate_node_file(template)
        generated_files["node_file"] = node_file
        
        # Обновляем prompts.py
        prompts_file = self.output_dir.parent / "prompts.py"
        if prompts_file.exists():
            self.update_prompts_file(template, prompts_file)
        
        return generated_files


class SkillCreator:
    """Создатель навыков - высокоуровневый интерфейс для создания навыков"""
    
    def __init__(
        self,
        registry: Optional[SkillRegistry] = None,
        code_generator: Optional[SkillCodeGenerator] = None
    ):
        """
        Инициализировать создатель навыков
        
        Args:
            registry: Реестр навыков
            code_generator: Генератор кода
        """
        self.registry = registry or get_skill_registry()
        self.code_generator = code_generator or SkillCodeGenerator()
        logger.info("SkillCreator initialized")
    
    def create_skill(
        self,
        template: SkillTemplate,
        generate_code: bool = True,
        register: bool = True
    ) -> Dict[str, Any]:
        """
        Создать навык из шаблона
        
        Args:
            template: Шаблон навыка
            generate_code: Генерировать код файлов
            register: Зарегистрировать в реестре
        
        Returns:
            Словарь с результатами создания
        """
        # Валидируем шаблон
        is_valid, errors = template.validate()
        if not is_valid:
            raise ValueError(f"Invalid template: {', '.join(errors)}")
        
        result = {
            "template": template.to_dict(),
            "generated_files": {},
            "registered": False
        }
        
        # Генерируем код
        if generate_code:
            try:
                generated_files = self.code_generator.generate_all(template)
                result["generated_files"] = generated_files
                logger.info(f"Generated code files for skill {template.name}")
            except Exception as e:
                logger.error(f"Failed to generate code for skill {template.name}: {e}", exc_info=True)
                result["generation_error"] = str(e)
        
        # Регистрируем в реестре
        if register:
            try:
                metadata = template.to_metadata()
                self.registry.register(
                    name=metadata.name,
                    description=metadata.description,
                    version=metadata.version,
                    author=metadata.author,
                    status=metadata.status,
                    tags=metadata.tags,
                    dependencies=metadata.dependencies,
                    agent_type=metadata.agent_type,
                    tools=metadata.tools
                )
                result["registered"] = True
                logger.info(f"Registered skill {template.name} in registry")
            except Exception as e:
                logger.error(f"Failed to register skill {template.name}: {e}", exc_info=True)
                result["registration_error"] = str(e)
        
        return result
    
    def create_from_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создать навык из словаря
        
        Args:
            data: Словарь с данными навыка
        
        Returns:
            Результат создания
        """
        template = SkillTemplate.from_dict(data)
        return self.create_skill(template)

