from sqlalchemy import create_engine, Column, String, Integer, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()

# Set up the database
engine = create_engine('sqlite:///spotify_tokens.db')
Base.metadata.create_all(engine)

# Create a session for SQLAlchemy
Session = sessionmaker(bind=engine)

def get_session():
    return Session()

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
    playlist_url = Column(String, nullable=False)
    created_by = Column(String, nullable=False)

    def __repr__(self):
        return f"<CollaborativePlaylist(playlist_id='{self.playlist_id}', name='{self.name}')>"

class MusicProfile(Base):
    __tablename__ = 'music_profiles'
    user_id = Column(String, primary_key=True)
    name = Column(String)
    genres = Column(String)
    artists = Column(String)
    song = Column(String)
    events = Column(String)
    top_songs = Column(JSON)
    top_artists = Column(JSON)

    def __repr__(self):
        return f"<MusicProfile(user_id='{self.user_id}', name='{self.name}')>"

def add_playlist_to_db(playlist_id, name, description, playlist_url, user_id):
    session = get_session()
    try:
        new_playlist = CollaborativePlaylist(
            playlist_id=playlist_id,
            name=name,
            description=description,
            playlist_url=playlist_url,
            created_by=user_id
        )
        session.add(new_playlist)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Error adding playlist to DB: {e}")
    finally:
        session.close()

def fetch_all_playlists_from_db():
    session = get_session()
    try:
        playlists = session.query(CollaborativePlaylist).all()
        return playlists
    except Exception as e:
        print(f"Error fetching playlists from DB: {e}")
        return []
    finally:
        session.close()

def save_music_profile(user_id, profile):
    session = get_session()
    try:
        existing_profile = session.query(MusicProfile).filter_by(user_id=user_id).first()
        if existing_profile:
            existing_profile.name = profile['name']
            existing_profile.genres = profile['genres']
            existing_profile.artists = profile['artists']
            existing_profile.song = profile['song']
            existing_profile.events = profile['events']
            existing_profile.top_songs = profile['top_songs']
            existing_profile.top_artists = profile['top_artists']
        else:
            new_profile = MusicProfile(
                user_id=user_id,
                name=profile['name'],
                genres=profile['genres'],
                artists=profile['artists'],
                song=profile['song'],
                events=profile['events'],
                top_songs=profile['top_songs'],
                top_artists=profile['top_artists']
            )
            session.add(new_profile)
        session.commit()
    except Exception as e:
        session.rollback()
        print(f"Error saving music profile: {e}")
    finally:
        session.close()

def get_music_profile(user_id):
    session = get_session()
    try:
        profile = session.query(MusicProfile).filter_by(user_id=user_id).first()
        return profile
    except Exception as e:
        print(f"Error fetching music profile: {e}")
        return None
    finally:
        session.close()