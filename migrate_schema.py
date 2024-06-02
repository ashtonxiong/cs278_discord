from sqlalchemy import create_engine, MetaData
from database_setup import Base, CollaborativePlaylist

# Set up the database
engine = create_engine('sqlite:///spotify_tokens.db')

# Reflect the metadata
metadata = MetaData()
metadata.reflect(bind=engine)

# Drop the existing collaborative_playlists table if it exists
collaborative_playlists_table = metadata.tables.get('collaborative_playlists')
if collaborative_playlists_table is not None:
    collaborative_playlists_table.drop(engine)
    print("Dropped existing collaborative_playlists table.")
else:
    print("Table collaborative_playlists does not exist.")

# Create the table again with the updated schema
Base.metadata.create_all(engine)
print("Created new collaborative_playlists table with updated schema.")
