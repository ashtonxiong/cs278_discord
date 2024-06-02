from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

class SpotifyToken(Base):
    __tablename__ = 'spotify_tokens'
    id = Column(Integer, primary_key=True)
    user_id = Column(String, unique=True, nullable=False)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String)
    token_type = Column(String)
    expires_in = Column(Integer)
    scope = Column(String)
    expires_at = Column(Integer)

    def __repr__(self):
        return f"<SpotifyToken(user_id='{self.user_id}', access_token='{self.access_token}')>"

class CollaborativePlaylist(Base):
    __tablename__ = 'collaborative_playlists'
    id = Column(Integer, primary_key=True)
    playlist_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String)
    playlist_url = Column(String, nullable=False)  # Ensure this column is defined
    created_by = Column(String, nullable=False)

    def __repr__(self):
        return f"<CollaborativePlaylist(playlist_id='{self.playlist_id}', name='{self.name}')>"

# Set up the database
engine = create_engine('sqlite:///spotify_tokens.db')
Base.metadata.create_all(engine)

# Create a session for SQLAlchemy
Session = sessionmaker(bind=engine)
sql_session = Session()

def add_playlist_to_db(playlist_id, name, description, playlist_url, user_id):
    session = Session()
    new_playlist = CollaborativePlaylist(
        playlist_id=playlist_id,
        name=name,
        description=description,
        playlist_url=playlist_url,
        created_by=user_id
    )
    session.add(new_playlist)
    session.commit()
    session.close()

def fetch_all_playlists_from_db():
    session = Session()
    playlists = session.query(CollaborativePlaylist).all()
    session.close()
    return playlists
