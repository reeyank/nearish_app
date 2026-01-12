from sqlalchemy import create_engine
from main import Base, NearishUser, Streak, Memory

SQLALCHEMY_DATABASE_URL = "postgresql://postgres:IwVFaHIwQfulvssagcqReUsKLrEZcUcA@shuttle.proxy.rlwy.net:58300/railway"
engine = create_engine(SQLALCHEMY_DATABASE_URL)

print("Dropping tables...")
Memory.__table__.drop(engine, checkfirst=True)
Streak.__table__.drop(engine, checkfirst=True)
NearishUser.__table__.drop(engine, checkfirst=True)

print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Done.")
