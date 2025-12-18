#!/usr/bin/env python3
"""Проверка соответствия структуры БД моделям SQLAlchemy"""
import psycopg2
from psycopg2 import sql
import sys

DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# Ожидаемые поля из моделей
EXPECTED_SCHEMA = {
    "cases": {
        "id": "character varying",
        "user_id": "character varying",
        "title": "character varying",
        "description": "text",  # ОТСУТСТВУЕТ
        "case_type": "character varying",  # ОТСУТСТВУЕТ
        "status": "character varying",  # ОТСУТСТВУЕТ
        "full_text": "text",
        "num_documents": "integer",
        "file_names": "json",
        "analysis_config": "json",  # ОТСУТСТВУЕТ
        "case_metadata": "json",  # ОТСУТСТВУЕТ
        "created_at": "timestamp without time zone",
        "updated_at": "timestamp without time zone"
    },
    "timeline_events": {
        "id": "text",
        "case_id": "character varying",  # В БД может быть другой тип
        "date": "date",
        "event_type": "character varying",
        "description": "text",
        "source_document": "character varying",
        "source_page": "integer",
        "source_line": "integer",
        "event_metadata": "json",  # В БД: metadata
        "created_at": "timestamp without time zone"
    },
    "document_chunks": {
        "id": "character varying",
        "case_id": "character varying",
        "file_id": "character varying",
        "chunk_index": "integer",
        "chunk_text": "text",
        "source_file": "character varying",
        "source_page": "integer",
        "source_start_line": "integer",
        "source_end_line": "integer",
        "embedding": "json",
        "chunk_metadata": "json",
        "created_at": "timestamp without time zone"
    }
}

def check_schema():
    """Проверка соответствия схемы БД моделям"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        issues = []
        
        for table_name, expected_fields in EXPECTED_SCHEMA.items():
            print(f"\n🔍 Проверка таблицы: {table_name}")
            
            # Получаем реальные поля из БД
            cursor.execute("""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position;
            """, (table_name,))
            actual_fields = {row[0]: row[1] for row in cursor.fetchall()}
            
            # Проверяем отсутствующие поля
            for field_name, expected_type in expected_fields.items():
                if field_name not in actual_fields:
                    issue = f"❌ Отсутствует поле: {table_name}.{field_name} (ожидается: {expected_type})"
                    issues.append(issue)
                    print(issue)
                else:
                    actual_type = actual_fields[field_name]
                    # Проверяем соответствие типов (с учетом вариаций)
                    if not types_match(expected_type, actual_type):
                        issue = f"⚠️  Несоответствие типа: {table_name}.{field_name} (ожидается: {expected_type}, фактически: {actual_type})"
                        issues.append(issue)
                        print(issue)
                    else:
                        print(f"   ✅ {field_name}: {actual_type}")
            
            # Проверяем лишние поля
            for field_name in actual_fields:
                if field_name not in expected_fields:
                    # Пропускаем системные поля или поля из других схем
                    if field_name not in ['timelineId', 'order', 'intervalDays']:  # Эти поля могут быть из другой схемы
                        issue = f"ℹ️  Дополнительное поле: {table_name}.{field_name} (тип: {actual_fields[field_name]})"
                        print(issue)
        
        # Специальная проверка для переименованных полей
        print("\n🔧 Проверка переименованных полей:")
        
        # Проверка timeline_events.metadata -> event_metadata
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'timeline_events'
            AND column_name IN ('metadata', 'event_metadata');
        """)
        timeline_metadata = [row[0] for row in cursor.fetchall()]
        if 'metadata' in timeline_metadata and 'event_metadata' not in timeline_metadata:
            issue = "❌ timeline_events.metadata должно быть переименовано в event_metadata"
            issues.append(issue)
            print(issue)
        elif 'event_metadata' in timeline_metadata:
            print("   ✅ timeline_events.event_metadata существует")
        
        # Проверка cases.case_metadata
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'cases'
            AND column_name = 'case_metadata';
        """)
        if cursor.fetchone() is None:
            issue = "❌ cases.case_metadata отсутствует"
            issues.append(issue)
            print(issue)
        else:
            print("   ✅ cases.case_metadata существует")
        
        cursor.close()
        conn.close()
        
        print("\n" + "="*60)
        if issues:
            print(f"❌ Найдено проблем: {len(issues)}")
            print("\nРекомендуется выполнить миграцию БД для приведения структуры в соответствие с моделями.")
            return False
        else:
            print("✅ Структура БД соответствует моделям!")
            return True
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False

def types_match(expected, actual):
    """Проверка соответствия типов с учетом вариаций"""
    # Нормализация типов
    type_mapping = {
        "character varying": ["character varying", "text"],
        "text": ["text", "character varying"],
        "integer": ["integer"],
        "json": ["json", "jsonb"],
        "timestamp without time zone": ["timestamp without time zone"],
        "date": ["date"]
    }
    
    for expected_type, allowed_types in type_mapping.items():
        if expected == expected_type:
            return actual in allowed_types
    
    return expected == actual

if __name__ == "__main__":
    success = check_schema()
    sys.exit(0 if success else 1)
