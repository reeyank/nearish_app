from sqlalchemy import create_engine, Column, String, DateTime, Integer, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import uuid

# Database Connection
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:IwVFaHIwQfulvssagcqReUsKLrEZcUcA@shuttle.proxy.rlwy.net:58300/railway"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
Base = declarative_base()

class Streak(Base):
    __tablename__ = "streak"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    userId = Column(String, unique=True) # Removed ForeignKey constraint for simplified creation script
    currentStreak = Column(Integer, default=0)
    lastLoginDate = Column(DateTime)
    createdAt = Column(DateTime, default=datetime.utcnow)
    updatedAt = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

print("Creating streak table...")
Base.metadata.create_all(bind=engine)
print("Done.")
