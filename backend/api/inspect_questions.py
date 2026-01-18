import os
import json
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'auth', '.env')
load_dotenv(env_path)
load_dotenv('.env')

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    result = conn.execute(text("SELECT id, text FROM questions LIMIT 20"))
    print("--- Sample Questions ---")
    for row in result:
        print(f"ID: {row[0]}")
        print(f"Text: {row[1]}")
        print("-" * 20)
