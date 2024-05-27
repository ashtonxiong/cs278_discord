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

    def __repr__(self):
        return f"<SpotifyToken(user_id='{self.user_id}', access_token='{self.access_token}')>"

# Set up the database
engine = create_engine('sqlite:///spotify_tokens.db')
Base.metadata.create_all(engine)

# Create a session for SQLAlchemy
Session = sessionmaker(bind=engine)
sql_session = Session()