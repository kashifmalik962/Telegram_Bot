# main.py

from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from pymongo import MongoClient
from telethon import TelegramClient
from telethon.errors import PhoneNumberInvalidError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact
from util import *
from req_body import *
from scheduler import *

# -------------------- Load environment --------------------
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
DB = os.getenv("DB")
USER_COLLECTION = os.getenv("USER_COLLECTION")
BOT_TOKEN = os.getenv("BOT_TOKEN")
PHONE = os.getenv("PHONE")  # Your Telegram number
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")

# -------------------- MongoDB Setup --------------------
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DB]
users_collection = db[USER_COLLECTION]

# -------------------- Telethon Setup --------------------
client = TelegramClient('session', API_ID, API_HASH)

# -------------------- FastAPI Lifespan --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start(PHONE)
    start_expiry_check()
    yield
    await client.disconnect()
    mongo_client.close()

# -------------------- FastAPI App --------------------
app = FastAPI(lifespan=lifespan)

# -------------------- Request Models --------------------
class SubscribeRequest(BaseModel):
    phone: str
    duration_days: int

class PhoneCheckRequest(BaseModel):
    phone: str

# -------------------- Helper Functions --------------------
async def get_telegram_id_by_phone(phone: str):
    """
    Import a phone contact, return Telegram ID and username if exists.
    """
    try:
        contact = InputPhoneContact(client_id=0, phone=phone, first_name="Temp", last_name="Temp")
        result = await client(ImportContactsRequest([contact]))
        if result.users:
            user = result.users[0]
            await client(DeleteContactsRequest(id=[user.id]))  # optional cleanup
            return user.id, getattr(user, "username", None)
        return None, None
    except PhoneNumberInvalidError:
        return None, None

# -------------------- Check User by Phone Endpoint --------------------
@app.post("/check-user-by-phone")
async def check_user_by_phone(request: PhoneCheckRequest):
    try:
        telegram_id, username = await get_telegram_id_by_phone(request.phone)
        if telegram_id:
            return {"exists": True, "telegram_id": telegram_id, "username": username, "phone": request.phone}
        return {"exists": False, "telegram_id": None, "username": None, "phone": request.phone}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------- Subscribe Endpoint --------------------
@app.post("/subscribe")
async def subscribe_user(request: SubscribeRequest):
    try:
        phone = request.phone
        duration_days = request.duration_days

        if not phone or not duration_days or duration_days <= 0:
            return JSONResponse(status_code=400, content={
                "status_code": 0,
                "message": "phone or duration_days missing/invalid"
            })

        telegram_id, username = await get_telegram_id_by_phone(phone)
        if not telegram_id:
            return JSONResponse(status_code=404, content={
                "status_code": 0,
                "message": "Telegram account not found for this phone number"
            })

        invite_link = create_temp_invite_link()
        if not invite_link:
            telegram_bot_sendtext("❌ Failed to generate invite link. Please try again later.", telegram_id)
            return JSONResponse(status_code=500, content={
                "status_code": 0,
                "message": "Failed to generate invite link"
            })

        expiry_date = datetime.now() + timedelta(days=duration_days)

        # Save to DB (phone + telegram_id)
        users_collection.update_one(
            {"telegram_id": telegram_id},
            {"$set": {
                "telegram_id": telegram_id,
                "phone": phone,
                "invite_link": invite_link,
                "expiry_date": expiry_date
            }},
            upsert=True
        )

        telegram_bot_sendtext(f"Click here to join the group: {invite_link}", telegram_id)

        return JSONResponse(status_code=200, content={
            "status_code": 1,
            "message": "User subscribed successfully",
            "phone": phone,
            "telegram_id": telegram_id,
            "username": username,
            "invite_link": invite_link,
            "expiry_date": jsonable_encoder(expiry_date)
        })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------- Extend Plan Endpoint --------------------
@app.post("/extend-plan")
async def extend_plan(request: SubscribeRequest):
    try:
        phone = request.phone
        extra_days = request.duration_days

        if not phone or not extra_days or extra_days <= 0:
            return JSONResponse(status_code=400, content={
                "status_code": 0,
                "message": "phone or duration_days missing/invalid"
            })

        telegram_id, username = await get_telegram_id_by_phone(phone)
        if not telegram_id:
            return JSONResponse(status_code=404, content={
                "status_code": 0,
                "message": "Telegram account not found for this phone number"
            })

        user = users_collection.find_one({"telegram_id": telegram_id})

        if user:
            previous_expiry = user.get("expiry_date")
            base_date = previous_expiry if previous_expiry and previous_expiry > datetime.now() else datetime.now()
            new_expiry_date = base_date + timedelta(days=extra_days)
            duration_days = (new_expiry_date - datetime.now()).days

            users_collection.update_one(
                {"telegram_id": telegram_id},
                {"$set": {"expiry_date": new_expiry_date}}
            )

            telegram_bot_sendtext(f"🎉 Your plan has been extended until {new_expiry_date}", telegram_id)

            return JSONResponse(status_code=200, content={
                "status_code": 1,
                "message": "User plan extended successfully",
                "phone": phone,
                "telegram_id": telegram_id,
                "username": username,
                "invite_link": user.get("invite_link"),
                "expiry_date": jsonable_encoder(new_expiry_date),
                "data": {
                    "previous_expiry": jsonable_encoder(previous_expiry),
                    "new_expiry": jsonable_encoder(new_expiry_date),
                    "duration_days": duration_days
                }
            })

        else:
            invite_link = create_temp_invite_link()
            if invite_link:
                new_expiry_date = datetime.now() + timedelta(days=extra_days)
                users_collection.update_one(
                    {"telegram_id": telegram_id},
                    {"$set": {
                        "telegram_id": telegram_id,
                        "phone": phone,
                        "invite_link": invite_link,
                        "expiry_date": new_expiry_date
                    }},
                    upsert=True
                )
                telegram_bot_sendtext(f"Click here to join the group: {invite_link}", telegram_id)
            else:
                telegram_bot_sendtext("❌ Failed to generate invite link. Please try again later.", telegram_id)

            return JSONResponse(status_code=200, content={
                "status_code": 1,
                "message": "User plan extended successfully",
                "phone": phone,
                "telegram_id": telegram_id,
                "username": username,
                "invite_link": invite_link,
                "expiry_date": jsonable_encoder(new_expiry_date),
                "data": {
                    "previous_expiry": None,
                    "duration_days": jsonable_encoder(new_expiry_date)
                }
            })

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -------------------- Manual Kick Endpoint --------------------
@app.get("/kick_expired_users")
def kick_expired_users():
    check_and_kick_users()
    return {"message": "Expired users kicked successfully"}


# -------------------- Run App --------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
