"""Skill Registry for managing and discovering agent skills"""
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, asdict
from enum import Enum
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SkillStatus(str, Enum):
    """Статус навыка"""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"
    DISABLED = "disabled"


@dataclass
class SkillMetadata:
    """Метаданные навыка"""
    name: str
    description: str
    version: str
    author: str
    status: SkillStatus = SkillStatus.ACTIVE
    tags: List[str] = None
    dependencies: List[str] = None
    agent_type: Optional[str] = None
    tools: List[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.dependencies is None:
            self.dependencies = []
        if self.tools is None:
            self.tools = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь"""
        result = asdict(self)
        result["status"] = self.status.value
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillMetadata":
        """Создать из словаря"""
        if "status" in data and isinstance(data["status"], str):
            data["status"] = SkillStatus(data["status"])
        return cls(**data)


class SkillRegistry:
    """Реестр навыков для управления и поиска агентных навыков"""
    
    def __init__(self, registry_path: Optional[Path] = None):
        """
        Инициализировать реестр навыков
        
        Args:
            registry_path: Путь к файлу реестра (опционально)
        """
        self.registry_path = registry_path or Path("skills_registry.json")
        self.skills: Dict[str, SkillMetadata] = {}
        self._load_registry()
        logger.info(f"SkillRegistry initialized with {len(self.skills)} skills")
    
    def _load_registry(self):
        """Загрузить реестр из файла"""
        if self.registry_path.exists():
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.skills = {
                        name: SkillMetadata.from_dict(metadata)
                        for name, metadata in data.items()
                    }
                logger.info(f"Loaded {len(self.skills)} skills from registry")
            except Exception as e:
                logger.warning(f"Failed to load registry: {e}, starting with empty registry")
                self.skills = {}
        else:
            self.skills = {}
    
    def _save_registry(self):
        """Сохранить реестр в файл"""
        try:
            data = {
                name: metadata.to_dict()
                for name, metadata in self.skills.items()
            }
            with open(self.registry_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved registry with {len(self.skills)} skills")
        except Exception as e:
            logger.error(f"Failed to save registry: {e}", exc_info=True)
    
    def register(
        self,
        name: str,
        description: str,
        version: str = "1.0.0",
        author: str = "unknown",
        status: SkillStatus = SkillStatus.ACTIVE,
        tags: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
        agent_type: Optional[str] = None,
        tools: Optional[List[str]] = None
    ) -> SkillMetadata:
        """
        Зарегистрировать навык
        
        Args:
            name: Уникальное имя навыка
            description: Описание навыка
            version: Версия навыка
            author: Автор навыка
            status: Статус навыка
            tags: Теги для поиска
            dependencies: Зависимости от других навыков
            agent_type: Тип агента
            tools: Инструменты, используемые навыком
        
        Returns:
            Метаданные зарегистрированного навыка
        """
        if name in self.skills:
            logger.warning(f"Skill {name} already registered, updating metadata")
        
        metadata = SkillMetadata(
            name=name,
            description=description,
            version=version,
            author=author,
            status=status,
            tags=tags or [],
            dependencies=dependencies or [],
            agent_type=agent_type,
            tools=tools or []
        )
        
        self.skills[name] = metadata
        self._save_registry()
        logger.info(f"Registered skill: {name} (version {version})")
        
        return metadata
    
    def unregister(self, name: str) -> bool:
        """
        Удалить навык из реестра
        
        Args:
            name: Имя навыка
        
        Returns:
            True если навык был удален
        """
        if name in self.skills:
            del self.skills[name]
            self._save_registry()
            logger.info(f"Unregistered skill: {name}")
            return True
        return False
    
    def get(self, name: str) -> Optional[SkillMetadata]:
        """
        Получить метаданные навыка
        
        Args:
            name: Имя навыка
        
        Returns:
            Метаданные навыка или None
        """
        return self.skills.get(name)
    
    def search(
        self,
        query: Optional[str] = None,
        tags: Optional[List[str]] = None,
        agent_type: Optional[str] = None,
        status: Optional[SkillStatus] = None
    ) -> List[SkillMetadata]:
        """
        Поиск навыков по критериям
        
        Args:
            query: Текст для поиска в имени и описании
            tags: Фильтр по тегам
            agent_type: Фильтр по типу агента
            status: Фильтр по статусу
        
        Returns:
            Список найденных навыков
        """
        results = []
        
        for metadata in self.skills.values():
            # Фильтр по статусу
            if status and metadata.status != status:
                continue
            
            # Фильтр по типу агента
            if agent_type and metadata.agent_type != agent_type:
                continue
            
            # Фильтр по тегам
            if tags:
                if not any(tag in metadata.tags for tag in tags):
                    continue
            
            # Поиск по тексту
            if query:
                query_lower = query.lower()
                if (query_lower not in metadata.name.lower() and
                    query_lower not in metadata.description.lower()):
                    continue
            
            results.append(metadata)
        
        logger.debug(f"Search found {len(results)} skills")
        return results
    
    def get_all(self) -> List[SkillMetadata]:
        """Получить все навыки"""
        return list(self.skills.values())
    
    def get_by_agent_type(self, agent_type: str) -> List[SkillMetadata]:
        """Получить навыки для определенного типа агента"""
        return [
            metadata for metadata in self.skills.values()
            if metadata.agent_type == agent_type
        ]
    
    def get_dependencies(self, name: str) -> List[SkillMetadata]:
        """
        Получить зависимости навыка
        
        Args:
            name: Имя навыка
        
        Returns:
            Список метаданных зависимостей
        """
        metadata = self.get(name)
        if not metadata:
            return []
        
        dependencies = []
        for dep_name in metadata.dependencies:
            dep_metadata = self.get(dep_name)
            if dep_metadata:
                dependencies.append(dep_metadata)
            else:
                logger.warning(f"Dependency {dep_name} not found for skill {name}")
        
        return dependencies
    
    def validate(self, name: str) -> tuple[bool, List[str]]:
        """
        Валидировать навык (проверить зависимости и т.д.)
        
        Args:
            name: Имя навыка
        
        Returns:
            Кортеж (валиден, список ошибок)
        """
        metadata = self.get(name)
        if not metadata:
            return False, [f"Skill {name} not found"]
        
        errors = []
        
        # Проверяем зависимости
        for dep_name in metadata.dependencies:
            if dep_name not in self.skills:
                errors.append(f"Dependency {dep_name} not found")
            elif self.skills[dep_name].status == SkillStatus.DISABLED:
                errors.append(f"Dependency {dep_name} is disabled")
        
        # Проверяем обязательные поля
        if not metadata.description:
            errors.append("Description is required")
        
        return len(errors) == 0, errors


# Global registry instance
_global_registry: Optional[SkillRegistry] = None


def get_skill_registry(registry_path: Optional[Path] = None) -> SkillRegistry:
    """Получить глобальный экземпляр реестра навыков"""
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry(registry_path)
    return _global_registry

