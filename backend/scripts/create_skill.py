#!/usr/bin/env python3
"""CLI утилита для создания новых навыков агентов"""
import sys
import json
from pathlib import Path
from typing import Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.langchain_agents.skill_template import (
    SkillTemplate,
    SkillTemplateBuilder,
    SkillStatus
)
from app.services.langchain_agents.skill_creator import SkillCreator
from app.services.langchain_agents.skill_registry import get_skill_registry
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def prompt_input(prompt: str, default: Optional[str] = None) -> str:
    """Интерактивный ввод с подсказкой"""
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    else:
        return input(f"{prompt}: ").strip()


def prompt_list(prompt: str) -> list:
    """Интерактивный ввод списка"""
    print(f"{prompt} (по одному элементу в строке, пустая строка для завершения):")
    items = []
    while True:
        item = input("  ").strip()
        if not item:
            break
        items.append(item)
    return items


def create_skill_interactive() -> SkillTemplate:
    """Интерактивное создание навыка"""
    print("=== Создание нового навыка агента ===\n")
    
    builder = SkillTemplateBuilder()
    
    # Базовая информация
    name = prompt_input("Имя навыка (например: compliance_check)")
    builder.with_name(name)
    
    description = prompt_input("Описание навыка")
    builder.with_description(description)
    
    version = prompt_input("Версия", "1.0.0")
    builder.with_version(version)
    
    author = prompt_input("Автор", "unknown")
    builder.with_author(author)
    
    # Статус
    print("\nСтатус навыка:")
    print("  1. active (активный)")
    print("  2. experimental (экспериментальный)")
    print("  3. deprecated (устаревший)")
    status_choice = prompt_input("Выберите статус", "1")
    status_map = {
        "1": SkillStatus.ACTIVE,
        "2": SkillStatus.EXPERIMENTAL,
        "3": SkillStatus.DEPRECATED
    }
    builder.with_status(status_map.get(status_choice, SkillStatus.ACTIVE))
    
    # Тип агента
    agent_type = prompt_input("\nТип агента (например: analysis, extraction, classification)", "")
    if agent_type:
        builder.with_agent_type(agent_type)
    
    # Теги
    tags = prompt_list("\nТеги для поиска")
    if tags:
        builder.with_tags(*tags)
    
    # Зависимости
    dependencies = prompt_list("\nЗависимости от других навыков")
    if dependencies:
        builder.with_dependencies(*dependencies)
    
    # Инструменты
    tools = prompt_list("\nИнструменты (например: retrieve_documents, web_search)")
    if tools:
        builder.with_tools(*tools)
    
    # Системный промпт
    print("\nСистемный промпт для агента:")
    system_prompt = input("(можно оставить пустым и добавить позже): ").strip()
    if system_prompt:
        builder.with_system_prompt(system_prompt)
    
    # Метаданные (опционально)
    add_metadata = prompt_input("\nДобавить дополнительные метаданные? (y/n)", "n")
    if add_metadata.lower() == "y":
        while True:
            key = input("Ключ метаданных (пустая строка для завершения): ").strip()
            if not key:
                break
            value = input(f"Значение для '{key}': ").strip()
            builder.with_metadata(key, value)
    
    # Строим шаблон
    try:
        template = builder.build()
        print(f"\n✅ Шаблон навыка '{name}' успешно создан!")
        return template
    except ValueError as e:
        print(f"\n❌ Ошибка создания шаблона: {e}")
        sys.exit(1)


def main():
    """Главная функция CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Создать новый навык агента",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Интерактивное создание
  python create_skill.py
  
  # Создание из JSON файла
  python create_skill.py --template skill_template.json
  
  # Создание с указанием выходной директории
  python create_skill.py --output-dir ./custom_skills
        """
    )
    
    parser.add_argument(
        "--template",
        type=Path,
        help="Путь к JSON файлу с шаблоном навыка"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Директория для генерации файлов (по умолчанию: backend/app/services/langchain_agents)"
    )
    parser.add_argument(
        "--no-code",
        action="store_true",
        help="Не генерировать код, только зарегистрировать"
    )
    parser.add_argument(
        "--no-register",
        action="store_true",
        help="Не регистрировать в реестре, только сгенерировать код"
    )
    parser.add_argument(
        "--registry-path",
        type=Path,
        help="Путь к файлу реестра навыков"
    )
    
    args = parser.parse_args()
    
    # Определяем шаблон
    if args.template:
        # Загружаем из файла
        try:
            with open(args.template, "r", encoding="utf-8") as f:
                template_data = json.load(f)
            template = SkillTemplate.from_dict(template_data)
            print(f"✅ Загружен шаблон из {args.template}")
        except Exception as e:
            print(f"❌ Ошибка загрузки шаблона: {e}")
            sys.exit(1)
    else:
        # Интерактивное создание
        template = create_skill_interactive()
    
    # Создаем навык
    try:
        registry = get_skill_registry(args.registry_path) if args.registry_path else None
        creator = SkillCreator(registry=registry)
        
        result = creator.create_skill(
            template,
            generate_code=not args.no_code,
            register=not args.no_register
        )
        
        print("\n=== Результаты создания ===")
        print(f"Навык: {template.name}")
        print(f"Версия: {template.version}")
        
        if result.get("generated_files"):
            print("\nСозданные файлы:")
            for file_type, file_path in result["generated_files"].items():
                print(f"  {file_type}: {file_path}")
        
        if result.get("registered"):
            print("\n✅ Навык зарегистрирован в реестре")
        
        if result.get("generation_error"):
            print(f"\n⚠️  Ошибка генерации кода: {result['generation_error']}")
        
        if result.get("registration_error"):
            print(f"\n⚠️  Ошибка регистрации: {result['registration_error']}")
        
        print("\n✅ Готово!")
        
    except Exception as e:
        print(f"\n❌ Ошибка создания навыка: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()

