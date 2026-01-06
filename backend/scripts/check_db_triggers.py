#!/usr/bin/env python3
"""Script to check for database triggers that might create columns automatically"""
import psycopg2

DATABASE_URL = 'postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require'

def check_triggers():
    """Check for triggers on tabular_columns table"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Check for triggers on tabular_columns
        cur.execute("""
            SELECT trigger_name, event_manipulation, event_object_table, action_statement
            FROM information_schema.triggers
            WHERE event_object_table = 'tabular_columns'
            ORDER BY trigger_name;
        """)
        
        triggers = cur.fetchall()
        
        if triggers:
            print(f"⚠️  Found {len(triggers)} triggers on tabular_columns table:")
            for trigger in triggers:
                print(f"  - {trigger[0]} ({trigger[1]})")
                print(f"    Statement: {trigger[3][:200]}...")
        else:
            print("✅ No triggers found on tabular_columns table")
        
        # Check for functions that might create columns
        cur.execute("""
            SELECT routine_name, routine_definition
            FROM information_schema.routines
            WHERE routine_schema = 'public'
            AND (routine_definition LIKE '%tabular_columns%' OR routine_definition LIKE '%TabularColumn%')
            ORDER BY routine_name;
        """)
        
        functions = cur.fetchall()
        
        if functions:
            print(f"\n⚠️  Found {len(functions)} functions that might interact with tabular_columns:")
            for func in functions:
                print(f"  - {func[0]}")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"❌ Error checking triggers: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_triggers()

