"""
Script to create database tables manually.
Run this if Alembic migrations are not working.
"""
from app.core.database import Base, engine
from app.models import User, Customer, Vehicle, Estimate, EstimateItem

def create_tables():
    """Create all database tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✅ All tables created successfully!")
    
    # Print created tables
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print(f"\nCreated tables: {', '.join(tables)}")

if __name__ == "__main__":
    create_tables()
