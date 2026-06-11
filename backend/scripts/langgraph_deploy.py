#!/usr/bin/env python3
"""
Скрипт для деплоя LangGraph агентов.

Поддерживает:
- Локальный запуск через LangGraph CLI
- Сборку Docker образа
- Деплой на LangGraph Platform

# ИСПОЛЬЗОВАНИЕ

## Локальный запуск
```bash
python scripts/langgraph_deploy.py serve
```

## Сборка Docker образа
```bash
python scripts/langgraph_deploy.py build
```

## Деплой на LangGraph Platform
```bash
python scripts/langgraph_deploy.py deploy --api-key YOUR_API_KEY
```
"""
import argparse
import subprocess
import sys
import os
import json
from pathlib import Path


# Определяем корневую директорию
SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
LANGGRAPH_JSON = BACKEND_DIR / "langgraph.json"
DOCKERFILE = BACKEND_DIR / "Dockerfile.langgraph"


def check_langgraph_cli():
    """Проверить наличие LangGraph CLI."""
    try:
        result = subprocess.run(
            ["langgraph", "--version"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"✅ LangGraph CLI: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ LangGraph CLI не найден")
    print("Установите: pip install langgraph-cli")
    return False


def check_docker():
    """Проверить наличие Docker."""
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"✅ Docker: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ Docker не найден")
    return False


def validate_config():
    """Валидировать langgraph.json."""
    if not LANGGRAPH_JSON.exists():
        print(f"❌ Файл {LANGGRAPH_JSON} не найден")
        return False
    
    try:
        with open(LANGGRAPH_JSON) as f:
            config = json.load(f)
        
        # Проверяем обязательные поля
        required = ["graphs", "assistants"]
        for field in required:
            if field not in config:
                print(f"❌ Отсутствует обязательное поле: {field}")
                return False
        
        print(f"✅ Конфигурация валидна")
        print(f"   Графы: {list(config['graphs'].keys())}")
        print(f"   Assistants: {list(config['assistants'].keys())}")
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга JSON: {e}")
        return False


def cmd_serve(args):
    """Запустить локальный LangGraph сервер."""
    print("\n🚀 Запуск LangGraph сервера...")
    
    if not check_langgraph_cli():
        return 1
    
    if not validate_config():
        return 1
    
    # Переходим в директорию backend
    os.chdir(BACKEND_DIR)
    
    cmd = [
        "langgraph", "serve",
        "--host", args.host,
        "--port", str(args.port),
    ]
    
    if args.reload:
        cmd.append("--reload")
    
    print(f"Команда: {' '.join(cmd)}")
    print(f"Сервер будет доступен на http://{args.host}:{args.port}")
    print("Нажмите Ctrl+C для остановки\n")
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n\n🛑 Сервер остановлен")
    
    return 0


def cmd_build(args):
    """Собрать Docker образ."""
    print("\n🔨 Сборка Docker образа...")
    
    if not check_docker():
        return 1
    
    if not validate_config():
        return 1
    
    image_name = args.image or "legal-ai-langgraph"
    tag = args.tag or "latest"
    full_name = f"{image_name}:{tag}"
    
    # Переходим в директорию backend
    os.chdir(BACKEND_DIR)
    
    cmd = [
        "docker", "build",
        "-f", str(DOCKERFILE),
        "-t", full_name,
        "."
    ]
    
    if args.no_cache:
        cmd.insert(2, "--no-cache")
    
    print(f"Команда: {' '.join(cmd)}")
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print(f"\n✅ Образ собран: {full_name}")
        print(f"\nЗапуск:")
        print(f"  docker run -p 8123:8123 {full_name}")
    else:
        print(f"\n❌ Ошибка сборки")
    
    return result.returncode


def cmd_deploy(args):
    """Деплой на LangGraph Platform."""
    print("\n☁️ Деплой на LangGraph Platform...")
    
    if not check_langgraph_cli():
        return 1
    
    if not validate_config():
        return 1
    
    if not args.api_key:
        print("❌ Требуется API ключ (--api-key)")
        return 1
    
    # Переходим в директорию backend
    os.chdir(BACKEND_DIR)
    
    # Устанавливаем API ключ
    os.environ["LANGCHAIN_API_KEY"] = args.api_key
    
    cmd = ["langgraph", "deploy"]
    
    if args.project:
        cmd.extend(["--project", args.project])
    
    print(f"Команда: {' '.join(cmd)}")
    
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print(f"\n✅ Деплой завершён")
    else:
        print(f"\n❌ Ошибка деплоя")
    
    return result.returncode


def cmd_test(args):
    """Тестировать конфигурацию."""
    print("\n🧪 Тестирование конфигурации...")
    
    if not validate_config():
        return 1
    
    # Проверяем импорты графов
    print("\nПроверка импортов...")
    
    sys.path.insert(0, str(BACKEND_DIR))
    
    try:
        from app.services.langchain_agents.graphs.chat_graph import create_chat_graph
        print("  ✅ chat_graph")
    except Exception as e:
        print(f"  ❌ chat_graph: {e}")
    
    # Проверяем assistants
    print("\nПроверка assistants...")
    
    try:
        from app.services.langchain_agents.assistants import list_assistants
        assistants = list_assistants()
        for a in assistants:
            print(f"  ✅ {a['id']}: {a['name']}")
    except Exception as e:
        print(f"  ❌ Ошибка: {e}")
    
    print("\n✅ Тестирование завершено")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="LangGraph Deployment Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python scripts/langgraph_deploy.py serve
  python scripts/langgraph_deploy.py build --tag v1.0
  python scripts/langgraph_deploy.py deploy --api-key sk-xxx
  python scripts/langgraph_deploy.py test
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Команда")
    
    # serve
    serve_parser = subparsers.add_parser("serve", help="Запустить локальный сервер")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    serve_parser.add_argument("--port", type=int, default=8123, help="Port (default: 8123)")
    serve_parser.add_argument("--reload", action="store_true", help="Auto-reload при изменениях")
    serve_parser.set_defaults(func=cmd_serve)
    
    # build
    build_parser = subparsers.add_parser("build", help="Собрать Docker образ")
    build_parser.add_argument("--image", help="Имя образа (default: legal-ai-langgraph)")
    build_parser.add_argument("--tag", help="Тег (default: latest)")
    build_parser.add_argument("--no-cache", action="store_true", help="Без кэша")
    build_parser.set_defaults(func=cmd_build)
    
    # deploy
    deploy_parser = subparsers.add_parser("deploy", help="Деплой на LangGraph Platform")
    deploy_parser.add_argument("--api-key", required=True, help="LangChain API ключ")
    deploy_parser.add_argument("--project", help="Имя проекта")
    deploy_parser.set_defaults(func=cmd_deploy)
    
    # test
    test_parser = subparsers.add_parser("test", help="Тестировать конфигурацию")
    test_parser.set_defaults(func=cmd_test)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

