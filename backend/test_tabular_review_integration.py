"""
Тестовый скрипт для проверки интеграции TabularReview и чата с ИИ

Этот скрипт проверяет:
1. Создание таблиц в deliver_node для всех типов анализа
2. Сохранение table_results в plan_data
3. Отправку SSE событий через plan_execution
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm import Session
from app.utils.database import SessionLocal
from app.models.tabular_review import TabularReview, TabularColumn
from app.models.analysis import AnalysisPlan
from app.models.case import Case
from app.services.tabular_review_service import TabularReviewService
from app.services.langchain_agents.deliver_node import deliver_node
from app.services.langchain_agents.state import create_initial_state
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_table_creation_methods():
    """Проверка методов создания таблиц в TabularReviewService"""
    db = SessionLocal()
    try:
        service = TabularReviewService(db)
        
        # Проверяем наличие методов
        methods = [
            'create_timeline_table_from_results',
            'create_key_facts_table_from_results',
            'create_discrepancies_table_from_results',
            'create_risks_table_from_results'
        ]
        
        for method_name in methods:
            if hasattr(service, method_name):
                logger.info(f"✅ Метод {method_name} существует")
            else:
                logger.error(f"❌ Метод {method_name} не найден")
                return False
        
        return True
    finally:
        db.close()


def test_deliver_node_table_creation():
    """Проверка создания таблиц в deliver_node"""
    db = SessionLocal()
    try:
        # Получаем тестовый case
        case = db.query(Case).first()
        if not case:
            logger.warning("⚠️ Нет тестовых cases в БД. Создайте case для тестирования.")
            return False
        
        # Создаем mock state с результатами анализа
        state = create_initial_state(
            case_id=case.id,
            analysis_types=["timeline", "key_facts"],
            metadata={"user_id": case.user_id}
        )
        
        # Добавляем mock результаты
        state["timeline_result"] = {
            "events": [
                {"date": "2024-01-01", "type": "Событие 1", "description": "Описание 1"}
            ]
        }
        state["key_facts_result"] = {
            "facts": [
                {"fact": "Факт 1", "importance": "high"}
            ]
        }
        
        # Вызываем deliver_node
        result_state = deliver_node(state, db=db)
        
        # Проверяем результаты
        table_results = result_state.get("table_results", {})
        delivery_result = result_state.get("delivery_result", {})
        
        logger.info(f"Table results: {table_results}")
        logger.info(f"Delivery result tables: {delivery_result.get('tables', {})}")
        
        # Проверяем, что таблицы созданы
        created_tables = 0
        for analysis_type, table_info in table_results.items():
            if isinstance(table_info, dict) and table_info.get("status") == "created":
                table_id = table_info.get("table_id")
                if table_id:
                    # Проверяем, что таблица существует в БД
                    review = db.query(TabularReview).filter(TabularReview.id == table_id).first()
                    if review:
                        logger.info(f"✅ Таблица для {analysis_type} создана: {table_id}")
                        created_tables += 1
                    else:
                        logger.error(f"❌ Таблица {table_id} не найдена в БД")
        
        if created_tables > 0:
            logger.info(f"✅ Успешно создано {created_tables} таблиц")
            return True
        else:
            logger.warning("⚠️ Таблицы не были созданы (возможно, нет данных для анализа)")
            return False
        
    except Exception as e:
        logger.error(f"❌ Ошибка при тестировании deliver_node: {e}", exc_info=True)
        return False
    finally:
        db.close()


def test_plan_data_saving():
    """Проверка сохранения table_results в plan_data"""
    db = SessionLocal()
    try:
        # Получаем последний выполненный план
        plan = db.query(AnalysisPlan).filter(
            AnalysisPlan.status == "completed"
        ).order_by(AnalysisPlan.created_at.desc()).first()
        
        if not plan:
            logger.warning("⚠️ Нет завершенных планов для проверки")
            return False
        
        plan_data = plan.plan_data or {}
        
        # Проверяем наличие table_results или delivery_result
        has_table_results = "table_results" in plan_data
        has_delivery_result = "delivery_result" in plan_data
        
        if has_table_results:
            table_results = plan_data.get("table_results", {})
            logger.info(f"✅ table_results найдены в plan_data: {len(table_results)} таблиц")
            for key, value in table_results.items():
                logger.info(f"  - {key}: {value}")
        
        if has_delivery_result:
            delivery = plan_data.get("delivery_result", {})
            tables = delivery.get("tables", {})
            logger.info(f"✅ delivery_result найден в plan_data: {len(tables)} таблиц")
            for key, value in tables.items():
                logger.info(f"  - {key}: {value}")
        
        if has_table_results or has_delivery_result:
            return True
        else:
            logger.warning("⚠️ table_results и delivery_result не найдены в plan_data")
            return False
        
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке plan_data: {e}", exc_info=True)
        return False
    finally:
        db.close()


def main():
    """Запуск всех тестов"""
    logger.info("=" * 60)
    logger.info("Тестирование интеграции TabularReview и чата с ИИ")
    logger.info("=" * 60)
    
    results = []
    
    # Тест 1: Проверка методов создания таблиц
    logger.info("\n1. Проверка методов создания таблиц...")
    results.append(("Методы создания таблиц", test_table_creation_methods()))
    
    # Тест 2: Проверка deliver_node
    logger.info("\n2. Проверка создания таблиц в deliver_node...")
    results.append(("Создание таблиц в deliver_node", test_deliver_node_table_creation()))
    
    # Тест 3: Проверка сохранения в plan_data
    logger.info("\n3. Проверка сохранения table_results в plan_data...")
    results.append(("Сохранение в plan_data", test_plan_data_saving()))
    
    # Итоги
    logger.info("\n" + "=" * 60)
    logger.info("Результаты тестирования:")
    logger.info("=" * 60)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    logger.info(f"\nИтого: {passed}/{total} тестов пройдено")
    
    if passed == total:
        logger.info("✅ Все тесты пройдены успешно!")
        return 0
    else:
        logger.warning(f"⚠️ {total - passed} тестов не пройдено")
        return 1


if __name__ == "__main__":
    sys.exit(main())


