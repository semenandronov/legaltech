#!/usr/bin/env python3
"""Миграция структуры БД для приведения в соответствие с моделями SQLAlchemy"""
import psycopg2
from psycopg2 import sql
import sys

DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def migrate_database():
    """Выполнение миграции БД"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cursor = conn.cursor()
        
        print("🔄 Начало миграции БД...\n")
        
        # 1. Добавление недостающих полей в таблицу cases
        print("1️⃣  Обновление таблицы cases...")
        cases_migrations = [
            ("description", "TEXT"),
            ("case_type", "VARCHAR(50)"),
            ("status", "VARCHAR(50) DEFAULT 'pending'"),
            ("analysis_config", "JSON"),
            ("case_metadata", "JSON")
        ]
        
        for field_name, field_def in cases_migrations:
            try:
                cursor.execute(sql.SQL("ALTER TABLE cases ADD COLUMN IF NOT EXISTS {} {}").format(
                    sql.Identifier(field_name),
                    sql.SQL(field_def)
                ))
                print(f"   ✅ Добавлено поле: {field_name}")
            except Exception as e:
                print(f"   ⚠️  Ошибка при добавлении {field_name}: {e}")
        
        # 2. Обновление таблицы timeline_events
        # Проверяем, какая структура используется
        print("\n2️⃣  Проверка таблицы timeline_events...")
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'timeline_events'
            ORDER BY column_name;
        """)
        existing_columns = [row[0] for row in cursor.fetchall()]
        
        # Если используется старая схема (с timelineId), пропускаем миграцию
        # Если используется новая схема (с case_id), добавляем недостающие поля
        if 'timelineId' in existing_columns:
            print("   ℹ️  Таблица использует старую схему (timelineId). Пропускаем миграцию.")
        elif 'case_id' in existing_columns:
            print("   ℹ️  Таблица использует новую схему (case_id). Проверяем поля...")
            timeline_migrations = [
                ("event_type", "VARCHAR(100)"),
                ("source_document", "VARCHAR(255)"),
                ("source_page", "INTEGER"),
                ("source_line", "INTEGER"),
                ("event_metadata", "JSON")
            ]
            
            for field_name, field_def in timeline_migrations:
                try:
                    cursor.execute(sql.SQL("ALTER TABLE timeline_events ADD COLUMN IF NOT EXISTS {} {}").format(
                        sql.Identifier(field_name),
                        sql.SQL(field_def)
                    ))
                    print(f"   ✅ Добавлено поле: {field_name}")
                except Exception as e:
                    print(f"   ⚠️  Ошибка при добавлении {field_name}: {e}")
            
            # Переименование metadata -> event_metadata, если нужно
            if 'metadata' in existing_columns and 'event_metadata' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE timeline_events RENAME COLUMN metadata TO event_metadata")
                    print("   ✅ Переименовано: metadata -> event_metadata")
                except Exception as e:
                    print(f"   ⚠️  Ошибка при переименовании: {e}")
        else:
            print("   ⚠️  Неизвестная структура таблицы timeline_events")
        
        # 3. Проверка и обновление user_id в cases (если NULL, но должно быть NOT NULL)
        print("\n3️⃣  Проверка user_id в cases...")
        cursor.execute("SELECT COUNT(*) FROM cases WHERE user_id IS NULL")
        null_user_count = cursor.fetchone()[0]
        if null_user_count > 0:
            print(f"   ⚠️  Найдено {null_user_count} записей с user_id = NULL")
            print("   ℹ️  В модели user_id должен быть NOT NULL, но в БД он nullable")
            print("   ℹ️  Рекомендуется обновить существующие записи или изменить модель")
        
        conn.commit()
        print("\n✅ Миграция завершена успешно!")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка при миграции: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
        return False

if __name__ == "__main__":
    print("⚠️  ВНИМАНИЕ: Этот скрипт изменит структуру базы данных!")
    print("Убедитесь, что у вас есть резервная копия БД.")
    response = input("Продолжить? (yes/no): ")
    
    if response.lower() in ['yes', 'y', 'да', 'д']:
        success = migrate_database()
        sys.exit(0 if success else 1)
    else:
        print("Миграция отменена.")
        sys.exit(0)
