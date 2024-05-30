from sqlalchemy import create_engine, Column, String, Integer, MetaData, Table, text
from sqlalchemy.orm import sessionmaker
import sqlite3

# Define the old and new table schemas
old_table_name = 'spotify_tokens'
new_table_name = 'spotify_tokens_new'

# Create a new engine and connect to the existing database
engine = create_engine('sqlite:///spotify_tokens.db')
connection = engine.connect()
metadata = MetaData()

# Define the new table with the additional 'expires_at' column
new_table = Table(new_table_name, metadata,
    Column('id', Integer, primary_key=True),
    Column('user_id', String, unique=True, nullable=False),
    Column('access_token', String, nullable=False),
    Column('refresh_token', String),
    Column('token_type', String),
    Column('expires_in', Integer),
    Column('scope', String),
    Column('expires_at', Integer)
)

# Create the new table
metadata.create_all(engine)

# Copy the data from the old table to the new table
connection.execute(text(f'''
    INSERT INTO {new_table_name} (id, user_id, access_token, refresh_token, token_type, expires_in, scope)
    SELECT id, user_id, access_token, refresh_token, token_type, expires_in, scope FROM {old_table_name}
'''))

# Drop the old table and rename the new table to the old table name
connection.execute(text(f'DROP TABLE {old_table_name}'))
connection.execute(text(f'ALTER TABLE {new_table_name} RENAME TO {old_table_name}'))

# Close the connection
connection.close()
