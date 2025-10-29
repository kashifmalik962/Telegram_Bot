from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from telethon import TelegramClient
from telethon.errors import PhoneNumberInvalidError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact
from util import *
from req_body import *
from scheduler import *
import logging

# Configure logging
logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# -------------------- Load environment --------------------
load_dotenv()

IS_PROD = os.getenv("IS_PROD", "False").lower() == "true"
if IS_PROD:
    MONGO_URI = os.getenv("MONGO_URI")
    DB = os.getenv("DB")
    USER_COLLECTION = os.getenv("USER_COLLECTION")
    LOG_COLLECTION = os.getenv("LOG_COLLECTION")  # New: telegram_log
    BOT_TOKEN = os.getenv("PROD_BOT_TOKEN")
    PHONE = os.getenv("PROD_PHONE")  # Your Telegram number
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    PORT = int(os.getenv("PORT"))
    WEBHOOK_URL = os.getenv("PROD_WEBHOOK_URL")
else:
    MONGO_URI = os.getenv("MONGO_URI")
    DB = os.getenv("DB")
    USER_COLLECTION = os.getenv("USER_COLLECTION")
    LOG_COLLECTION = os.getenv("LOG_COLLECTION")  # New: telegram_log
    BOT_TOKEN = os.getenv("DEV_BOT_TOKEN")
    PHONE = os.getenv("DEV_PHONE")  # Your Telegram number
    API_ID = int(os.getenv("API_ID"))
    API_HASH = os.getenv("API_HASH")
    PORT = int(os.getenv("PORT"))
    WEBHOOK_URL = os.getenv("DEV_WEBHOOK_URL")

print("IS_PROD", IS_PROD)
print("WEBHOOK_URL", WEBHOOK_URL)
print("PHONE", PHONE)
print("GROUP_CHAT_ID", GROUP_CHAT_ID)

# -------------------- MongoDB Setup --------------------
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB]
users_collection = db[USER_COLLECTION]
log_collection = db[LOG_COLLECTION]

# -------------------- Telethon Setup --------------------
client = TelegramClient('session', API_ID, API_HASH)

# -------------------- FastAPI Lifespan --------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start(PHONE)
    start_expiry_check()

    # Set Telegram webhook
    webhook_url = f"{WEBHOOK_URL}/webhook"  # e.g., https://your-app.herokuapp.com/webhook
    print("webhook_url with endpoint", webhook_url)
    set_webhook_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
    response = requests.get(set_webhook_url)
    print("response",response.json())
    logging.info(f"Webhook set response: {response.json()}")

    yield
    await client.disconnect()
    mongo_client.close()

    # Optional: Delete webhook on shutdown
    delete_webhook_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    response = requests.get(delete_webhook_url)
    logging.info(f"Webhook delete response: {response.json()}")

# -------------------- FastAPI App --------------------
app = FastAPI(lifespan=lifespan)

# -------------------- Request Models --------------------
class SubscribeRequest(BaseModel):
    phone: str
    duration_days: int

class PhoneCheckRequest(BaseModel):
    phone: str

@app.post("/webhook")
async def handle_webhook(request: Request):
    try:
        print("webhook running...")
        update = await request.json()
        logging.info(f"Received webhook update: {update}")
        
        if "chat_join_request" in update:
            join_request = update["chat_join_request"]
            chat_id = join_request["chat"]["id"]
            user_id = join_request["from"]["id"]
            invite_link = join_request.get("invite_link", {}).get("invite_link", "")
            logging.info(f"Join request: chat_id={chat_id}, user_id={user_id}, invite_link={invite_link}")

            print("chat_id", chat_id)
            print("user_id", user_id)
            print("invite_link", invite_link)

            if chat_id != int(GROUP_CHAT_ID):
                logging.info(f"Ignoring join request for chat_id {chat_id}")
                return {"ok": True}

            db_entry = await users_collection.find_one({"invite_link": invite_link})
            print("db_entry", db_entry)
            logging.info(f"DB entry for invite_link {invite_link}: {db_entry}")
            if db_entry and db_entry["telegram_id"] == user_id and not db_entry["joined"]:
                approve_url = f"https://api.telegram.org/bot{BOT_TOKEN}/approveChatJoinRequest?chat_id={GROUP_CHAT_ID}&user_id={user_id}"
                response = requests.get(approve_url)
                logging.info(f"Approve response: {response.json()}")

                users_collection.update_one(
                    {"telegram_id": user_id},
                    {"$set": {"joined": True}}
                )
                # Mirror to log_collection
                log_collection.update_one(
                    {"telegram_id": user_id},
                    {"$set": {"joined": True}}
                )
                logging.info(f"Marked user {user_id} as joined in both collections")

                revoke_url = f"https://api.telegram.org/bot{BOT_TOKEN}/revokeChatInviteLink?chat_id={GROUP_CHAT_ID}&invite_link={invite_link}"
                response = requests.get(revoke_url)
                logging.info(f"Revoke link response: {response.json()}")

                telegram_bot_sendtext("🎉 Welcome! Your subscription is active.", user_id)
            else:
                print("❌ This invite link is not for your account")
                decline_url = f"https://api.telegram.org/bot{BOT_TOKEN}/declineChatJoinRequest?chat_id={GROUP_CHAT_ID}&user_id={user_id}"
                response = requests.get(decline_url)
                logging.info(f"Decline response: {response.json()}")
                telegram_bot_sendtext("❌ This invite link is not for your account. Request declined.", user_id)

        return {"ok": True}
    except Exception as e:
        logging.error(f"Webhook error: {e}", exc_info=True)
        return {"ok": False}

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

        # Prepare data
        user_data = {
            "telegram_id": telegram_id,
            "phone": phone,
            "username": username,
            "invite_link": invite_link,
            "expiry_date": expiry_date,
            "joined": False
        }

        # Save to main collection
        users_collection.update_one(
            {"telegram_id": telegram_id},
            {"$set": user_data},
            upsert=True
        )
        logging.info(f"Subscribed user {telegram_id} in users_collection")

        # Mirror to log collection
        log_collection.update_one(
            {"telegram_id": telegram_id},
            {"$set": user_data},
            upsert=True
        )
        logging.info(f"Mirrored subscribed user {telegram_id} to log_collection")

        print("invite_link", invite_link)
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
        logging.error(f"Subscribe error: {e}", exc_info=True)
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

        user = await users_collection.find_one({"telegram_id": telegram_id})

        if user:
            previous_expiry = user.get("expiry_date")
            base_date = previous_expiry if previous_expiry and previous_expiry > datetime.now() else datetime.now()
            new_expiry_date = base_date + timedelta(days=extra_days)
            duration_days = (new_expiry_date - datetime.now()).days

            update_data = {"expiry_date": new_expiry_date}
            invite_link = user.get("invite_link")
            if not user.get("joined"):
                # Revoke old link if exists
                if user.get("invite_link"):
                    revoke_url = f"https://api.telegram.org/bot{BOT_TOKEN}/revokeChatInviteLink?chat_id={GROUP_CHAT_ID}&invite_link={user['invite_link']}"
                    response = requests.get(revoke_url)
                    logging.info(f"Revoke old link response: {response.json()}")

                invite_link = create_temp_invite_link()
                if not invite_link:
                    telegram_bot_sendtext("❌ Failed to generate invite link. Please try again later.", telegram_id)
                    return JSONResponse(status_code=500, content={
                        "status_code": 0,
                        "message": "Failed to generate invite link"
                    })
                update_data["invite_link"] = invite_link
                update_data["username"] = username
                telegram_bot_sendtext(f"Click here to join the group: {invite_link}", telegram_id)

            # Update main collection
            users_collection.update_one(
                {"telegram_id": telegram_id},
                {"$set": update_data}
            )
            logging.info(f"Extended plan for user {telegram_id} in users_collection")

            # Mirror to log collection
            log_collection.update_one(
                {"telegram_id": telegram_id},
                {"$set": update_data}
            )
            logging.info(f"Mirrored extended plan for user {telegram_id} to log_collection")

            telegram_bot_sendtext(f"🎉 Your plan has been extended until {new_expiry_date}", telegram_id)

            return JSONResponse(status_code=200, content={
                "status_code": 1,
                "message": "User plan extended successfully",
                "phone": phone,
                "telegram_id": telegram_id,
                "username": username,
                "invite_link": invite_link,
                "expiry_date": jsonable_encoder(new_expiry_date),
                "data": {
                    "previous_expiry": jsonable_encoder(previous_expiry),
                    "new_expiry": jsonable_encoder(new_expiry_date),
                    "duration_days": duration_days
                }
            })

        else:
            invite_link = create_temp_invite_link()
            if not invite_link:
                telegram_bot_sendtext("❌ Failed to generate invite link. Please try again later.", telegram_id)
                return JSONResponse(status_code=500, content={
                    "status_code": 0,
                    "message": "Failed to generate invite link"
                })

            new_expiry_date = datetime.now() + timedelta(days=extra_days)
            duration_days = extra_days

            # Prepare data
            user_data = {
                "telegram_id": telegram_id,
                "phone": phone,
                "username": username,
                "invite_link": invite_link,
                "expiry_date": new_expiry_date,
                "joined": False
            }

            # Save to main collection
            users_collection.update_one(
                {"telegram_id": telegram_id},
                {"$set": user_data},
                upsert=True
            )
            logging.info(f"Extended (new) plan for user {telegram_id} in users_collection")

            # Mirror to log collection
            log_collection.update_one(
                {"telegram_id": telegram_id},
                {"$set": user_data},
                upsert=True
            )
            logging.info(f"Mirrored extended (new) plan for user {telegram_id} to log_collection")

            telegram_bot_sendtext(f"Click here to join the group: {invite_link}", telegram_id)

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
                    "new_expiry": jsonable_encoder(new_expiry_date),
                    "duration_days": duration_days
                }
            })

    except Exception as e:
        logging.error(f"Extend plan error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# -------------------- Get All Active user Endpoint --------------------
@app.get("/get-all-active-user")
async def get_all_active_user():
    try:
        # Fetch all joined=True users
        joined_true_cursor = users_collection.find({"joined": True})
        joined_true_users = []
        async for user in joined_true_cursor:
            user["_id"] = str(user["_id"])  # convert ObjectId to string
            joined_true_users.append(user)

        # Fetch all joined=False users
        joined_false_cursor = users_collection.find({"joined": False})
        joined_false_users = []
        async for user in joined_false_cursor:
            user["_id"] = str(user["_id"])
            joined_false_users.append(user)

        data = {
            "joined_true_count": len(joined_true_users),
            "joined_false_count": len(joined_false_users),
            "joined_true_users": joined_true_users,
            "joined_false_users": joined_false_users
        }

        return JSONResponse(
            status_code=200,
            content={
                "message": "Successfully retrieved candidate data.",
                "status_code": 1,
                "data": jsonable_encoder(data)
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "message": "Failed to retrieve candidate data.",
                "status_code": 0,
                "error": str(e)
            }
        )
    

# -------------------- Get out user from group Endpoint --------------------
@app.post("/get-out-user-group")
async def get_out_user_group(telegram_id: int):
    try:
        user_exist = await users_collection.find_one({"telegram_id": telegram_id})
        if not user_exist:
            return JSONResponse(
                status_code=404,
                content={
                    "message": "User not exist.",
                    "status_code": 0
                }
            )
        kick_user(telegram_id)
        users_collection.delete_one({"telegram_id": telegram_id})
        print(f"User {telegram_id} kicked by admin.")

        return JSONResponse(
            status_code=200,
            content={
                "message": "Successfully removed candidate from group.",
                "status_code": 1,
                "telegram_id": telegram_id
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "message": "Failed to retrieve candidate data.",
                "status_code": 0,
                "error": str(e)
            }
        )

# -------------------- Manual Kick Endpoint --------------------
@app.get("/kick_expired_users")
def kick_expired_users():
    check_and_kick_users()
    return {"message": "Expired users kicked successfully"}


# -------------------- Run App --------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)