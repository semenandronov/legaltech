"""Initialize database tables"""
from app.utils.database import init_db

if __name__ == "__main__":
    print("Инициализация базы данных...")
    init_db()
    print("База данных инициализирована успешно!")

