from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import httpx
import os
from dotenv import load_dotenv
from jose import jwt
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

load_dotenv()

app = FastAPI(title="ReelVid API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB
MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("DB_NAME", "reelvid")
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-this")

if not MONGO_URL:
    raise Exception("MONGO_URL không được để trống")

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]
users_collection = db["users"]
videos_collection = db["videos"]
notifications_collection = db["notifications"]
friends_collection = db["friends"]
messages_collection = db["messages"]

# ==================== MODELS ====================

class GoogleTokenRequest(BaseModel):
    token: str

class VideoCreate(BaseModel):
    title: str
    channel: str
    video_url: str
    thumbnail: Optional[str] = None

class NotificationCreate(BaseModel):
    user_id: str
    type: str
    from_user: str
    from_avatar: str
    content: Optional[str] = None

class FriendCreate(BaseModel):
    user_id: str
    friend_id: str
    friend_name: str
    friend_avatar: str

class MessageCreate(BaseModel):
    sender_id: str
    receiver_id: str
    content: str

# ==================== API ====================

@app.get("/")
async def root():
    return {
        "message": "ReelVid API đang chạy!",
        "status": "online",
        "version": "1.0.0"
    }

@app.get("/api/health")
async def health_check():
    # Kiểm tra kết nối MongoDB
    try:
        await client.admin.command('ping')
        return {"status": "healthy", "database": "connected"}
    except:
        return {"status": "unhealthy", "database": "disconnected"}

# ==================== AUTH ====================

@app.post("/api/auth/google")
async def google_login(request: GoogleTokenRequest):
    """Đăng nhập với Google - KHÔNG CÓ DATA FAKE"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": request.token}
            )
        
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Token không hợp lệ")
        
        user_info = response.json()
        
        if not user_info.get("email_verified"):
            raise HTTPException(status_code=400, detail="Email chưa được xác thực")
        
        email = user_info["email"]
        name = user_info.get("name", email.split("@")[0])
        avatar = user_info.get("picture", "")
        
        # Kiểm tra user đã tồn tại
        existing_user = await users_collection.find_one({"email": email})
        
        if existing_user:
            # Cập nhật thông tin
            await users_collection.update_one(
                {"email": email},
                {"$set": {
                    "name": name,
                    "avatar": avatar,
                    "last_login": datetime.now()
                }}
            )
            user_data = {
                "id": str(existing_user["_id"]),
                "email": existing_user["email"],
                "name": existing_user.get("name", name),
                "avatar": existing_user.get("avatar", avatar),
                "created_at": existing_user.get("created_at")
            }
        else:
            # Tạo user mới
            new_user = {
                "email": email,
                "name": name,
                "avatar": avatar,
                "created_at": datetime.now(),
                "last_login": datetime.now()
            }
            result = await users_collection.insert_one(new_user)
            user_data = {
                "id": str(result.inserted_id),
                "email": email,
                "name": name,
                "avatar": avatar,
                "created_at": new_user["created_at"]
            }
        
        # Tạo JWT token
        token = jwt.encode(
            {"user_id": user_data["id"], "email": email, "exp": datetime.now() + timedelta(days=7)},
            SECRET_KEY,
            algorithm="HS256"
        )
        
        return {
            "status": "success",
            "message": "Đăng nhập thành công",
            "user": user_data,
            "token": token
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/auth/me")
async def get_current_user(request: Request):
    """Lấy thông tin user hiện tại"""
    token = request.headers.get("Authorization")
    if not token:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    
    try:
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id")
        
        user = await users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            raise HTTPException(status_code=404, detail="User không tồn tại")
        
        return {
            "status": "success",
            "user": {
                "id": str(user["_id"]),
                "email": user["email"],
                "name": user["name"],
                "avatar": user.get("avatar", ""),
                "created_at": user.get("created_at")
            }
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Token không hợp lệ")

# ==================== USERS ====================

@app.get("/api/users")
async def get_all_users():
    """Lấy danh sách tất cả users - KHÔNG CÓ DATA FAKE"""
    users = []
    async for user in users_collection.find():
        users.append({
            "id": str(user["_id"]),
            "email": user["email"],
            "name": user["name"],
            "avatar": user.get("avatar", ""),
            "created_at": user.get("created_at")
        })
    return {"status": "success", "users": users}

@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    """Lấy thông tin user theo ID"""
    user = await users_collection.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User không tồn tại")
    
    return {
        "status": "success",
        "user": {
            "id": str(user["_id"]),
            "email": user["email"],
            "name": user["name"],
            "avatar": user.get("avatar", ""),
            "created_at": user.get("created_at")
        }
    }

# ==================== VIDEOS ====================

@app.get("/api/videos")
async def get_videos():
    """Lấy danh sách video - KHÔNG CÓ DATA FAKE"""
    videos = []
    async for video in videos_collection.find().sort("created_at", -1).limit(20):
        videos.append({
            "id": str(video["_id"]),
            "title": video["title"],
            "channel": video["channel"],
            "views": video.get("views", 0),
            "time": video.get("time", "Vừa đăng"),
            "avatar": video.get("avatar", ""),
            "thumbnail": video.get("thumbnail", ""),
            "video_url": video.get("video_url", "")
        })
    return {"status": "success", "videos": videos}

@app.post("/api/videos")
async def create_video(video: VideoCreate, request: Request):
    """Tạo video mới - KHÔNG CÓ DATA FAKE"""
    # Lấy user_id từ token
    token = request.headers.get("Authorization")
    if not token:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    
    try:
        token = token.replace("Bearer ", "")
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id")
        
        video_dict = {
            **video.dict(),
            "user_id": user_id,
            "created_at": datetime.now(),
            "views": 0,
            "time": "Vừa đăng"
        }
        
        result = await videos_collection.insert_one(video_dict)
        return {
            "status": "success",
            "message": "Tạo video thành công",
            "video_id": str(result.inserted_id)
        }
    except Exception as e:
        raise HTTPException(status_code=401, detail="Token không hợp lệ")

# ==================== NOTIFICATIONS ====================

@app.get("/api/notifications/{user_id}")
async def get_notifications(user_id: str):
    """Lấy danh sách thông báo - KHÔNG CÓ DATA FAKE"""
    notifications = []
    async for notif in notifications_collection.find({"user_id": user_id}).sort("created_at", -1).limit(50):
        notifications.append({
            "id": str(notif["_id"]),
            "type": notif["type"],
            "user": notif.get("from_user", ""),
            "avatar": notif.get("from_avatar", ""),
            "content": notif.get("content", ""),
            "time": notif.get("time", ""),
            "isFollowing": notif.get("is_following", False),
            "is_read": notif.get("is_read", False)
        })
    return {"status": "success", "notifications": notifications}

@app.post("/api/notifications")
async def create_notification(notification: NotificationCreate):
    """Tạo thông báo mới"""
    notif_dict = {
        **notification.dict(),
        "time": "Vừa xong",
        "is_read": False,
        "created_at": datetime.now()
    }
    result = await notifications_collection.insert_one(notif_dict)
    return {
        "status": "success",
        "message": "Tạo thông báo thành công",
        "notification_id": str(result.inserted_id)
    }

@app.put("/api/notifications/read/{user_id}")
async def mark_notifications_read(user_id: str):
    """Đánh dấu tất cả thông báo đã đọc"""
    await notifications_collection.update_many(
        {"user_id": user_id, "is_read": False},
        {"$set": {"is_read": True}}
    )
    return {"status": "success", "message": "Đã đánh dấu đã đọc"}

# ==================== FRIENDS ====================

@app.get("/api/friends/{user_id}")
async def get_friends(user_id: str):
    """Lấy danh sách bạn bè - KHÔNG CÓ DATA FAKE"""
    friends = []
    async for friend in friends_collection.find({"user_id": user_id}).sort("created_at", -1):
        friends.append({
            "id": str(friend["_id"]),
            "name": friend.get("friend_name", ""),
            "avatar": friend.get("friend_avatar", ""),
            "status": friend.get("status", "offline"),
            "friend_id": friend.get("friend_id", "")
        })
    return {"status": "success", "friends": friends}

@app.post("/api/friends")
async def add_friend(friend: FriendCreate):
    """Thêm bạn bè"""
    friend_dict = {
        **friend.dict(),
        "status": "online",
        "created_at": datetime.now()
    }
    result = await friends_collection.insert_one(friend_dict)
    return {
        "status": "success",
        "message": "Thêm bạn bè thành công",
        "friend_id": str(result.inserted_id)
    }

@app.delete("/api/friends/{friend_id}")
async def remove_friend(friend_id: str):
    """Xóa bạn bè"""
    result = await friends_collection.delete_one({"_id": ObjectId(friend_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Không tìm thấy bạn bè")
    return {"status": "success", "message": "Đã xóa bạn bè"}

# ==================== MESSAGES ====================

@app.get("/api/messages/{user_id}/{friend_id}")
async def get_messages(user_id: str, friend_id: str):
    """Lấy tin nhắn giữa 2 user - KHÔNG CÓ DATA FAKE"""
    messages = []
    async for msg in messages_collection.find({
        "$or": [
            {"sender_id": user_id, "receiver_id": friend_id},
            {"sender_id": friend_id, "receiver_id": user_id}
        ]
    }).sort("created_at", 1).limit(100):
        messages.append({
            "id": str(msg["_id"]),
            "sender_id": msg["sender_id"],
            "receiver_id": msg["receiver_id"],
            "content": msg["content"],
            "is_read": msg.get("is_read", False),
            "created_at": msg["created_at"].isoformat()
        })
    return {"status": "success", "messages": messages}

@app.post("/api/messages")
async def send_message(message: MessageCreate):
    """Gửi tin nhắn"""
    msg_dict = {
        **message.dict(),
        "is_read": False,
        "created_at": datetime.now()
    }
    result = await messages_collection.insert_one(msg_dict)
    return {
        "status": "success",
        "message": "Gửi tin nhắn thành công",
        "message_id": str(result.inserted_id)
    }

@app.put("/api/messages/read/{message_id}")
async def mark_message_read(message_id: str):
    """Đánh dấu tin nhắn đã đọc"""
    result = await messages_collection.update_one(
        {"_id": ObjectId(message_id)},
        {"$set": {"is_read": True}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Không tìm thấy tin nhắn")
    return {"status": "success", "message": "Đã đánh dấu đã đọc"}

# ==================== RUN ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)