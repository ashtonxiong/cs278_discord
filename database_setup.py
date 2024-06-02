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

class Playlist(Base):
    __tablename__ = 'playlists'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String)
    url = Column(String, nullable=False)
    user_id = Column(String, nullable=False)

    def __repr__(self):
        return f"<Playlist(name='{self.name}', user_id='{self.user_id}')>"

# Set up the database
engine = create_engine('sqlite:///spotify_tokens.db')
Base.metadata.create_all(engine)

# Create a session for SQLAlchemy
Session = sessionmaker(bind=engine)
sql_session = Session()

def add_playlist_to_db(playlist_id, name, description, url, user_id):
    playlist = Playlist(id=playlist_id, name=name, description=description, url=url, user_id=user_id)
    sql_session.add(playlist)
    sql_session.commit()

def fetch_playlists_from_db(user_id):
    return sql_session.query(Playlist).filter_by(user_id=user_id).all()