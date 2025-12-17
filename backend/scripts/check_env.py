#!/usr/bin/env python3
"""Скрипт для проверки переменных окружения"""
import os
import sys
from typing import Dict, Tuple


REQUIRED_ENV_VARS = {
    "DATABASE_URL": {
        "required": True,
        "description": "PostgreSQL connection string для checkpointer",
        "example": "postgresql://user:password@localhost:5432/dbname"
    },
    "OPENROUTER_API_KEY": {
        "required": True,
        "description": "API ключ для OpenRouter (LLM)",
        "example": "sk-or-v1-..."
    },
}

OPTIONAL_ENV_VARS = {
    "AGENT_ENABLED": {
        "required": False,
        "description": "Включение/выключение агентов",
        "default": "true",
        "example": "true"
    },
    "AGENT_MAX_PARALLEL": {
        "required": False,
        "description": "Максимальное количество параллельных агентов",
        "default": "3",
        "example": "3"
    },
    "AGENT_TIMEOUT": {
        "required": False,
        "description": "Таймаут для агента (секунды)",
        "default": "300",
        "example": "300"
    },
    "AGENT_RETRY_COUNT": {
        "required": False,
        "description": "Количество повторов при ошибке",
        "default": "2",
        "example": "2"
    },
    "LANGSMITH_API_KEY": {
        "required": False,
        "description": "API ключ для LangSmith (мониторинг)",
        "example": "lsv2_..."
    },
    "LANGSMITH_PROJECT": {
        "required": False,
        "description": "Название проекта в LangSmith",
        "default": "legal-ai-vault",
        "example": "legal-ai-vault"
    },
    "LANGCHAIN_TRACING_V2": {
        "required": False,
        "description": "Включение трейсинга LangSmith",
        "default": "false",
        "example": "true"
    },
    "LANGCHAIN_ENDPOINT": {
        "required": False,
        "description": "Endpoint для LangSmith",
        "default": "https://api.smith.langchain.com",
        "example": "https://api.smith.langchain.com"
    },
}


def check_env_var(name: str, config: Dict) -> Tuple[bool, str]:
    """
    Проверить переменную окружения
    
    Args:
        name: Имя переменной
        config: Конфигурация переменной
    
    Returns:
        Tuple[bool, str]: (корректна, значение или сообщение)
    """
    value = os.getenv(name)
    
    if value is None or value.strip() == "":
        if config.get("required", False):
            return False, "❌ ОТСУТСТВУЕТ (обязательная)"
        else:
            default = config.get("default", "не установлено")
            return True, f"⚠️  не установлено (по умолчанию: {default})"
    
    # Дополнительные проверки
    if name == "DATABASE_URL":
        if not value.startswith(("postgresql://", "postgres://")):
            return False, f"❌ Некорректный формат: {value[:50]}..."
        return True, "✅ установлено"
    
    if name == "OPENROUTER_API_KEY":
        if not value.startswith("sk-or-v1-"):
            return False, "❌ Некорректный формат (должен начинаться с sk-or-v1-)"
        return True, "✅ установлено"
    
    if name == "AGENT_ENABLED":
        if value.lower() not in ("true", "false"):
            return False, f"❌ Некорректное значение: {value} (должно быть true/false)"
        return True, f"✅ установлено ({value})"
    
    if name in ("AGENT_MAX_PARALLEL", "AGENT_TIMEOUT", "AGENT_RETRY_COUNT"):
        try:
            int(value)
            return True, f"✅ установлено ({value})"
        except ValueError:
            return False, f"❌ Некорректное значение: {value} (должно быть числом)"
    
    if name == "LANGCHAIN_TRACING_V2":
        if value.lower() not in ("true", "false"):
            return False, f"❌ Некорректное значение: {value} (должно быть true/false)"
        return True, f"✅ установлено ({value})"
    
    return True, "✅ установлено"


def main():
    """Основная функция проверки"""
    print("🔍 Проверка переменных окружения...")
    print("=" * 80)
    
    all_required_ok = True
    
    # Проверка обязательных переменных
    print("\n📋 Обязательные переменные:")
    print("-" * 80)
    for var_name, config in REQUIRED_ENV_VARS.items():
        ok, message = check_env_var(var_name, config)
        print(f"{var_name:30} {message}")
        if not ok:
            all_required_ok = False
            print(f"   Описание: {config['description']}")
            print(f"   Пример: {config['example']}")
    
    # Проверка опциональных переменных
    print("\n📋 Опциональные переменные:")
    print("-" * 80)
    for var_name, config in OPTIONAL_ENV_VARS.items():
        ok, message = check_env_var(var_name, config)
        print(f"{var_name:30} {message}")
        if not ok:
            print(f"   Описание: {config['description']}")
            print(f"   Пример: {config.get('example', 'N/A')}")
    
    print("=" * 80)
    
    if all_required_ok:
        print("✅ Все обязательные переменные окружения установлены корректно")
        return 0
    else:
        print("❌ Некоторые обязательные переменные окружения отсутствуют или некорректны")
        print("\nУстановите переменные в .env файле или через переменные окружения")
        return 1


if __name__ == "__main__":
    sys.exit(main())
