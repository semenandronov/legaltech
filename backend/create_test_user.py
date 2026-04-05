#!/usr/bin/env python3
"""Скрипт для создания тестового пользователя"""
import sys
import os
import secrets
import string
import uuid
from datetime import datetime

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    print("Устанавливаю psycopg2-binary...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "--quiet"])
    import psycopg2
    from psycopg2 import sql

# Строка подключения к БД (приоритет: переменная окружения, затем .env)
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent / ".env"
    if _env.is_file():
        load_dotenv(_env)
except ImportError:
    pass

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def generate_password(length=12):
    """Генерирует безопасный пароль"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    return password

def hash_password(password: str) -> str:
    """Хеширует пароль используя bcrypt напрямую"""
    # Bcrypt limitation: 72 bytes max - обрезаем ДО хеширования
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    
    try:
        import bcrypt
        # Генерируем salt и хешируем пароль
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    except ImportError:
        print("Устанавливаю bcrypt...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "bcrypt", "--quiet"])
        import bcrypt
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')

def create_test_user(email: str = None, password: str = None):
    """Создает тестового пользователя"""
    # Генерируем данные, если не указаны
    if not email:
        email = f"test_{secrets.token_hex(4)}@legaltech.local"
    
    if not password:
        password = generate_password(12)
    
    try:
        # Подключаемся к БД
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cursor = conn.cursor()
        
        # Проверяем, существует ли пользователь
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        existing_user = cursor.fetchone()
        
        if existing_user:
            print(f"❌ Пользователь с email {email} уже существует!")
            print(f"\n💡 Попробуйте использовать другой email или сбросить пароль.")
            cursor.close()
            conn.close()
            return None
        
        # Генерируем ID пользователя
        user_id = str(uuid.uuid4())
        
        # Хешируем пароль
        password_hash = hash_password(password)
        
        # Создаем пользователя
        now = datetime.utcnow()
        cursor.execute("""
            INSERT INTO users (id, email, password, name, role, "createdAt", "updatedAt")
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, email, password_hash, "Test User", "USER", now, now))
        
        conn.commit()
        
        print("✅ Пользователь успешно создан!")
        print(f"\n📧 Данные для входа:")
        print(f"Email: {email}")
        print(f"Пароль: {password}")
        print(f"\n⚠️  ВАЖНО: Сохраните эти данные! Пароль показан только один раз.")
        print(f"\n🔗 URL для входа: https://legaltech-ynit.onrender.com/login")
        
        cursor.close()
        conn.close()
        
        return {
            "email": email,
            "password": password,
            "user_id": user_id
        }
        
    except Exception as e:
        print(f"❌ Ошибка при создании пользователя: {e}")
        import traceback
        traceback.print_exc()
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return None

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Создать тестового пользователя")
    parser.add_argument("--email", type=str, help="Email пользователя")
    parser.add_argument("--password", type=str, help="Пароль пользователя (если не указан, будет сгенерирован)")
    
    args = parser.parse_args()
    
    result = create_test_user(email=args.email, password=args.password)
    
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
