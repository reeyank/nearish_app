import os
import json
import uuid
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timezone
from dotenv import load_dotenv
from llm_service import generate_questions

# Load env
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'auth', '.env')
load_dotenv(env_path)
# Also load local .env if it exists
load_dotenv('.env')

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not found!")
    exit(1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Games(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    system_prompt = Column(String, nullable=True)

class GameQuestion(Base):
    __tablename__ = "game_questions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    game_id = Column(Integer, ForeignKey("games.id"))
    question_text = Column(Text)
    createdAt = Column(DateTime, default=datetime.now(timezone.utc))

def seed_games():
    db = SessionLocal()
    try:
        games = db.query(Games).all()
        
        for game in games:
            print(f"\n--- Processing Game: {game.name} (ID: {game.id}) ---")
            
            if not game.system_prompt:
                print("No system prompt, skipping.")
                continue

            # Count existing
            count = db.query(GameQuestion).filter(GameQuestion.game_id == game.id).count()
            print(f"Existing questions: {count}")
            
            target = 60
            needed = target - count
            
            if needed <= 0:
                print("Enough questions already.")
                continue
                
            print(f"Generating {needed} more questions...")
            
            # Fetch existing texts to avoid dupes (limit context window)
            existing_qs = db.query(GameQuestion.question_text).filter(GameQuestion.game_id == game.id).limit(100).all()
            existing_texts = [q[0] for q in existing_qs]
            
            # Generate in batches of 10
            while needed > 0:
                batch_size = min(needed, 10)
                print(f"Requesting batch of {batch_size}...")
                
                try:
                    new_items = generate_questions(game.system_prompt, existing_texts, count=batch_size)
                    
                    if not new_items:
                        print("LLM returned no items. Retrying or skipping.")
                        break

                    added_count = 0
                    for item in new_items:
                        # Serialize if dict
                        if isinstance(item, (dict, list)):
                            text_val = json.dumps(item)
                        else:
                            text_val = str(item).strip()
                        
                        # Check duplicate locally in this run
                        if text_val in existing_texts:
                            continue
                            
                        # Check duplicate in DB
                        exists = db.query(GameQuestion).filter(
                            GameQuestion.game_id == game.id, 
                            GameQuestion.question_text == text_val
                        ).first()
                        
                        if not exists:
                            nq = GameQuestion(game_id=game.id, question_text=text_val)
                            db.add(nq)
                            existing_texts.append(text_val)
                            added_count += 1
                    
                    db.commit()
                    print(f"Added {added_count} new questions.")
                    needed -= added_count
                    
                    if added_count == 0:
                        print("No unique questions generated in this batch. Stopping for this game.")
                        break
                        
                except Exception as e:
                    print(f"Error generating batch: {e}")
                    break
                    
    finally:
        db.close()

if __name__ == "__main__":
    seed_games()
