import os
import json
import ast
from sqlalchemy import create_engine, Column, String, Text, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'auth', '.env')
load_dotenv(env_path)
load_dotenv('.env')

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Question(Base):
    __tablename__ = "questions"
    id = Column(String, primary_key=True)
    # Removing ForeignKey for this script to avoid metadata issues
    category_id = Column(String) 
    text = Column(Text)
    createdAt = Column(DateTime, default=datetime.now(timezone.utc))

def clean_questions():
    db = SessionLocal()
    try:
        questions = db.query(Question).all()
        updated_count = 0
        
        for q in questions:
            original_text = q.text
            new_text = original_text
            
            try:
                # Try parsing as JSON first
                data = json.loads(original_text)
                if isinstance(data, dict):
                    # Extract text from known keys
                    if 'question' in data:
                        new_text = data['question']
                    elif 'text' in data:
                        new_text = data['text']
                    elif 'prompt' in data:
                        new_text = data['prompt']
            except (json.JSONDecodeError, TypeError):
                # If JSON fails, try python literal_eval (for single quotes)
                try:
                    data = ast.literal_eval(original_text)
                    if isinstance(data, dict):
                        if 'question' in data:
                            new_text = data['question']
                        elif 'text' in data:
                            new_text = data['text']
                        elif 'prompt' in data:
                            new_text = data['prompt']
                except (ValueError, SyntaxError):
                    pass
            
            # Final cleanup
            if new_text != original_text:
                print(f"Cleaning ID {q.id}...")
                q.text = new_text
                updated_count += 1
        
        db.commit()
        print(f"\nSuccessfully cleaned {updated_count} questions.")
        
    except Exception as e:
        print(f"Error: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    clean_questions()