"""Force database initialization script"""
from app.utils.database import init_db
from app.models.case import Base, Case, ChatMessage
from sqlalchemy import inspect
from app.config import config
from sqlalchemy import create_engine

engine = create_engine(config.DATABASE_URL, echo=True)

def check_tables():
    """Check if tables exist"""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"Existing tables: {tables}")
    return tables

def init_db_force():
    """Force create all tables"""
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created!")
    check_tables()

if __name__ == "__main__":
    check_tables()
    init_db_force()

