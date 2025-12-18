#!/usr/bin/env python3
"""Скрипт для проверки состояния базы данных"""
import psycopg2
from psycopg2 import sql
import sys

# Строка подключения
DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def check_database():
    """Проверка состояния базы данных"""
    try:
        # Подключение к БД
        print("🔌 Подключение к базе данных...")
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # 1. Проверка версии PostgreSQL
        print("\n📊 Информация о базе данных:")
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"   PostgreSQL версия: {version.split(',')[0]}")
        
        # 2. Список всех таблиц
        print("\n📋 Список таблиц:")
        cursor.execute("""
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = cursor.fetchall()
        if tables:
            for table_name, table_type in tables:
                print(f"   - {table_name} ({table_type})")
        else:
            print("   ⚠️  Таблицы не найдены")
        
        # 3. Проверка структуры каждой таблицы
        print("\n🔍 Структура таблиц:")
        for table_name, _ in tables:
            print(f"\n   Таблица: {table_name}")
            cursor.execute("""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position;
            """, (table_name,))
            columns = cursor.fetchall()
            for col_name, data_type, is_nullable, default in columns:
                nullable = "NULL" if is_nullable == "YES" else "NOT NULL"
                default_str = f" DEFAULT {default}" if default else ""
                print(f"     - {col_name}: {data_type} {nullable}{default_str}")
        
        # 4. Количество записей в каждой таблице
        print("\n📈 Количество записей в таблицах:")
        for table_name, _ in tables:
            cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(
                sql.Identifier(table_name)
            ))
            count = cursor.fetchone()[0]
            print(f"   - {table_name}: {count} записей")
        
        # 5. Проверка индексов
        print("\n🔑 Индексы:")
        cursor.execute("""
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY tablename, indexname;
        """)
        indexes = cursor.fetchall()
        if indexes:
            current_table = None
            for tablename, indexname, indexdef in indexes:
                if current_table != tablename:
                    print(f"   Таблица: {tablename}")
                    current_table = tablename
                print(f"     - {indexname}")
        else:
            print("   ⚠️  Индексы не найдены")
        
        # 6. Проверка внешних ключей
        print("\n🔗 Внешние ключи:")
        cursor.execute("""
            SELECT
                tc.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name,
                tc.constraint_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = 'public'
            ORDER BY tc.table_name;
        """)
        foreign_keys = cursor.fetchall()
        if foreign_keys:
            for table_name, column_name, foreign_table, foreign_column, constraint_name in foreign_keys:
                print(f"   {table_name}.{column_name} -> {foreign_table}.{foreign_column} ({constraint_name})")
        else:
            print("   ⚠️  Внешние ключи не найдены")
        
        # 7. Проверка последних записей в основных таблицах
        print("\n📝 Последние записи (если есть):")
        main_tables = ['cases', 'users', 'documents', 'timeline_events', 'key_facts', 'discrepancies']
        for table_name in main_tables:
            if any(t[0] == table_name for t in tables):
                cursor.execute(sql.SQL("""
                    SELECT * FROM {}
                    ORDER BY id DESC
                    LIMIT 3
                """).format(sql.Identifier(table_name)))
                rows = cursor.fetchall()
                if rows:
                    print(f"\n   {table_name} (последние 3 записи):")
                    # Получаем названия колонок
                    cursor.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = %s
                        ORDER BY ordinal_position;
                    """, (table_name,))
                    column_names = [col[0] for col in cursor.fetchall()]
                    for row in rows:
                        row_dict = dict(zip(column_names, row))
                        print(f"     {row_dict}")
        
        cursor.close()
        conn.close()
        print("\n✅ Проверка завершена успешно!")
        return True
        
    except psycopg2.Error as e:
        print(f"\n❌ Ошибка при работе с базой данных: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = check_database()
    sys.exit(0 if success else 1)
