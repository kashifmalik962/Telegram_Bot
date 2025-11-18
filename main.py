# -------------------------------------------------------------
# main.py
from fastapi import FastAPI, HTTPException, File, UploadFile, Request
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
import pandas as pd
import io
import re
from datetime import datetime
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
    IMPORT_USERS_COLLECTION = os.getenv("IMPORT_USERS_COLLECTION")
    LOG_COLLECTION = os.getenv("LOG_COLLECTION")
    BOT_TOKEN = os.getenv("PROD_BOT_TOKEN")
    PHONE = os.getenv("PROD_PHONE")
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    PORT = int(os.getenv("PORT"))
    WEBHOOK_URL = os.getenv("PROD_WEBHOOK_URL")
    BOT_USERNAME = os.getenv("PROD_BOT_USERNAME", "")
    GROUP_CHAT_ID = os.getenv("PROD_GROUP_CHAT_ID")
else:
    MONGO_URI = os.getenv("MONGO_URI")
    DB = os.getenv("DB")
    USER_COLLECTION = os.getenv("USER_COLLECTION")
    IMPORT_USERS_COLLECTION = os.getenv("IMPORT_USERS_COLLECTION")
    LOG_COLLECTION = os.getenv("LOG_COLLECTION")
    BOT_TOKEN = os.getenv("DEV_BOT_TOKEN")
    PHONE = os.getenv("DEV_PHONE")
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    PORT = int(os.getenv("PORT"))
    WEBHOOK_URL = os.getenv("DEV_WEBHOOK_URL")
    BOT_USERNAME = os.getenv("DEV_BOT_USERNAME", "")
    GROUP_CHAT_ID = os.getenv("DEV_GROUP_CHAT_ID")

# ---- Validate ----
if not BOT_USERNAME:
    logging.warning("BOT_USERNAME not set in .env")

print("IS_PROD:", IS_PROD)
print("BOT_TOKEN:", BOT_TOKEN)
print("WEBHOOK_URL:", WEBHOOK_URL)
print("GROUP_CHAT_ID:", GROUP_CHAT_ID)
print("PHONE:", PHONE)

# -------------------- MongoDB --------------------
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB]
users_collection = db[USER_COLLECTION]
log_collection = db[LOG_COLLECTION]
import_users_coll = db[IMPORT_USERS_COLLECTION]

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
    # Start Telethon
    await client.start(phone=PHONE)
    print("Telethon started")

    # Run Telethon event loop in background
    asyncio.create_task(client.run_until_disconnected())

    # Start expiry checker
    start_expiry_check()

    # Setup Webhook
    webhook_url = f"{WEBHOOK_URL}/webhook"
    await _tg_get(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}")
    logging.info("Webhook set")

    yield

    # Shutdown
    await client.disconnect()
    mongo_client.close()
    await _tg_get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")


app = FastAPI(lifespan=lifespan)

# -------------------- Models --------------------
class SubscribeRequest(BaseModel):
    phone: str
    duration_days: int

class RegenerateLink(BaseModel):
    phone: str

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
        group_link = req.get("invite_link", {}).get("invite_link", "")


        print("chat_id", chat_id)
        print("user_id", user_id)
        print("username", username)
        print("group_link", group_link)
        print("req", req)
        print("update", update)
        
        
        if chat_id != int(GROUP_CHAT_ID):
            return {"ok": True}

        # Find subscription by invite_link
        sub = await users_collection.find_one({"group_link": group_link, "joined": False, "link_used": False})
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
            "username": username,
            "left_group": False,
            "left_at": None,
            "link_used": True
        }
        await users_collection.update_one(
            {"group_link": group_link},
            {"$set": update_data}
        )
        await log_collection.update_one(
            {"group_link": group_link},
            {"$set": update_data}
        )

        # REVOKE one-time link
        try:
            await revoke_invite_link(group_link)
            print("revoke_invite_link +++++++++++++++")
        except:
            pass

        await telegram_bot_sendtext("Welcome! Your subscription is active.", user_id)
        logging.info(f"User {user_id} joined via group_link")

        return {"ok": True}

    except Exception as e:
        logging.error(f"Webhook error: {e}", exc_info=True)
        return {"ok": False}



# -------------------- Telethon Event: User Left Group --------------------
from telethon import events

@client.on(events.ChatAction)
async def handle_user_left(event):
    try:
        print("running handle_user_left...")

        if not (event.user_left or event.user_kicked):
            return

        chat = await event.get_chat()

        # FIX: Telethon returns bare ID without -100 prefix
        real_group_id = f"-100{chat.id}"
        print("real_group_id", real_group_id)
        print("env GROUP_CHAT_ID", GROUP_CHAT_ID)

        if str(real_group_id) != str(GROUP_CHAT_ID):
            print("❌ Not matching group id, skipping...")
            return

        user = await event.get_user()
        telegram_id = user.id

        print("left group telegram id", telegram_id)

        update_data = {
            "joined": False,
            "left_group": True,
            "left_at": datetime.utcnow(),
        }

        result = await users_collection.update_one(
            {"telegram_id": telegram_id},
            {"$set": update_data}
        )

        print("update result", result.modified_count)

        print(f"🚨 User Left: {telegram_id}")

    except Exception as e:
        print("Left event error:", e)


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
        if await users_collection.find_one({"phone": phone, "joined": True}):
            return JSONResponse(status_code=400, content={"status_code":0, "message":"Already Joined group"})


        exist_user =  await users_collection.find_one({"phone": phone})
        if not exist_user:
            # Create one-time join-request link
            group_link = create_temp_invite_link()
            if not group_link:
                print("group_link", group_link)
                return JSONResponse(status_code=500, content={"status_code":0, "message":"Failed to create link"})

            expiry = datetime.now() + timedelta(days=days)

            print("expiry", expiry)
            doc = {
                "phone": phone,
                "group_link": group_link,
                "expiry_date": expiry,
                "joined": False,
                "telegram_id": None,
                "username": None,
                "left_group": False,
                "left_at": None,
                "link_used": False
            }
            
            await users_collection.insert_one(doc)
            await log_collection.insert_one(doc.copy())

            # Remove _id before sending response
            doc.pop("_id", None)

            return JSONResponse(
                status_code=200,
                content={
                    "status_code": 1,
                    "message": "Click below to join. Your request will be approved automatically.",
                    "data": jsonable_encoder(doc)
                }
            )
        
        else:
            remain_days_in_expiry =  await users_collection.find_one({"phone": phone, "expiry_date": {"$gt": datetime.now()}})
            if remain_days_in_expiry:
                return JSONResponse(
                    status_code=200,
                    content={
                        "status_code": 1,
                        "message": "Already generated link Please contact by admin."
                    }
                )

    except Exception as e:
        logging.error(f"Subscribe error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status_code":1, "message":str(e)})



# ---- Extend Plan ----
@app.post("/extend-plan")
async def extend(req: SubscribeRequest):
    try:
        phone = req.phone
        days = req.duration_days
        if not validate_phone(phone) or days <= 0:
            return JSONResponse(status_code=400, content={"status_code":0, "message":"Invalid"})

        user = await users_collection.find_one({"phone": phone})
        if user:
            base = user["expiry_date"] if user and user["expiry_date"] > datetime.now() else datetime.now()
            new_expiry = base + timedelta(days=days)

            update = {"expiry_date": new_expiry}
            # if user and not user.get("joined"):
            #     await revoke_invite_link(user["group_link"])
            #     new_link = create_temp_invite_link()
            #     if not new_link:
            #         return JSONResponse(status_code=500, content={"status_code":0, "message":"Link failed"})
            #     update["group_link"] = new_link

            await users_collection.update_one({"phone": phone}, {"$set": update})
            await log_collection.update_one({"phone": phone}, {"$set": update})

            if user and user.get("telegram_id"):
                telegram_bot_sendtext(f"Plan extended to {new_expiry:%Y-%m-%d}", user["telegram_id"])

            return JSONResponse(status_code=200, content={
                "status_code": 1,
                "expiry_date": jsonable_encoder(new_expiry),
                "group_link": update.get("group_link")
            })
        
        else:
            # Create one-time join-request link
            group_link = create_temp_invite_link()
            if not group_link:
                print("group_link", group_link)
                return JSONResponse(status_code=500, content={"status_code":0, "message":"Failed to create link"})

            expiry = datetime.now() + timedelta(days=days)

            doc = {
                "phone": phone,
                "group_link": group_link,
                "expiry_date": expiry,
                "joined": False,
                "telegram_id": None,
                "username": None,
                "left_group": False,
                "left_at": None,
                "link_used": False
            }
            
            await users_collection.insert_one(doc)
            await log_collection.insert_one(doc.copy())

            # Remove _id before sending response
            doc.pop("_id", None)

            return JSONResponse(
                status_code=200,
                content={
                    "status_code": 1,
                    "message": "Click below to join. Your request will be approved automatically.",
                    "data": jsonable_encoder(doc)
                }
            )

    except Exception as e:
        logging.error(f"Extend error: {e}")
        raise HTTPException(status_code=500)



@app.post("/re-generate-link-after-leave")
async def re_generate_link_after_leave(req: RegenerateLink):
    try:
        phone = req.phone

        if not validate_phone(phone):
            return JSONResponse(status_code=400, content={"status_code":0, "message":"Invalid input"})
        if await users_collection.find_one({"phone": phone, "joined": True}):
            return JSONResponse(status_code=400, content={"status_code":0, "message":"Already Joined group"})

        if await users_collection.find_one({"phone": phone, "joined": False, "left_group": True,"expiry_date": {"$gt": datetime.now()}}):
            # Create one-time join-request link
            group_link = create_temp_invite_link()
            if not group_link:
                print("group_link", group_link)
                return JSONResponse(status_code=500, content={"status_code":0, "message":"Failed to create link"})

            await users_collection.update_one({"phone": phone},{"$set": {"group_link": group_link, "link_used": False}})
            result = await users_collection.find_one({"phone": phone}, {"_id": 0})
            return JSONResponse(status_code=200, content={"status_code":1, 
                                                          "message": "Successfully group link generated",
                                                          "data": jsonable_encoder(result)})
    except Exception as e:
        logging.error(f"Subscribe error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status_code":1, "message":str(e)})


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
    # await users_collection.delete_one({"telegram_id": telegram_id})
    await users_collection.delete_one(
            {"telegram_id": telegram_id}
        )
    return JSONResponse(status_code=200, content={"status_code":1})

@app.get("/kick_expired_users")
def kick_expired():
    check_and_kick_users()
    return {"ok": True}



@app.post("/import-user")
async def import_user(file: UploadFile = File(...)):
    """
    Upload CSV/XLSX → map → insert/update MongoDB
    """
    try:
        filename = file.filename.lower()
        if not (filename.endswith(".csv") or filename.endswith(".xlsx")):
            raise HTTPException(status_code=400, detail="Only CSV or XLSX allowed.")

        # Read + parse file
        file_bytes = await file.read()
        if filename.endswith(".csv"):
            decoded = file_bytes.decode("utf-8", errors="ignore")
            df = pd.read_csv(io.StringIO(decoded))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes))

        if df.empty:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        total_inserted, inserted, errors, not_phone = 0, [], [], 0, 0

        for idx, row in df.iterrows():
            try:
                mapped = transform_row_data(row)
                phone = mapped.get("phone")
                
                if not phone:
                    print("mapped", mapped)
                    not_phone+=1
                    errors.append({"row": idx + 1, "error": "Missing phone"})
                    print("not_phone", not_phone)
                    await import_users_coll.insert_one(mapped)
                    total_inserted+=1
                    continue

                existing = await import_users_coll.find_one({"phone": phone})

                if existing:
                    continue

                try:
                    telegram_id, username = await get_telegram_id_by_phone(phone)
                    if telegram_id:
                        mapped["telegram_id"] = telegram_id
                        mapped["telegram_username"] = username
                        print(f"✅ Found Telegram ID for {phone}: {telegram_id}")
                    else:
                        print(f"❌ No Telegram account found for {phone}")
                except Exception as e:
                    print("Error fetching telegram_id:", e)

                await import_users_coll.insert_one(mapped)
                inserted.append(mapped["phone"])
                total_inserted+=1
        
            except Exception as row_err:
                email_val = row.get("Email ID") if "Email ID" in row else None
                errors.append({"row": idx + 1, "error": str(row_err), "email": email_val})


        return JSONResponse(
            content={
                "message": "bulk import completed",
                "inserted": inserted,
                "errors": errors,
            },
            status_code=200,
        )

    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    

# -------------------- Run --------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)