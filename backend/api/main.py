from fastapi import FastAPI, Depends, HTTPException, Header, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Integer, ForeignKey, Float, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from sqlalchemy.sql.expression import func
from datetime import datetime, timedelta, timezone
import os
import uvicorn
import uuid
import random
import string
import json
import asyncio
import httpx
from sse_manager import manager
from s3_client import upload_file_to_s3, get_presigned_url, delete_file_from_s3
from llm_service import generate_questions
import ast


# Database Connection
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:IwVFaHIwQfulvssagcqReUsKLrEZcUcA@shuttle.proxy.rlwy.net:58300/railway"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- Models ---

class DbSession(Base):
    __tablename__ = "session"
    id = Column(String, primary_key=True)
    userId = Column(String)
    token = Column(String)
    expiresAt = Column(DateTime)

class User(Base):
    __tablename__ = "user"
    id = Column(String, primary_key=True)
    name = Column(String)
    email = Column(String)
    image = Column(String)
    emailVerified = Column(Boolean)
    createdAt = Column(DateTime)
    updatedAt = Column(DateTime)
    isAnonymous = Column(Boolean) 

class NearishUser(Base):
    __tablename__ = "nearish_user"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    better_auth_id = Column(String, ForeignKey("user.id"), unique=True)

    # Profile Data (from onboarding)
    display_name = Column(String, nullable=True)
    partner_name = Column(String, nullable=True)
    relationship_date = Column(DateTime, nullable=True)
    goals = Column(Text, nullable=True)  # JSON string array

    # Partner Connection
    partner_id = Column(String, ForeignKey("nearish_user.id"), nullable=True)
    connection_code = Column(String, unique=True, nullable=True)

    # Location Tracking
    lastLatitude = Column(Float, nullable=True)
    lastLongitude = Column(Float, nullable=True)
    lastLocationUpdate = Column(DateTime, nullable=True)

    # Status
    status_emoji = Column(String, nullable=True)
    status_text = Column(String, nullable=True)
    status_updated_at = Column(DateTime, nullable=True)

    # Push Notifications
    push_token = Column(String, nullable=True)

    # Subscription Status
    is_pro = Column(Boolean, default=False)
    is_pro_via_partner = Column(Boolean, default=False)  # True if pro access granted via partner's subscription

    createdAt = Column(DateTime, default=datetime.now(timezone.utc))
    updatedAt = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    # Relationship for accessing the partner object easily
    partner = relationship("NearishUser", remote_side=[id])

class Streak(Base):
    __tablename__ = "streak"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nearish_user_id = Column(String, ForeignKey("nearish_user.id"), unique=True) 
    currentStreak = Column(Integer, default=0)
    lastLoginDate = Column(DateTime)
    createdAt = Column(DateTime, default=datetime.now(timezone.utc))
    updatedAt = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

class Memory(Base):
    __tablename__ = "memory"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    nearish_user_id = Column(String, ForeignKey("nearish_user.id"))
    imagePath = Column(String, nullable=True)
    title = Column(String)
    description = Column(String, nullable=True)
    date = Column(DateTime)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    locationName = Column(String, nullable=True)
    createdAt = Column(DateTime, default=datetime.now(timezone.utc))

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

class CoupleGameSession(Base):
    __tablename__ = "couple_game_sessions"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    game_id = Column(Integer, ForeignKey("games.id"))
    # We store the couple as two user IDs to easily find it later
    user_1_id = Column(String, ForeignKey("nearish_user.id"))
    user_2_id = Column(String, ForeignKey("nearish_user.id"))
    
    is_active = Column(Boolean, default=True)
    
    # We store the list of question IDs for this session as a JSON string (e.g. "['id1', 'id2']")
    # In a more normalized schema we might use a link table, but this is simpler for "Session" scope. 
    question_ids = Column(Text) 
    
    createdAt = Column(DateTime, default=datetime.now(timezone.utc))
    completedAt = Column(DateTime, nullable=True)

class GameAnswer(Base):
    __tablename__ = "game_answers"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("couple_game_sessions.id"))
    question_id = Column(String, ForeignKey("game_questions.id"))
    user_id = Column(String, ForeignKey("nearish_user.id"))
    answer_text = Column(Text)
    createdAt = Column(DateTime, default=datetime.now(timezone.utc))

# --- Question Tab Models ---

class QuestionCategory(Base):
    __tablename__ = "question_categories"
    id = Column(String, primary_key=True) # e.g. 'getting-started'
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

class UserQuestionAnswer(Base):
    __tablename__ = "user_question_answers"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("nearish_user.id"))
    question_id = Column(String, ForeignKey("questions.id"))
    answer_text = Column(Text, nullable=True) # Can be just "read" or actual text
    is_read = Column(Boolean, default=True)
    createdAt = Column(DateTime, default=datetime.now(timezone.utc))

# Create tables
Base.metadata.create_all(bind=engine)

# --- Dependencies ---

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    try:
        scheme, token = authorization.split()
        if scheme.lower() != 'bearer':
            raise HTTPException(status_code=401, detail="Invalid Authorization Scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Authorization Format")

    session_record = db.query(DbSession).filter(DbSession.token == token).first()
    if not session_record:
        raise HTTPException(status_code=401, detail="Invalid Session")
    
    expires_at = session_record.expiresAt
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
        
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session Expired")
        
    user = db.query(User).filter(User.id == session_record.userId).first()
    if not user:
        raise HTTPException(status_code=401, detail="User Not Found")
    return user

# Helper to find/create NearishUser
def get_nearish_user(user: User, db: Session):
    nearish_user = db.query(NearishUser).filter(NearishUser.better_auth_id == user.id).first()
    if not nearish_user:
        nearish_user = NearishUser(better_auth_id=user.id)
        db.add(nearish_user)
        db.commit()
        db.refresh(nearish_user)
    return nearish_user

# Helper to identify couple tuple
def get_couple_ids(nearish_user: NearishUser):
    if not nearish_user.partner_id:
        return None
    ids = sorted([nearish_user.id, nearish_user.partner_id])
    return (ids[0], ids[1])

app = FastAPI()

# --- Endpoints ---

@app.get("/")
def read_root():
    return {"message": "Nearish API is running!"}

@app.get("/api/events")
async def event_stream(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Identify the NearishUser stable ID
    nearish_user = get_nearish_user(user, db)
    user_id = nearish_user.id
    
    queue = await manager.connect(user_id)
    
    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                
                # Wait for data from the queue
                data = await queue.get()
                
                # Format as SSE
                yield f"event: {data['event']}\n"
                yield f"data: {json.dumps(data['data'])}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await manager.disconnect(user_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/user/me")
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    nearish_user = get_nearish_user(user, db)

    # Parse goals from JSON string if exists
    goals = []
    if nearish_user.goals:
        try:
            goals = json.loads(nearish_user.goals)
        except:
            goals = []

    return {
        "id": nearish_user.id,
        "partner_id": nearish_user.partner_id,
        "connection_code": nearish_user.connection_code,
        "better_auth_id": user.id,
        "name": user.name,
        "email": user.email,
        "is_anonymous": user.isAnonymous,
        "is_pro": nearish_user.is_pro,
        "is_pro_via_partner": nearish_user.is_pro_via_partner,
        "status": {
            "emoji": nearish_user.status_emoji,
            "text": nearish_user.status_text,
            "updatedAt": nearish_user.status_updated_at
        },
        "profile": {
            "displayName": nearish_user.display_name,
            "partnerName": nearish_user.partner_name,
            "relationshipDate": nearish_user.relationship_date.isoformat() if nearish_user.relationship_date else None,
            "goals": goals
        }
    }

@app.post("/api/user/onboarding")
def save_onboarding(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Save onboarding data to the user's profile"""
    nearish_user = get_nearish_user(user, db)

    # Extract data from payload
    display_name = payload.get("yourName")
    partner_name = payload.get("partnerName")
    relationship_date_str = payload.get("relationshipDate")
    goals = payload.get("goals", [])

    # Update user profile
    if display_name:
        nearish_user.display_name = display_name
    if partner_name:
        nearish_user.partner_name = partner_name
    if relationship_date_str:
        try:
            # Parse date from MM/DD/YYYY format
            nearish_user.relationship_date = datetime.strptime(relationship_date_str, "%m/%d/%Y").replace(tzinfo=timezone.utc)
        except ValueError:
            # Try ISO format as fallback
            try:
                nearish_user.relationship_date = datetime.fromisoformat(relationship_date_str.replace('Z', '+00:00'))
            except:
                pass
    if goals:
        nearish_user.goals = json.dumps(goals)

    db.commit()

    return {
        "success": True,
        "data": {
            "displayName": nearish_user.display_name,
            "partnerName": nearish_user.partner_name,
            "relationshipDate": nearish_user.relationship_date.isoformat() if nearish_user.relationship_date else None,
            "goals": goals
        }
    }

@app.put("/api/user/profile")
def update_profile(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update user profile data"""
    nearish_user = get_nearish_user(user, db)

    print("hello")

    # Update fields if provided
    if "displayName" in payload:
        nearish_user.display_name = payload["displayName"]
    if "partnerName" in payload:
        nearish_user.partner_name = payload["partnerName"]
    if "relationshipDate" in payload:
        date_str = payload["relationshipDate"]
        if date_str:
            try:
                # Try ISO format first
                nearish_user.relationship_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            except ValueError:
                # Try MM/DD/YYYY format
                try:
                    nearish_user.relationship_date = datetime.strptime(date_str, "%m/%d/%Y").replace(tzinfo=timezone.utc)
                except:
                    pass
        else:
            nearish_user.relationship_date = None
    if "goals" in payload:
        nearish_user.goals = json.dumps(payload["goals"]) if payload["goals"] else None

    db.commit()

    # Parse goals for response
    goals = []
    if nearish_user.goals:
        try:
            goals = json.loads(nearish_user.goals)
        except:
            goals = []

    return {
        "success": True,
        "data": {
            "displayName": nearish_user.display_name,
            "partnerName": nearish_user.partner_name,
            "relationshipDate": nearish_user.relationship_date.isoformat() if nearish_user.relationship_date else None,
            "goals": goals
        }
    }

@app.post("/api/status")
async def update_status(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    nearish_user = get_nearish_user(user, db)
    
    emoji = payload.get("emoji")
    text_status = payload.get("text")
    
    nearish_user.status_emoji = emoji
    nearish_user.status_text = text_status
    nearish_user.status_updated_at = datetime.now(timezone.utc)
    
    db.commit()
    
    # Notify partner
    if nearish_user.partner_id:
        await manager.send_event(nearish_user.partner_id, "partner_status_update", {
            "emoji": emoji,
            "text": text_status,
            "updatedAt": nearish_user.status_updated_at.isoformat()
        })
        
    return {"success": True}

@app.get("/api/status/partner")
def get_partner_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_nearish_user(user, db)
    
    if not me.partner_id:
        return {"success": False, "message": "No partner connected"}
        
    partner = db.query(NearishUser).filter(NearishUser.id == me.partner_id).first()
    
    if not partner:
        return {"success": False, "message": "Partner not found"}

    # Calculate distance info here too, to keep it centralized for the UI
    distance_str = None
    dist_miles = None
    
    if me.lastLatitude is not None and me.lastLongitude is not None and \
       partner.lastLatitude is not None and partner.lastLongitude is not None:
        
        dist_miles = haversine(me.lastLatitude, me.lastLongitude, partner.lastLatitude, partner.lastLongitude)
        dist_miles = round(dist_miles, 2)
        
        if dist_miles < 0.5:
            distance_str = "With You ❤️"
        elif dist_miles < 5:
            distance_str = "Nearby"
        else:
            distance_str = f"{dist_miles} miles away"

    return {"success": True, "data": {
        "emoji": partner.status_emoji,
        "text": partner.status_text,
        "updatedAt": partner.status_updated_at,
        "location": {
            "distanceStr": distance_str,
            "distanceMiles": dist_miles,
            "lastUpdated": partner.lastLocationUpdate
        }
    }}

@app.post("/api/partner/code")
def generate_code(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    nearish_user = get_nearish_user(user, db)
    
    if nearish_user.partner_id:
        raise HTTPException(status_code=400, detail="Already connected to a partner")
    
    if nearish_user.connection_code:
        return {"code": nearish_user.connection_code}
    
    # Generate unique 6-char code
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        # Check uniqueness
        if not db.query(NearishUser).filter(NearishUser.connection_code == code).first():
            nearish_user.connection_code = code
            db.commit()
            return {"code": code}

@app.post("/api/partner/connect")
async def connect_partner(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    code = payload.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Code is required")
        
    me = get_nearish_user(user, db)
    
    if me.partner_id:
        raise HTTPException(status_code=400, detail="You already have a partner")
        
    partner = db.query(NearishUser).filter(NearishUser.connection_code == code).first()
    
    if not partner:
        raise HTTPException(status_code=404, detail="Invalid connection code")
        
    if partner.id == me.id:
        raise HTTPException(status_code=400, detail="You cannot connect with yourself")
        
    if partner.partner_id:
        raise HTTPException(status_code=400, detail="This user is already connected to someone else")
        
    # Connect both ways
    me.partner_id = partner.id
    partner.partner_id = me.id
    
    # Clear codes
    me.connection_code = None
    partner.connection_code = None
    
    db.commit()
    
    # Send Real-Time Event to Partner
    await manager.send_event(partner.id, "partner_connected", {
        "message": f"{user.name or 'Your partner'} has connected with you!",
        "partner_name": user.name
    })
    
    return {"message": "Successfully connected!", "partner_id": partner.id}

@app.post("/api/partner/nudge")
async def send_nudge(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_nearish_user(user, db)
    
    if not me.partner_id:
        raise HTTPException(status_code=400, detail="No partner connected")
        
    # Send Nudge Event
    await manager.send_event(me.partner_id, "nudge", {
        "message": f"{user.name or 'Your partner'} is thinking of you! ❤️",
        "sender_name": user.name
    })
    
    return {"success": True, "message": "Nudge sent"}

@app.post("/api/partner/disconnect")
async def disconnect_partner(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_nearish_user(user, db)
    
    if not me.partner_id:
        raise HTTPException(status_code=400, detail="No partner connected")
        
    partner = db.query(NearishUser).filter(NearishUser.id == me.partner_id).first()
    
    if partner:
        # Notify partner about disconnection
        await manager.send_event(partner.id, "partner_disconnected", {
            "message": f"{user.name or 'Your partner'} has disconnected."
        })
        partner.partner_id = None
    
    me.partner_id = None
    db.commit()
    
    return {"success": True, "message": "Disconnected from partner"}

@app.post("/api/streak/check-in")
def check_in_streak(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    nearish_user = get_nearish_user(user, db)

    streak = db.query(Streak).filter(Streak.nearish_user_id == nearish_user.id).first()
    now = datetime.now(timezone.utc)
    
    if not streak:
        streak = Streak(nearish_user_id=nearish_user.id, currentStreak=1, lastLoginDate=now)
        db.add(streak)
        db.commit()
        return {"currentStreak": 1, "message": "Streak started!"}
    
    last_date = streak.lastLoginDate
    if last_date.tzinfo is None:
        last_date = last_date.replace(tzinfo=timezone.utc)
        
    if last_date.date() == now.date():
        return {"currentStreak": streak.currentStreak, "message": "Already checked in today"}
    
    if last_date.date() == (now - timedelta(days=1)).date():
        streak.currentStreak += 1
        streak.lastLoginDate = now
        db.commit()
        return {"currentStreak": streak.currentStreak, "message": "Streak increased!"}
    
    streak.currentStreak = 1
    streak.lastLoginDate = now
    db.commit()
    return {"currentStreak": 1, "message": "Streak reset."}

@app.post("/api/memories")
async def add_memory(
    title: str = Form(...),
    description: str = Form(None),
    date: str = Form(...),
    latitude: float = Form(None),
    longitude: float = Form(None),
    locationName: str = Form(None),
    image: UploadFile = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    nearish_user = get_nearish_user(user, db)

    # Block non-pro users from creating memories
    if not nearish_user.is_pro:
        raise HTTPException(status_code=403, detail="Memories require Nearish Unlimited")
    
    image_path = None
    if image:
        file_extension = image.filename.split('.')[-1]
        object_name = f"{nearish_user.id}/{uuid.uuid4()}.{file_extension}"
        image_path = upload_file_to_s3(image.file, object_name)
        
    new_memory = Memory(
        nearish_user_id=nearish_user.id,
        title=title,
        description=description,
        date=datetime.fromisoformat(date.replace('Z', '+00:00')),
        imagePath=image_path,
        latitude=latitude,
        longitude=longitude,
        locationName=locationName
    )
    
    db.add(new_memory)
    db.commit()
    db.refresh(new_memory)
    
    response_data = {
        "id": new_memory.id,
        "title": new_memory.title,
        "description": new_memory.description,
        "date": new_memory.date,
        "locationName": new_memory.locationName,
        "latitude": new_memory.latitude,
        "longitude": new_memory.longitude,
        "imageUrl": get_presigned_url(new_memory.imagePath) if new_memory.imagePath else None,
        "authorName": user.name or "Me"
    }
    
    return {"success": True, "data": response_data}

@app.put("/api/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    title: str = Form(None),
    description: str = Form(None),
    date: str = Form(None),
    latitude: float = Form(None),
    longitude: float = Form(None),
    locationName: str = Form(None),
    image: UploadFile = File(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    nearish_user = get_nearish_user(user, db)
    
    # Find existing memory
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
        
    if memory.nearish_user_id != nearish_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to edit this memory")
        
    # Update fields if provided
    if title is not None:
        memory.title = title
    if description is not None:
        memory.description = description
    if date is not None:
        memory.date = datetime.fromisoformat(date.replace('Z', '+00:00'))
    if latitude is not None:
        memory.latitude = latitude
    if longitude is not None:
        memory.longitude = longitude
    if locationName is not None:
        memory.locationName = locationName
        
    # Handle Image Update
    if image:
        file_extension = image.filename.split('.')[-1]
        object_name = f"{nearish_user.id}/{uuid.uuid4()}.{file_extension}"
        image_path = upload_file_to_s3(image.file, object_name)
        
        # Delete old image if exists
        if memory.imagePath:
            delete_file_from_s3(memory.imagePath)
            
        memory.imagePath = image_path
        
    db.commit()
    db.refresh(memory)
    
    return {"success": True, "data": {
        "id": memory.id,
        "title": memory.title,
        "description": memory.description,
        "date": memory.date,
        "locationName": memory.locationName,
        "latitude": memory.latitude,
        "longitude": memory.longitude,
        "imageUrl": get_presigned_url(memory.imagePath) if memory.imagePath else None,
        "authorName": user.name or "Me",
        "isMine": True
    }}

@app.delete("/api/memories/{memory_id}")
def delete_memory(
    memory_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    nearish_user = get_nearish_user(user, db)
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
        
    if memory.nearish_user_id != nearish_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this memory")
    
    # Delete from S3 if exists
    if memory.imagePath:
        delete_file_from_s3(memory.imagePath)
        
    db.delete(memory)
    db.commit()
    
    return {"success": True, "message": "Memory deleted"}

import math

def haversine(lat1, lon1, lat2, lon2):
    # Radius of Earth in miles
    R = 3958.8 
    
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c

# ... (Existing endpoints)

@app.post("/api/location/update")
def update_location(
    data: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    nearish_user = get_nearish_user(user, db)
    latitude = data.get("latitude")
    longitude = data.get("longitude")
    
    if latitude is not None and longitude is not None:
        nearish_user.lastLatitude = latitude
        nearish_user.lastLongitude = longitude
        nearish_user.lastLocationUpdate = datetime.now(timezone.utc)
        db.commit()
    
    return {"success": True}

@app.get("/api/location/partner")
def get_partner_location(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_nearish_user(user, db)
    
    if not me.partner_id:
        return {"success": False, "message": "No partner connected"}
        
    partner = db.query(NearishUser).filter(NearishUser.id == me.partner_id).first()
    
    if not partner or partner.lastLatitude is None or partner.lastLongitude is None:
        return {"success": True, "data": None, "message": "Partner location unavailable"}
    
    distance = None
    status = "Unknown"
    
    if me.lastLatitude is not None and me.lastLongitude is not None:
        dist_miles = haversine(me.lastLatitude, me.lastLongitude, partner.lastLatitude, partner.lastLongitude)
        distance = round(dist_miles, 2)
        
        if dist_miles < 0.5:
            status = "With You ❤️"
        elif dist_miles < 5:
            status = "Nearby"
        else:
            status = f"{distance} miles away"
            
    # Check if location is stale (> 1 hour old)
    is_stale = False
    if partner.lastLocationUpdate:
        if (datetime.now(timezone.utc) - partner.lastLocationUpdate.replace(tzinfo=timezone.utc)) > timedelta(hours=1):
            is_stale = True
            status = f"Last seen {status}"

    return {"success": True, "data": {
        "latitude": partner.lastLatitude,
        "longitude": partner.lastLongitude,
        "updatedAt": partner.lastLocationUpdate,
        "distanceMiles": distance,
        "status": status,
        "isStale": is_stale
    }}

@app.get("/api/memories")
def get_memories(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    nearish_user = get_nearish_user(user, db)

    # Return empty for non-pro users with message
    if not nearish_user.is_pro:
        return {"success": True, "data": [], "is_pro": False, "message": "Upgrade to Nearish Unlimited to access memories"}

    user_ids = [nearish_user.id]
    if nearish_user.partner_id:
        user_ids.append(nearish_user.partner_id)
        
    query = db.query(Memory, User.name).outerjoin(
        NearishUser, Memory.nearish_user_id == NearishUser.id
    ).outerjoin(
        User, NearishUser.better_auth_id == User.id
    ).filter(Memory.nearish_user_id.in_(user_ids)).order_by(Memory.date.desc())
    
    memories_with_names = query.all()
    
    results = []
    for m, author_name in memories_with_names:
        results.append({
            "id": m.id,
            "title": m.title,
            "description": m.description,
            "date": m.date,
            "locationName": m.locationName,
            "latitude": m.latitude,
            "longitude": m.longitude,
            "imageUrl": get_presigned_url(m.imagePath) if m.imagePath else None,
            "authorName": author_name or "Partner",
            "isMine": m.nearish_user_id == nearish_user.id
        })
    
    return {"success": True, "data": results}

@app.get("/api/games")
def get_games(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    games = db.query(Games).all()
    return {"success": True, "data": [{"id": g.id, "name": g.name} for g in games]}

@app.post("/api/games/{game_id}/start")
def start_game(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    me = get_nearish_user(user, db)
    
    if not me.partner_id:
        raise HTTPException(status_code=400, detail="Partner connection required")
    
    couple_ids = get_couple_ids(me) # (user1, user2) sorted
    if not couple_ids:
        raise HTTPException(status_code=400, detail="Partner connection required")
        
    # 1. Check for active session
    session = db.query(CoupleGameSession).filter(
        CoupleGameSession.game_id == game_id,
        CoupleGameSession.user_1_id == couple_ids[0],
        CoupleGameSession.user_2_id == couple_ids[1],
        CoupleGameSession.is_active == True
    ).first()
    
    questions = []
    
    if session:
        # Session exists, fetch questions
        q_ids = json.loads(session.question_ids)
        questions = db.query(GameQuestion).filter(GameQuestion.id.in_(q_ids)).all()
    else:
        # 2. No active session. Check question pool.
        # Find questions NOT answered by this couple
        # For now, let's just find questions not in previous sessions?
        # Simpler: Get all questions for this game.
        # Filter out questions that are in any PAST completed sessions for this couple.
        
        # Get all question IDs used in past sessions
        past_sessions = db.query(CoupleGameSession).filter(
            CoupleGameSession.game_id == game_id,
            CoupleGameSession.user_1_id == couple_ids[0],
            CoupleGameSession.user_2_id == couple_ids[1]
        ).all()
        
        used_q_ids = set()
        for s in past_sessions:
            try:
                ids = json.loads(s.question_ids)
                used_q_ids.update(ids)
            except:
                pass
        
        # Get potential questions
        # We limit to finding 10 unused ones.
        
        all_questions_query = db.query(GameQuestion).filter(GameQuestion.game_id == game_id)
        # SQLAlchemy doesn't have a clean "NOT IN JSON" easily without native JSON types,
        # but we can fetch candidates and filter in python if the pool isn't massive.
        # Assuming the pool is < 1000 for now.
        
        all_candidates = all_questions_query.all()
        candidates = [q for q in all_candidates if q.id not in used_q_ids]
        
        if len(candidates) < 10:
            # 3. Call LLM to generate more
            game = db.query(Games).filter(Games.id == game_id).first()
            if not game:
                raise HTTPException(status_code=404, detail="Game not found")
                
            if game.system_prompt:
                # Generate new questions
                new_items = generate_questions(game.system_prompt, [q.question_text for q in candidates])
                
                new_questions = []
                for item in new_items:
                    # Ensure we store a string
                    if isinstance(item, (dict, list)):
                        text_val = json.dumps(item)
                    else:
                        text_val = str(item)
                        
                    # Check dupe text locally to be safe
                    if not db.query(GameQuestion).filter(GameQuestion.game_id == game_id, GameQuestion.question_text == text_val).first():
                        nq = GameQuestion(game_id=game_id, question_text=text_val)
                        db.add(nq)
                        new_questions.append(nq)
                
                db.commit()
                # Refresh candidates
                candidates.extend(new_questions)
        
        # 4. Select 10 questions (or fewer if we still don't have enough)
        selected_questions = random.sample(candidates, min(len(candidates), 10))
        selected_ids = [q.id for q in selected_questions]
        
        # 5. Create Session
        new_session = CoupleGameSession(
            game_id=game_id,
            user_1_id=couple_ids[0],
            user_2_id=couple_ids[1],
            question_ids=json.dumps(selected_ids),
            is_active=True
        )
        db.add(new_session)
        db.commit()
        db.refresh(new_session)
        
        session = new_session
        questions = selected_questions

    # 6. Fetch answers for this session (for both users)
    answers = db.query(GameAnswer).filter(GameAnswer.session_id == session.id).all()
    
    # Format Response
    # If BOTH have answered a question, we reveal both answers.
    # If ONLY ONE has answered, we show that they have answered but hide the text (or show own text).
    
    # Map q_id -> {user1_ans: ..., user2_ans: ...}
    ans_map = {}
    for a in answers:
        if a.question_id not in ans_map:
            ans_map[a.question_id] = {}
        ans_map[a.question_id][a.user_id] = a.answer_text

    result_questions = []
    for q in questions:
        q_answers = ans_map.get(q.id, {})
        my_ans = q_answers.get(me.id)
        partner_ans = q_answers.get(me.partner_id)
        
        # Reveal logic: Both must answer to see partner's answer
        show_partner = (my_ans is not None) and (partner_ans is not None)
        
        result_questions.append({
            "id": q.id,
            "text": q.question_text,
            "myAnswer": my_ans,
            "partnerAnswer": partner_ans if show_partner else None,
            "partnerHasAnswered": partner_ans is not None
        })
        
    return {
        "success": True,
        "sessionId": session.id,
        "questions": result_questions
    }

@app.post("/api/games/{game_id}/answer")
async def answer_question(
    game_id: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    me = get_nearish_user(user, db)
    
    session_id = payload.get("sessionId")
    question_id = payload.get("questionId")
    answer_text = payload.get("answer")
    
    if not session_id or not question_id or not answer_text:
        raise HTTPException(status_code=400, detail="Missing fields")
        
    session = db.query(CoupleGameSession).filter(CoupleGameSession.id == session_id).first()
    if not session or not session.is_active:
        raise HTTPException(status_code=400, detail="Invalid session")
        
    # Check if answer exists
    existing = db.query(GameAnswer).filter(
        GameAnswer.session_id == session_id,
        GameAnswer.question_id == question_id,
        GameAnswer.user_id == me.id
    ).first()
    
    if existing:
        existing.answer_text = answer_text
    else:
        new_ans = GameAnswer(
            session_id=session_id,
            question_id=question_id,
            user_id=me.id,
            answer_text=answer_text
        )
        db.add(new_ans)
    
    db.commit()
    
    # Check if this completes the question (both answered)
    partner_ans = db.query(GameAnswer).filter(
        GameAnswer.session_id == session_id,
        GameAnswer.question_id == question_id,
        GameAnswer.user_id == me.partner_id
    ).first()
    
    if partner_ans:
        # Notify Partner that I answered (and now it's revealed!)
        await manager.send_event(me.partner_id, "game_update", {
            "gameId": game_id,
            "type": "reveal",
            "questionId": question_id,
            "partnerAnswer": answer_text # They can see it now
        })
    else:
         # Notify Partner that I answered (but hidden)
        await manager.send_event(me.partner_id, "game_update", {
            "gameId": game_id,
            "type": "answered",
            "questionId": question_id
        })
    
    return {"success": True}

@app.post("/api/games/{game_id}/restart")
def restart_game(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    me = get_nearish_user(user, db)
    
    if not me.partner_id:
        raise HTTPException(status_code=400, detail="Partner connection required")
    
    couple_ids = get_couple_ids(me)
    if not couple_ids:
        raise HTTPException(status_code=400, detail="Partner connection required")
        
    # Find active session
    session = db.query(CoupleGameSession).filter(
        CoupleGameSession.game_id == game_id,
        CoupleGameSession.user_1_id == couple_ids[0],
        CoupleGameSession.user_2_id == couple_ids[1],
        CoupleGameSession.is_active == True
    ).first()
    
    if session:
        session.is_active = False
        session.completedAt = datetime.now(timezone.utc)
        db.commit()
        
    # We don't create a new one immediately; the next /start call will do that.
    return {"success": True, "message": "Session closed. Ready for new game."}

    
    return {"success": True}

# --- Questions Feature Endpoints ---

@app.get("/api/questions/categories")
def get_question_categories(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_nearish_user(user, db)
    categories = db.query(QuestionCategory).all()
    
    data = []
    for cat in categories:
        total = db.query(Question).filter(Question.category_id == cat.id).count()
        
        # Count answered by me
        answered = db.query(UserQuestionAnswer).join(Question).filter(
            UserQuestionAnswer.user_id == me.id,
            Question.category_id == cat.id
        ).count()
        
        progress = (answered / total * 100) if total > 0 else 0
        
        data.append({
            "id": cat.id,
            "title": cat.title,
            "emoji": cat.emoji,
            "backgroundColor": cat.backgroundColor,
            "accentColor": cat.accentColor,
            "questionCount": total,
            "progress": progress
        })
        
    return {"success": True, "data": data}

@app.get("/api/questions/categories/{category_id}/questions")
def get_questions_by_category(category_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_nearish_user(user, db)
    partner_id = me.partner_id

    questions = db.query(Question).filter(Question.category_id == category_id).all()

    # Limit to 10 questions for non-pro users
    FREE_QUESTION_LIMIT = 10
    total_questions = len(questions)
    is_limited = not me.is_pro and total_questions > FREE_QUESTION_LIMIT

    if is_limited:
        questions = questions[:FREE_QUESTION_LIMIT]

    question_ids = [q.id for q in questions]

    # My answers
    my_answers = db.query(UserQuestionAnswer).filter(
        UserQuestionAnswer.user_id == me.id,
        UserQuestionAnswer.question_id.in_(question_ids)
    ).all()
    my_ans_map = {a.question_id: a.answer_text for a in my_answers}

    # Partner answers
    partner_ans_map = {}
    if partner_id:
        p_answers = db.query(UserQuestionAnswer).filter(
            UserQuestionAnswer.user_id == partner_id,
            UserQuestionAnswer.question_id.in_(question_ids)
        ).all()
        partner_ans_map = {a.question_id: a.answer_text for a in p_answers}

    results = []
    for q in questions:
        my_ans = my_ans_map.get(q.id)
        p_ans = partner_ans_map.get(q.id)

        show_partner = (my_ans is not None) and (p_ans is not None)

        results.append({
            "id": q.id,
            "text": q.text,
            "isAnswered": my_ans is not None,
            "myAnswer": my_ans,
            "partnerAnswer": p_ans if show_partner else None,
            "partnerHasAnswered": p_ans is not None
        })

    return {
        "success": True,
        "data": results,
        "is_limited": is_limited,
        "total_questions": total_questions,
        "limit": FREE_QUESTION_LIMIT if is_limited else None
    }

@app.post("/api/questions/{question_id}/answer")
def answer_question_card(question_id: str, payload: dict = {}, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    me = get_nearish_user(user, db)

    # Check if already answered
    existing = db.query(UserQuestionAnswer).filter(
        UserQuestionAnswer.user_id == me.id,
        UserQuestionAnswer.question_id == question_id
    ).first()

    if not existing:
        ans = UserQuestionAnswer(
            user_id=me.id,
            question_id=question_id,
            answer_text=payload.get("answer"),
            is_read=True
        )
        db.add(ans)
        db.commit()

    return {"success": True}

@app.get("/api/questions/daily")
def get_daily_question(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Returns the daily question for the couple.
    The question is deterministic based on the current date so both partners get the same question.
    """
    me = get_nearish_user(user, db)
    partner_id = me.partner_id

    # Get total count of questions to cycle through
    total_questions = db.query(Question).count()

    if total_questions == 0:
        return {"success": False, "message": "No questions available"}

    # Use the day of year to deterministically select a question
    # This ensures both partners get the same question on the same day
    today = datetime.now(timezone.utc).date()
    day_of_year = today.timetuple().tm_yday

    # Get all question IDs and sort them for consistency
    all_questions = db.query(Question).order_by(Question.id).all()
    question_index = day_of_year % len(all_questions)
    daily_question = all_questions[question_index]

    # Get category info for the question
    category = db.query(QuestionCategory).filter(QuestionCategory.id == daily_question.category_id).first()

    # Check if user has answered this question
    my_answer = db.query(UserQuestionAnswer).filter(
        UserQuestionAnswer.user_id == me.id,
        UserQuestionAnswer.question_id == daily_question.id
    ).first()

    # Check if partner has answered this question
    partner_answer = None
    if partner_id:
        partner_answer = db.query(UserQuestionAnswer).filter(
            UserQuestionAnswer.user_id == partner_id,
            UserQuestionAnswer.question_id == daily_question.id
        ).first()

    # Only reveal partner's answer if both have answered
    show_partner = (my_answer is not None) and (partner_answer is not None)

    return {
        "success": True,
        "data": {
            "id": daily_question.id,
            "text": daily_question.text,
            "category": {
                "id": category.id if category else None,
                "title": category.title if category else None,
                "emoji": category.emoji if category else None,
                "backgroundColor": category.backgroundColor if category else None,
                "accentColor": category.accentColor if category else None,
            } if category else None,
            "isAnswered": my_answer is not None,
            "myAnswer": my_answer.answer_text if my_answer else None,
            "partnerAnswer": partner_answer.answer_text if show_partner else None,
            "partnerHasAnswered": partner_answer is not None
        }
    }

# ==================== PUSH NOTIFICATIONS ====================

async def send_expo_push_notification(push_tokens: list, title: str, body: str, data: dict = None):
    """Send push notification via Expo's push notification service"""
    if not push_tokens:
        return {"success": False, "message": "No push tokens provided"}

    messages = []
    for token in push_tokens:
        if token and token.startswith("ExponentPushToken"):
            messages.append({
                "to": token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": data or {}
            })

    if not messages:
        return {"success": False, "message": "No valid Expo push tokens"}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://exp.host/--/api/v2/push/send",
                json=messages,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            )
            result = response.json()
            return {"success": True, "result": result, "sent_count": len(messages)}
        except Exception as e:
            return {"success": False, "error": str(e)}

@app.post("/api/push-token")
def register_push_token(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Register or update push token for the current user"""
    nearish_user = get_nearish_user(user, db)
    token = payload.get("token")

    if not token:
        raise HTTPException(status_code=400, detail="Token is required")

    nearish_user.push_token = token
    db.commit()

    return {"success": True, "message": "Push token registered"}

@app.post("/api/user/subscription")
def update_subscription_status(payload: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Update user's subscription status (synced from RevenueCat)

    When a user subscribes, their partner automatically gets pro access too.
    """
    nearish_user = get_nearish_user(user, db)
    client_has_sub = payload.get("isPro", False)

    # Check if partner has a valid subscription that can be shared
    partner_has_sharable_sub = False
    partner = None
    if nearish_user.partner_id:
        partner = db.query(NearishUser).filter(NearishUser.id == nearish_user.partner_id).first()
        if partner and partner.is_pro and not partner.is_pro_via_partner:
            partner_has_sharable_sub = True

    # Determine final status for THIS user
    final_is_pro = client_has_sub or partner_has_sharable_sub
    final_is_via_partner = (not client_has_sub) and partner_has_sharable_sub

    # Update this user
    nearish_user.is_pro = final_is_pro
    nearish_user.is_pro_via_partner = final_is_via_partner
    
    print(f"User {nearish_user.id} subscription update: Own={client_has_sub}, Partner={partner_has_sharable_sub} -> Final={final_is_pro}")

    # Now handle the PARTNER's status
    # Case A: This user HAS a sub (client_has_sub=True). We must ensure partner gets it.
    if client_has_sub and partner:
        if not partner.is_pro:
            partner.is_pro = True
            partner.is_pro_via_partner = True
            print(f"Granted pro access to partner {partner.id}")
        elif partner.is_pro and not partner.is_pro_via_partner:
             # Partner has their own sub, so we don't change anything about them
             pass
        elif partner.is_pro and partner.is_pro_via_partner:
             # Partner already has it via partner (us), keep it that way
             pass

    # Case B: This user does NOT have a sub (client_has_sub=False).
    # We need to ensure we aren't incorrectly keeping the partner as "Pro via Partner" if we just lost our sub.
    # Note: If we lost our sub, but we are now "Pro via Partner" (because they have one), 
    # then THEY must have their own sub, so they are fine.
    # The only tricky case is if BOTH lose it at the same time? No, requests are separate.
    # We only need to revoke partner if:
    # 1. We don't have a sub.
    # 2. Partner is "Pro via Partner" (meaning they relied on us).
    if not client_has_sub and partner:
        if partner.is_pro_via_partner:
            # Re-evaluate partner.
            # Does partner have a source of Pro?
            # They don't have their own (is_pro_via_partner is True).
            # We don't have our own (client_has_sub is False).
            # So they should lose it.
            partner.is_pro = False
            partner.is_pro_via_partner = False
            print(f"Revoked pro access from partner {partner.id}")

    db.commit()

    return {
        "success": True,
        "is_pro": nearish_user.is_pro
    }

@app.post("/api/admin/notify/user/{user_id}")
async def send_notification_to_user(
    user_id: str,
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send notification to a specific user"""
    title = payload.get("title", "Nearish")
    body = payload.get("body", "")
    data = payload.get("data", {})

    if not body:
        raise HTTPException(status_code=400, detail="Body is required")

    # Find user by ID
    target_user = db.query(NearishUser).filter(NearishUser.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    if not target_user.push_token:
        raise HTTPException(status_code=400, detail="User has no push token registered")

    result = await send_expo_push_notification([target_user.push_token], title, body, data)
    return result

@app.post("/api/admin/notify/all")
async def send_notification_to_all(
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Send notification to all users with push tokens"""
    title = payload.get("title", "Nearish")
    body = payload.get("body", "")
    data = payload.get("data", {})

    if not body:
        raise HTTPException(status_code=400, detail="Body is required")

    # Get all users with push tokens
    users = db.query(NearishUser).filter(NearishUser.push_token.isnot(None)).all()
    tokens = [u.push_token for u in users if u.push_token]

    if not tokens:
        return {"success": False, "message": "No users with push tokens found"}

    result = await send_expo_push_notification(tokens, title, body, data)
    result["total_users"] = len(tokens)
    return result

@app.get("/api/admin/users")
def get_all_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get all users"""
    users = db.query(NearishUser).all()
    return {
        "success": True,
        "data": [
            {
                "id": u.id,
                "display_name": u.display_name,
                "partner_name": u.partner_name,
                "has_push_token": u.push_token is not None,
                "has_partner": u.partner_id is not None,
                "created_at": u.createdAt.isoformat() if u.createdAt else None
            }
            for u in users
        ]
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
