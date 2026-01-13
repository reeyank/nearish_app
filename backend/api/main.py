from fastapi import FastAPI, Depends, HTTPException, Header, Request, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Integer, ForeignKey, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime, timedelta, timezone
import os
import uvicorn
import uuid
import random
import string
import json
import asyncio
from sse_manager import manager
from s3_client import upload_file_to_s3, get_presigned_url, delete_file_from_s3

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
    return {
        "id": nearish_user.id,
        "partner_id": nearish_user.partner_id,
        "connection_code": nearish_user.connection_code,
        "better_auth_id": user.id,
        "name": user.name,
        "email": user.email,
        "is_anonymous": user.isAnonymous,
        "status": {
            "emoji": nearish_user.status_emoji,
            "text": nearish_user.status_text,
            "updatedAt": nearish_user.status_updated_at
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
    query = db.query()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)