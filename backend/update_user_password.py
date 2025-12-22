"""Script to update user password in database"""
import sys
import os
import bcrypt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt directly"""
    # Bcrypt limitation: passwords cannot be longer than 72 bytes
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    
    # Generate salt and hash password using bcrypt directly
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    
    # Return as string (bcrypt hash is always ASCII-safe)
    return hashed.decode('utf-8')

# Database URL (can be overridden via command line or environment)
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://neondb_owner:npg_c5L8QzZstGWd@ep-silent-mountain-ah9la27e-pooler.c-3.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require')

def update_password(email: str, new_password: str):
    """Update user password in database"""
    # Create engine and session
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Hash the new password
        hashed_password = get_password_hash(new_password)
        print(f"✅ Пароль захеширован: {hashed_password[:50]}...")
        
        # Update password in database
        result = session.execute(
            text("UPDATE users SET password = :password WHERE email = :email"),
            {"password": hashed_password, "email": email}
        )
        
        session.commit()
        
        if result.rowcount > 0:
            print(f"✅ Пароль успешно обновлен для пользователя: {email}")
        else:
            print(f"⚠️  Пользователь с email {email} не найден")
            session.rollback()
    except Exception as e:
        print(f"❌ Ошибка при обновлении пароля: {e}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) >= 3:
        email = sys.argv[1]
        new_password = sys.argv[2]
    else:
        email = "semenandronov2004@mail.ru"
        new_password = "salon017"
    
    print(f"Обновление пароля для пользователя: {email}")
    update_password(email, new_password)

