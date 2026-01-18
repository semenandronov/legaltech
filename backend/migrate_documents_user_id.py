#!/usr/bin/env python3
"""Миграция для исправления user_id в таблице documents"""
import psycopg2
from psycopg2 import sql
import sys
import os

# Get database URL from environment or use default
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

def migrate_documents_user_id():
    """Выполнение миграции для исправления user_id в documents"""
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cursor = conn.cursor()
        
        print("🔄 Начало миграции documents.user_id...\n")
        
        # Check current column name
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'documents' 
            AND column_name IN ('user_id', 'userId')
            ORDER BY column_name;
        """)
        existing_columns = [row[0] for row in cursor.fetchall()]
        
        print(f"Найдены колонки: {existing_columns}")
        
        # Check if user_id exists (snake_case)
        if 'user_id' in existing_columns and 'userId' not in existing_columns:
            print("Переименование user_id -> userId...")
            cursor.execute('ALTER TABLE documents RENAME COLUMN user_id TO "userId"')
            print("✅ Колонка переименована: user_id -> userId")
        elif 'userId' in existing_columns:
            print("✅ Колонка userId уже существует")
        elif 'user_id' not in existing_columns and 'userId' not in existing_columns:
            print("Создание колонки userId...")
            cursor.execute('ALTER TABLE documents ADD COLUMN "userId" VARCHAR')
            cursor.execute('ALTER TABLE documents ADD CONSTRAINT fk_documents_user FOREIGN KEY ("userId") REFERENCES users(id) ON DELETE CASCADE')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents("userId")')
            print("✅ Колонка userId создана")
        
        # Verify table structure
        cursor.execute("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'documents'
            ORDER BY ordinal_position;
        """)
        
        print("\n📋 Структура таблицы documents:")
        for row in cursor.fetchall():
            print(f"   {row[0]}: {row[1]} (nullable: {row[2]})")
        
        conn.commit()
        print("\n✅ Миграция завершена успешно!")
        
        cursor.close()
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка при миграции: {e}")
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print("⚠️  ВНИМАНИЕ: Этот скрипт изменит структуру базы данных!")
    print("Убедитесь, что у вас есть резервная копия БД.")
    response = input("Продолжить? (yes/no): ")
    
    if response.lower() in ['yes', 'y', 'да', 'д']:
        success = migrate_documents_user_id()
        sys.exit(0 if success else 1)
    else:
        print("Миграция отменена.")
        sys.exit(0)











