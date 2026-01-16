#!/usr/bin/env python3
"""Проверка структуры таблицы editor_documents"""
import psycopg2
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
)

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# Проверяем структуру editor_documents
print('=== Структура editor_documents ===')
cursor.execute("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name = 'editor_documents'
    ORDER BY ordinal_position;
""")
for row in cursor.fetchall():
    print(f'  {row[0]}: {row[1]} (nullable: {row[2]})')

# Проверяем индексы
print('\n=== Индексы editor_documents ===')
cursor.execute("""
    SELECT indexname
    FROM pg_indexes
    WHERE tablename = 'editor_documents';
""")
for row in cursor.fetchall():
    print(f'  {row[0]}')

# Проверяем foreign keys
print('\n=== Foreign Keys editor_documents ===')
cursor.execute("""
    SELECT kcu.column_name, ccu.table_name, ccu.column_name
    FROM information_schema.table_constraints AS tc
    JOIN information_schema.key_column_usage AS kcu
      ON tc.constraint_name = kcu.constraint_name
    JOIN information_schema.constraint_column_usage AS ccu
      ON ccu.constraint_name = tc.constraint_name
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_name = 'editor_documents';
""")
for row in cursor.fetchall():
    print(f'  {row[0]} -> {row[1]}.{row[2]}')

# Проверяем количество документов
print('\n=== Статистика ===')
cursor.execute("SELECT COUNT(*) FROM editor_documents")
count = cursor.fetchone()[0]
print(f'  Всего документов: {count}')

cursor.close()
conn.close()
print('\n✅ Проверка завершена')






