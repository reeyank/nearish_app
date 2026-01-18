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
load_dotenv('.env')

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("DATABASE_URL not found!")
    exit(1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class QuestionCategory(Base):
    __tablename__ = "question_categories"
    id = Column(String, primary_key=True)
    title = Column(String)
    emoji = Column(String)
    backgroundColor = Column(String)
    accentColor = Column(String)
    createdAt = Column(DateTime, default=datetime.now(timezone.utc))

class Question(Base):
    __tablename__ = "questions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    category_id = Column(String, ForeignKey("question_categories.id"))
    text = Column(Text)
    createdAt = Column(DateTime, default=datetime.now(timezone.utc))

CATEGORIES = [
  {
    "id": 'getting-started',
    "title": 'Getting Started',
    "emoji": '👋',
    "backgroundColor": '#FFF0F3', # Colors.topicCards.rose
    "accentColor": '#D4636F',
    "prompt": "Generate casual, ice-breaker questions for a couple to get to know each other or start a conversation. Simple, fun, and low-stakes."
  },
  {
    "id": 'deep-talks',
    "title": 'Deep Conversations',
    "emoji": '💭',
    "backgroundColor": '#F3F0FF', # Colors.topicCards.lavender
    "accentColor": '#8B7BA3',
    "prompt": "Generate deep, philosophical, or emotionally significant questions for a couple. Focus on values, beliefs, life meaning, and personal growth."
  },
  {
    "id": 'relationship',
    "title": 'Relationship',
    "emoji": '💕',
    "backgroundColor": '#FFF0F3',
    "accentColor": '#D4636F',
    "prompt": "Generate questions specifically about the relationship dynamic, feelings, communication, and appreciation between partners."
  },
  {
    "id": 'future',
    "title": 'Future Together',
    "emoji": '🔮',
    "backgroundColor": '#F0F9FF', # Colors.topicCards.sky
    "accentColor": '#5B8DB8',
    "prompt": "Generate questions about future goals, dreams, plans, and shared visions for a couple."
  },
  {
    "id": 'memories',
    "title": 'Memories',
    "emoji": '📸',
    "backgroundColor": '#FFF5EB', # Colors.topicCards.peach
    "accentColor": '#D4896F',
    "prompt": "Generate nostalgic questions asking a couple to recall specific past memories, first dates, and shared experiences."
  },
  {
    "id": 'intimacy',
    "title": 'Intimacy',
    "emoji": '🌹',
    "backgroundColor": '#FFF0F3',
    "accentColor": '#C4636F',
    "prompt": "Generate intimate, romantic, and spicy questions for a couple to deepen their physical and emotional connection. Keep it tasteful but romantic."
  },
  {
    "id": 'fun-hypotheticals',
    "title": 'Fun Hypotheticals',
    "emoji": '🎭',
    "backgroundColor": '#FAF6F0', # Colors.gameCards.cream
    "accentColor": '#B89B7A',
    "prompt": "Generate fun 'What if...' or hypothetical scenario questions for a couple to discuss playfully."
  },
  {
    "id": 'spicy',
    "title": 'Spicy',
    "emoji": '🌶️',
    "backgroundColor": '#FFF0F0', # Very light red
    "accentColor": '#E63946', # Hot red
    "prompt": "Generate hot, spicy, and adventurous questions for a couple to explore their desires, fantasies, and physical intimacy. Keep it exciting and bold."
  },
]

# Create tables if they don't exist
Base.metadata.create_all(bind=engine)

def seed_categories():
    db = SessionLocal()
    try:
        # Create categories
        for cat_data in CATEGORIES:
            cat = db.query(QuestionCategory).filter(QuestionCategory.id == cat_data["id"]).first()
            if not cat:
                print(f"Creating category: {cat_data['title']}")
                cat = QuestionCategory(
                    id=cat_data["id"],
                    title=cat_data["title"],
                    emoji=cat_data["emoji"],
                    backgroundColor=cat_data["backgroundColor"],
                    accentColor=cat_data["accentColor"]
                )
                db.add(cat)
            else:
                print(f"Category exists: {cat_data['title']}")
        db.commit()
        
        # Generate Questions
        for cat_data in CATEGORIES:
            print(f"\n--- Processing Category: {cat_data['title']} ---")
            
            count = db.query(Question).filter(Question.category_id == cat_data["id"]).count()
            target = 60
            needed = target - count
            
            if needed <= 0:
                print("Enough questions.")
                continue
                
            print(f"Generating {needed} more questions...")
            
            existing_qs = db.query(Question.text).filter(Question.category_id == cat_data["id"]).limit(100).all()
            existing_texts = [q[0] for q in existing_qs]
            
            while needed > 0:
                batch_size = min(needed, 10)
                print(f"Requesting batch of {batch_size}...")
                
                try:
                    # Reuse generate_questions from llm_service
                    new_texts = generate_questions(cat_data["prompt"], existing_texts, count=batch_size)
                    
                    added_count = 0
                    for text in new_texts:
                        text_val = str(text).strip()
                        if text_val in existing_texts: continue
                        
                        # DB Check
                        if not db.query(Question).filter(Question.category_id == cat_data["id"], Question.text == text_val).first():
                            q = Question(category_id=cat_data["id"], text=text_val)
                            db.add(q)
                            existing_texts.append(text_val)
                            added_count += 1
                            
                    db.commit()
                    print(f"Added {added_count} questions.")
                    needed -= added_count
                    
                    if added_count == 0:
                        print("No unique questions. Stopping.")
                        break
                        
                except Exception as e:
                    print(f"Error: {e}")
                    break

    finally:
        db.close()

if __name__ == "__main__":
    seed_categories()
