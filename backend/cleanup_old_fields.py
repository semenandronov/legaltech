#!/usr/bin/env python3
"""Удаление старых полей из timeline_events после миграции"""
import psycopg2
from psycopg2 import sql
import sys

DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def cleanup_old_fields():
    """Удаление старых полей"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cursor = conn.cursor()
        
        print("🧹 Очистка старых полей из timeline_events...\n")
        
        # Проверяем наличие старых полей
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'timeline_events'
            AND column_name IN ('eventType', 'metadata', 'timelineId', 'order', 'intervalDays');
        """)
        old_fields = [row[0] for row in cursor.fetchall()]
        
        if not old_fields:
            print("   ℹ️  Старые поля не найдены")
        else:
            print(f"   📋 Найдено старых полей: {', '.join(old_fields)}")
            
            # Проверяем, есть ли данные в новых полях
            cursor.execute("SELECT COUNT(*) FROM timeline_events WHERE event_type IS NOT NULL OR event_metadata IS NOT NULL")
            has_new_data = cursor.fetchone()[0] > 0
            
            if has_new_data or len(old_fields) > 0:
                print("   ⚠️  ВНИМАНИЕ: Удаление полей может привести к потере данных!")
                print("   ℹ️  Рекомендуется оставить старые поля для обратной совместимости")
                print("   ℹ️  Пропускаем удаление старых полей")
            else:
                for field in old_fields:
                    try:
                        cursor.execute(sql.SQL("ALTER TABLE timeline_events DROP COLUMN IF EXISTS {}").format(
                            sql.Identifier(field)
                        ))
                        print(f"   ✅ Удалено поле: {field}")
                    except Exception as e:
                        print(f"   ⚠️  Ошибка при удалении {field}: {e}")
        
        conn.commit()
        print("\n✅ Очистка завершена!")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
        return False

if __name__ == "__main__":
    cleanup_old_fields()
