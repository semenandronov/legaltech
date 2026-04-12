#!/usr/bin/env python3
"""Скрипт для проверки установленных зависимостей"""
import sys
import importlib
from typing import Dict, Tuple


REQUIRED_PACKAGES = {
    "langgraph": ">=0.2.0",
    "langgraph-checkpoint-postgres": ">=0.1.0",
    "langchain": ">=0.1.0",
    "langchain-openai": ">=0.0.5",
    "langchain-community": ">=0.0.20",
    "langchain-core": ">=0.1.0",
    "fastapi": ">=0.115.0",
    "uvicorn": ">=0.32.0",
    "sqlalchemy": ">=2.0.36",
    "pydantic": ">=2.9.2",
    "psycopg2-binary": ">=2.9.11",
    "openai": ">=1.0.0",
}


def check_package(package_name: str, min_version: str = None) -> Tuple[bool, str]:
    """
    Проверить наличие и версию пакета
    
    Args:
        package_name: Имя пакета для импорта (может отличаться от имени в pip)
        min_version: Минимальная версия (опционально)
    
    Returns:
        Tuple[bool, str]: (установлен, версия или сообщение об ошибке)
    """
    # Маппинг имен пакетов pip -> import
    import_map = {
        "langgraph-checkpoint-postgres": "langgraph.checkpoint.postgres",
        "langchain-openai": "langchain_openai",
        "langchain-community": "langchain_community",
        "langchain-core": "langchain_core",
        "psycopg2-binary": "psycopg2",
    }
    
    import_name = import_map.get(package_name, package_name.replace("-", "_"))
    
    try:
        module = importlib.import_module(import_name)
        version = getattr(module, "__version__", "unknown")
        return True, version
    except ImportError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Error checking package: {e}"


def main():
    """Основная функция проверки"""
    print("🔍 Проверка зависимостей...")
    print("=" * 60)
    
    all_ok = True
    results: Dict[str, Tuple[bool, str]] = {}
    
    for package, min_version in REQUIRED_PACKAGES.items():
        installed, info = check_package(package, min_version)
        results[package] = (installed, info)
        
        if installed:
            print(f"✅ {package:30} {info}")
        else:
            print(f"❌ {package:30} {info}")
            all_ok = False
    
    print("=" * 60)
    
    if all_ok:
        print("✅ Все зависимости установлены корректно")
        return 0
    else:
        print("❌ Некоторые зависимости отсутствуют или имеют проблемы")
        print("\nУстановите недостающие пакеты:")
        print("pip install -r backend/requirements-core.txt")
        print("(полный стек с Docling: pip install -r backend/requirements.txt)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
