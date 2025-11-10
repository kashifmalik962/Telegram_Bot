# -------------------------------------------------------------
# main.py
from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import re
import logging
import requests
import asyncio
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from telethon import TelegramClient
from util import *
from scheduler import *

# -------------------- Logging --------------------
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# -------------------- Load Env --------------------
load_dotenv()

IS_PROD = os.getenv("IS_PROD", "False").lower() == "true"
if IS_PROD:
    MONGO_URI = os.getenv("MONGO_URI")
    DB = os.getenv("DB")
    USER_COLLECTION = os.getenv("USER_COLLECTION")
    LOG_COLLECTION = os.getenv("LOG_COLLECTION")
    BOT_TOKEN = os.getenv("PROD_BOT_TOKEN")
    PHONE = os.getenv("PROD_PHONE")
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    PORT = int(os.getenv("PORT"))
    WEBHOOK_URL = os.getenv("PROD_WEBHOOK_URL")
    BOT_USERNAME = os.getenv("PROD_BOT_USERNAME", "")
else:
    MONGO_URI = os.getenv("MONGO_URI")
    DB = os.getenv("DB")
    USER_COLLECTION = os.getenv("USER_COLLECTION")
    LOG_COLLECTION = os.getenv("LOG_COLLECTION")
    BOT_TOKEN = os.getenv("DEV_BOT_TOKEN")
    PHONE = os.getenv("DEV_PHONE")
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    PORT = int(os.getenv("PORT"))
    WEBHOOK_URL = os.getenv("DEV_WEBHOOK_URL")
    BOT_USERNAME = os.getenv("DEV_BOT_USERNAME", "")

# ---- Validate ----
if not BOT_USERNAME:
    logging.warning("BOT_USERNAME not set in .env")

print("IS_PROD:", IS_PROD)
print("BOT_TOKEN:", BOT_TOKEN)
print("WEBHOOK_URL:", WEBHOOK_URL)
print("GROUP_CHAT_ID:", GROUP_CHAT_ID)

# -------------------- MongoDB --------------------
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB]
users_collection = db[USER_COLLECTION]
log_collection = db[LOG_COLLECTION]

# -------------------- Telethon --------------------
client = TelegramClient('session', API_ID, API_HASH)

# -------------------- Helpers --------------------
def validate_phone(phone: str) -> bool:
    return bool(re.match(r'^\+[1-9]\d{1,14}$', phone))

async def _tg_get(url: str):
    return await asyncio.to_thread(requests.get, url)

async def approve_join_request(user_id: int):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/approveChatJoinRequest?chat_id={GROUP_CHAT_ID}&user_id={user_id}"
    await _tg_get(url)

async def decline_join_request(user_id: int):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/declineChatJoinRequest?chat_id={GROUP_CHAT_ID}&user_id={user_id}"
    await _tg_get(url)

async def revoke_invite_link(link: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/revokeChatInviteLink?chat_id={GROUP_CHAT_ID}&invite_link={link}"
    await _tg_get(url)

# -------------------- Lifespan --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start(phone=PHONE)
    start_expiry_check()

    webhook_url = f"{WEBHOOK_URL}/webhook"
    await _tg_get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}")
    logging.info("Webhook set")

    yield

    await client.disconnect()
    mongo_client.close()
    await _tg_get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")

app = FastAPI(lifespan=lifespan)

# -------------------- Models --------------------
class SubscribeRequest(BaseModel):
    phone: str
    duration_days: int

class PhoneCheckRequest(BaseModel):
    phone: str

# ==================== WEBHOOK – AUTO APPROVE + SAVE telegram_id ====================
@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
        logging.info(f"Webhook update: {update}")

        if "chat_join_request" not in update:
            return {"ok": True}

        req = update["chat_join_request"]
        chat_id = req["chat"]["id"]
        user_id = req["from"]["id"]
        username = req["from"].get("username", "")
        invite_link = req.get("invite_link", {}).get("invite_link", "")


        print("chat_id", chat_id)
        print("user_id", user_id)
        print("username", username)
        print("invite_link", invite_link)
        print("req", req)
        
        
        if chat_id != int(GROUP_CHAT_ID):
            return {"ok": True}

        # Find subscription by invite_link
        sub = await users_collection.find_one({"invite_link": invite_link, "joined": False})
        if not sub:
            await decline_join_request(user_id)
            await telegram_bot_sendtext("This link is invalid or already used.", user_id)
            return {"ok": True}

        # APPROVE
        await approve_join_request(user_id)

        # SAVE telegram_id
        update_data = {
            "joined": True,
            "telegram_id": user_id,
            "username": username
        }
        await users_collection.update_one(
            {"invite_link": invite_link},
            {"$set": update_data}
        )
        await log_collection.update_one(
            {"invite_link": invite_link},
            {"$set": update_data}
        )

        # REVOKE one-time link
        try:
            await revoke_invite_link(invite_link)
        except:
            pass

        await telegram_bot_sendtext("Welcome! Your subscription is active.", user_id)
        logging.info(f"User {user_id} joined via invite_link")

        return {"ok": True}

    except Exception as e:
        logging.error(f"Webhook error: {e}", exc_info=True)
        return {"ok": False}

# ==================== ENDPOINTS ====================
@app.post("/check-user-by-phone")
async def check_phone(req: PhoneCheckRequest):
    if not validate_phone(req.phone):
        return {"valid": False, "message": "Invalid phone format"}
    return {"valid": True, "message": "Phone valid. Proceed to subscribe."}

@app.post("/subscribe")
async def subscribe(req: SubscribeRequest):
    try:
        phone = req.phone
        days = req.duration_days

        if not validate_phone(phone) or days <= 0:
            return JSONResponse(status_code=400, content={"status_code":0, "message":"Invalid input"})
        if await users_collection.find_one({"phone": phone}):
            return JSONResponse(status_code=400, content={"status_code":0, "message":"Already subscribed"})

        # Create one-time join-request link
        group_link = create_temp_invite_link()
        if not group_link:
            return JSONResponse(status_code=500, content={"status_code":0, "message":"Failed to create link"})

        expiry = datetime.now() + timedelta(days=days)

        doc = {
            "phone": phone,
            "invite_link": group_link,
            "expiry_date": expiry,
            "joined": False,
            "telegram_id": None,
            "username": None
        }

        await users_collection.insert_one(doc)
        await log_collection.insert_one(doc.copy())

        return JSONResponse(status_code=200, content={
            "status_code": 1,
            "message": "Click below to join. Your request will be approved automatically.",
            "phone": phone,
            "group_link": group_link,
            "expiry_date": jsonable_encoder(expiry)
        })

    except Exception as e:
        logging.error(f"Subscribe error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ---- Extend Plan ----
@app.post("/extend-plan")
async def extend(req: SubscribeRequest):
    try:
        phone = req.phone
        days = req.duration_days
        if not validate_phone(phone) or days <= 0:
            return JSONResponse(status_code=400, content={"status_code":0, "message":"Invalid"})

        user = await users_collection.find_one({"phone": phone})
        base = user["expiry_date"] if user and user["expiry_date"] > datetime.now() else datetime.now()
        new_expiry = base + timedelta(days=days)

        update = {"expiry_date": new_expiry}
        if user and not user.get("joined"):
            await revoke_invite_link(user["invite_link"])
            new_link = create_temp_invite_link()
            if not new_link:
                return JSONResponse(status_code=500, content={"status_code":0, "message":"Link failed"})
            update["invite_link"] = new_link

        await users_collection.update_one({"phone": phone}, {"$set": update})
        await log_collection.update_one({"phone": phone}, {"$set": update})

        if user and user.get("telegram_id"):
            telegram_bot_sendtext(f"Plan extended to {new_expiry:%Y-%m-%d}", user["telegram_id"])

        return JSONResponse(status_code=200, content={
            "status_code": 1,
            "expiry_date": jsonable_encoder(new_expiry),
            "group_link": update.get("invite_link")
        })
    except Exception as e:
        logging.error(f"Extend error: {e}")
        raise HTTPException(status_code=500)

# ---- Admin Endpoints ----
@app.get("/get-all-active-user")
async def get_all():
    joined = [u async for u in users_collection.find({"joined": True})]
    pending = [u async for u in users_collection.find({"joined": False})]
    for u in joined + pending:
        u["_id"] = str(u["_id"])
    return JSONResponse(status_code=200, content={
        "status_code": 1,
        "data": {
            "joined": len(joined),
            "pending": len(pending),
            "joined_users": joined,
            "pending_users": pending
        }
    })

@app.post("/get-out-user-group")
async def kick(telegram_id: int):
    user = await users_collection.find_one({"telegram_id": telegram_id})
    if not user:
        return JSONResponse(status_code=404, content={"status_code":0, "message":"Not found"})
    kick_user(telegram_id)
    await users_collection.delete_one({"telegram_id": telegram_id})
    return JSONResponse(status_code=200, content={"status_code":1})

@app.get("/kick_expired_users")
def kick_expired():
    check_and_kick_users()
    return {"ok": True}

# -------------------- Run --------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)