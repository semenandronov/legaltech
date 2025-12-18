#!/usr/bin/env python3
"""Скрипт для сброса пароля пользователя"""
import sys
import os
import secrets
import string

try:
    import psycopg2
except ImportError:
    print("Устанавливаю psycopg2-binary...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary", "--quiet"])
    import psycopg2

DATABASE_URL = "postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

def hash_password(password: str) -> str:
    """Хеширует пароль используя bcrypt напрямую"""
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    
    try:
        import bcrypt
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "bcrypt", "--quiet"])
        import bcrypt
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')

def reset_password(email: str, new_password: str = None):
    """Сбрасывает пароль пользователя"""
    if not new_password:
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        new_password = ''.join(secrets.choice(alphabet) for i in range(12))
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False
        cursor = conn.cursor()
        
        # Проверяем, существует ли пользователь
        cursor.execute("SELECT id, email FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        
        if not user:
            print(f"❌ Пользователь с email {email} не найден!")
            cursor.close()
            conn.close()
            return None
        
        # Хешируем новый пароль
        password_hash = hash_password(new_password)
        
        # Обновляем пароль
        cursor.execute("UPDATE users SET password = %s WHERE email = %s", (password_hash, email))
        conn.commit()
        
        print("✅ Пароль успешно сброшен!")
        print(f"\n📧 Данные для входа:")
        print(f"Email: {email}")
        print(f"Новый пароль: {new_password}")
        print(f"\n⚠️  ВАЖНО: Сохраните эти данные! Пароль показан только один раз.")
        
        cursor.close()
        conn.close()
        
        return {
            "email": email,
            "password": new_password
        }
        
    except Exception as e:
        print(f"❌ Ошибка при сбросе пароля: {e}")
        import traceback
        traceback.print_exc()
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return None

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Сбросить пароль пользователя")
    parser.add_argument("--email", type=str, required=True, help="Email пользователя")
    parser.add_argument("--password", type=str, help="Новый пароль (если не указан, будет сгенерирован)")
    
    args = parser.parse_args()
    
    result = reset_password(email=args.email, new_password=args.password)
    
    if result:
        sys.exit(0)
    else:
        sys.exit(1)
