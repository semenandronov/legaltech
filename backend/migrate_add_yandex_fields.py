#!/usr/bin/env python3
"""Миграция: добавление полей yandex_index_id и yandex_assistant_id в таблицу cases"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

import psycopg2
from psycopg2 import sql

# Получаем DATABASE_URL из переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ Ошибка: DATABASE_URL не установлена в переменных окружения")
    sys.exit(1)

def migrate_database():
    """Выполнение миграции БД для добавления полей Yandex"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cursor = conn.cursor()
        
        print("🔄 Начало миграции БД для добавления полей Yandex...\n")
        
        # Добавление полей в таблицу cases
        print("1️⃣  Обновление таблицы cases...")
        yandex_migrations = [
            ("yandex_index_id", "VARCHAR(255)"),
            ("yandex_assistant_id", "VARCHAR(255)")
        ]
        
        for field_name, field_def in yandex_migrations:
            try:
                cursor.execute(sql.SQL("ALTER TABLE cases ADD COLUMN IF NOT EXISTS {} {}").format(
                    sql.Identifier(field_name),
                    sql.SQL(field_def)
                ))
                print(f"   ✅ Добавлено поле: {field_name}")
            except Exception as e:
                print(f"   ⚠️  Ошибка при добавлении {field_name}: {e}")
                conn.rollback()
                raise
        
        conn.commit()
        print("\n✅ Миграция завершена успешно!")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка при миграции: {e}")
        import traceback
        traceback.print_exc()
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    success = migrate_database()
    sys.exit(0 if success else 1)

