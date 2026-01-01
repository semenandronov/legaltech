"""
Тестовый скрипт для проверки отправки SSE событий table_created

Этот скрипт проверяет формат и структуру событий, отправляемых через plan_execution.py
"""

import json
from app.routes.plan_execution import stream_plan_execution
from app.utils.database import SessionLocal
from app.models.analysis import AnalysisPlan
from app.models.tabular_review import TabularReview
import asyncio


async def test_sse_table_events():
    """Тестирование SSE событий table_created"""
    db = SessionLocal()
    try:
        # Получаем завершенный план с таблицами
        plan = db.query(AnalysisPlan).filter(
            AnalysisPlan.status == "completed"
        ).order_by(AnalysisPlan.created_at.desc()).first()
        
        if not plan:
            print("⚠️ Нет завершенных планов для тестирования")
            return False
        
        print(f"Тестирование плана: {plan.id}")
        print(f"Case ID: {plan.case_id}")
        
        # Проверяем plan_data
        plan_data = plan.plan_data or {}
        table_results = plan_data.get("table_results") or plan_data.get("delivery_result", {}).get("tables", {})
        
        if not table_results:
            print("⚠️ В plan_data нет table_results")
            return False
        
        print(f"Найдено таблиц в plan_data: {len(table_results)}")
        
        # Симулируем SSE поток
        events_received = []
        async for event in stream_plan_execution(plan.id, db):
            if event.startswith("data: "):
                try:
                    data = json.loads(event[6:])
                    if data.get("type") == "table_created":
                        events_received.append(data)
                        print(f"\n✅ Получено событие table_created:")
                        print(f"  - table_id: {data.get('table_id')}")
                        print(f"  - case_id: {data.get('case_id')}")
                        print(f"  - analysis_type: {data.get('analysis_type')}")
                        print(f"  - table_data: {json.dumps(data.get('table_data', {}), indent=2, ensure_ascii=False)}")
                except json.JSONDecodeError:
                    pass
        
        # Проверяем формат событий
        if events_received:
            print(f"\n✅ Получено {len(events_received)} событий table_created")
            
            # Проверяем структуру каждого события
            for event in events_received:
                required_fields = ["type", "table_id", "case_id", "analysis_type", "table_data"]
                missing_fields = [field for field in required_fields if field not in event]
                
                if missing_fields:
                    print(f"❌ Отсутствуют поля: {missing_fields}")
                    return False
                
                # Проверяем table_data
                table_data = event.get("table_data", {})
                required_table_fields = ["id", "name", "columns_count", "rows_count", "preview"]
                missing_table_fields = [field for field in required_table_fields if field not in table_data]
                
                if missing_table_fields:
                    print(f"❌ В table_data отсутствуют поля: {missing_table_fields}")
                    return False
            
            print("✅ Все события имеют правильную структуру")
            return True
        else:
            print("⚠️ События table_created не были отправлены")
            return False
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании SSE событий: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def main():
    """Запуск теста"""
    print("=" * 60)
    print("Тестирование SSE событий table_created")
    print("=" * 60)
    
    result = asyncio.run(test_sse_table_events())
    
    if result:
        print("\n✅ Тест пройден успешно!")
        return 0
    else:
        print("\n❌ Тест не пройден")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

