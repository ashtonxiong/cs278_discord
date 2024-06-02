# initialize_db.py
from database_setup import engine, Base

# Create all tables
Base.metadata.create_all(engine)
print("All tables created successfully.")
