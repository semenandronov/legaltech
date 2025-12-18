#!/usr/bin/env python3
"""Исправление данных в БД: установка user_id и миграция timeline_events"""
import psycopg2
from psycopg2 import sql
import sys

DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def fix_database():
    """Исправление данных в БД"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cursor = conn.cursor()
        
        print("🔄 Начало исправления данных в БД...\n")
        
        # 1. Получаем первый доступный user_id
        print("1️⃣  Поиск пользователей...")
        cursor.execute("SELECT id FROM users LIMIT 1")
        user_result = cursor.fetchone()
        
        if not user_result:
            print("   ❌ Пользователи не найдены. Создаём тестового пользователя...")
            # Создаём тестового пользователя, если его нет
            import uuid
            test_user_id = str(uuid.uuid4())
            cursor.execute("""
                INSERT INTO users (id, email, password, name, role, "createdAt", "updatedAt")
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """, (test_user_id, "system@legaltech.local", "system", "System User", "USER"))
            default_user_id = test_user_id
            print(f"   ✅ Создан тестовый пользователь: {default_user_id}")
        else:
            default_user_id = user_result[0]
            print(f"   ✅ Найден пользователь: {default_user_id}")
        
        # 2. Обновляем cases с NULL user_id
        print("\n2️⃣  Обновление cases с NULL user_id...")
        cursor.execute("SELECT COUNT(*) FROM cases WHERE user_id IS NULL")
        null_count = cursor.fetchone()[0]
        
        if null_count > 0:
            cursor.execute("""
                UPDATE cases 
                SET user_id = %s 
                WHERE user_id IS NULL
            """, (default_user_id,))
            updated_count = cursor.rowcount
            print(f"   ✅ Обновлено записей: {updated_count}")
        else:
            print("   ℹ️  Нет записей с NULL user_id")
        
        # 3. Миграция timeline_events на новую схему
        print("\n3️⃣  Миграция timeline_events...")
        
        # Проверяем текущую структуру
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'timeline_events'
            ORDER BY column_name;
        """)
        existing_columns = [row[0] for row in cursor.fetchall()]
        
        if 'timelineId' in existing_columns and 'case_id' not in existing_columns:
            print("   ℹ️  Обнаружена старая схема (timelineId). Начинаем миграцию...")
            
            # Проверяем, есть ли данные
            cursor.execute("SELECT COUNT(*) FROM timeline_events")
            event_count = cursor.fetchone()[0]
            
            if event_count > 0:
                print(f"   ⚠️  Найдено {event_count} записей. Нужно связать их с cases через timelines.")
                # Получаем связи timeline -> case через таблицу timelines
                cursor.execute("""
                    SELECT DISTINCT t.id, t."userId"
                    FROM timelines t
                    WHERE EXISTS (
                        SELECT 1 FROM timeline_events te WHERE te."timelineId" = t.id
                    )
                """)
                timeline_users = cursor.fetchall()
                
                if timeline_users:
                    print(f"   ℹ️  Найдено {len(timeline_users)} уникальных timelines")
                    # Для каждой timeline находим связанный case через user_id
                    for timeline_id, user_id in timeline_users:
                        cursor.execute("""
                            SELECT id FROM cases 
                            WHERE user_id = %s 
                            ORDER BY created_at DESC 
                            LIMIT 1
                        """, (user_id,))
                        case_result = cursor.fetchone()
                        if case_result:
                            case_id = case_result[0]
                            # Обновляем timeline_events, добавляя case_id
                            cursor.execute("""
                                UPDATE timeline_events 
                                SET case_id = %s 
                                WHERE "timelineId" = %s AND case_id IS NULL
                            """, (case_id, timeline_id))
                            print(f"   ✅ Связано timeline {timeline_id} с case {case_id}")
            
            # Добавляем недостающие поля
            print("   📝 Добавление недостающих полей...")
            new_fields = [
                ("case_id", "VARCHAR", "NULL"),
                ("event_type", "VARCHAR(100)", "NULL"),
                ("source_document", "VARCHAR(255)", "NULL"),
                ("source_page", "INTEGER", "NULL"),
                ("source_line", "INTEGER", "NULL"),
                ("event_metadata", "JSON", "NULL")
            ]
            
            for field_name, field_type, default in new_fields:
                try:
                    cursor.execute(sql.SQL("ALTER TABLE timeline_events ADD COLUMN IF NOT EXISTS {} {}").format(
                        sql.Identifier(field_name),
                        sql.SQL(f"{field_type} {default}")
                    ))
                    print(f"      ✅ Добавлено поле: {field_name}")
                except Exception as e:
                    print(f"      ⚠️  Ошибка при добавлении {field_name}: {e}")
            
            # Копируем данные из старых полей в новые
            print("   📋 Копирование данных из старых полей...")
            
            # eventType -> event_type
            if 'eventType' in existing_columns:
                try:
                    cursor.execute("""
                        UPDATE timeline_events 
                        SET event_type = "eventType" 
                        WHERE event_type IS NULL AND "eventType" IS NOT NULL
                    """)
                    print(f"      ✅ Скопировано eventType -> event_type ({cursor.rowcount} записей)")
                except Exception as e:
                    print(f"      ⚠️  Ошибка при копировании eventType: {e}")
            
            # metadata -> event_metadata
            if 'metadata' in existing_columns:
                try:
                    cursor.execute("""
                        UPDATE timeline_events 
                        SET event_metadata = metadata::json 
                        WHERE event_metadata IS NULL AND metadata IS NOT NULL
                    """)
                    print(f"      ✅ Скопировано metadata -> event_metadata ({cursor.rowcount} записей)")
                except Exception as e:
                    print(f"      ⚠️  Ошибка при копировании metadata: {e}")
            
            # Переименовываем createdAt -> created_at, если нужно
            if 'createdAt' in existing_columns and 'created_at' not in existing_columns:
                try:
                    cursor.execute("ALTER TABLE timeline_events RENAME COLUMN \"createdAt\" TO created_at")
                    print("      ✅ Переименовано createdAt -> created_at")
                except Exception as e:
                    print(f"      ⚠️  Ошибка при переименовании createdAt: {e}")
            
            # Устанавливаем source_document из description, если возможно
            try:
                cursor.execute("""
                    UPDATE timeline_events 
                    SET source_document = 'Unknown'
                    WHERE source_document IS NULL
                """)
                print(f"      ✅ Установлен source_document по умолчанию ({cursor.rowcount} записей)")
            except Exception as e:
                print(f"      ⚠️  Ошибка при установке source_document: {e}")
            
            print("   ✅ Миграция timeline_events завершена")
        elif 'case_id' in existing_columns:
            print("   ℹ️  Таблица уже использует новую схему (case_id)")
        else:
            print("   ⚠️  Неизвестная структура таблицы timeline_events")
        
        conn.commit()
        print("\n✅ Исправление данных завершено успешно!")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка при исправлении данных: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
        return False

if __name__ == "__main__":
    print("⚠️  ВНИМАНИЕ: Этот скрипт изменит данные в базе данных!")
    print("Убедитесь, что у вас есть резервная копия БД.")
    response = input("Продолжить? (yes/no): ")
    
    if response.lower() in ['yes', 'y', 'да', 'д']:
        success = fix_database()
        sys.exit(0 if success else 1)
    else:
        print("Операция отменена.")
        sys.exit(0)
