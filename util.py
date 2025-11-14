import requests
import time
from dotenv import load_dotenv
import os
import pymongo
from datetime import datetime
import logging
from telethon.errors import PhoneNumberInvalidError, FloodWaitError
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest
from telethon.tl.types import InputPhoneContact
import pandas as pd
import re
from datetime import datetime
import asyncio
from typing import Optional


logging.basicConfig(
    filename='app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# load environment variables
load_dotenv()

IS_PROD = os.getenv("IS_PROD", "False").lower() == "true"
if IS_PROD:
    BOT_TOKEN = os.getenv("PROD_BOT_TOKEN")
    GROUP_CHAT_ID = os.getenv("PROD_GROUP_CHAT_ID")
    MONGO_URI = os.getenv("MONGO_URI")
    DB = os.getenv("DB")
    USER_COLLECTION = os.getenv("USER_COLLECTION")
    LOG_COLLECTION = os.getenv("LOG_COLLECTION")  # New: telegram_log
else:
    BOT_TOKEN = os.getenv("DEV_BOT_TOKEN")
    GROUP_CHAT_ID = os.getenv("DEV_GROUP_CHAT_ID")
    MONGO_URI = os.getenv("MONGO_URI")
    DB = os.getenv("DB")
    USER_COLLECTION = os.getenv("USER_COLLECTION")
    LOG_COLLECTION = os.getenv("LOG_COLLECTION")  # New: telegram_log

# MongoDB Setup
client = pymongo.MongoClient(MONGO_URI)
db = client[DB]
users_collection = db[USER_COLLECTION]
log_collection = db[LOG_COLLECTION]  # New log collection

# -------------------- Utility Functions --------------------

def telegram_bot_sendtext(bot_message, telegram_id):
    """Send message to a specific Telegram user."""
    send_text = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?chat_id={telegram_id}&parse_mode=HTML&text={bot_message}'
    try:
        response = requests.get(send_text)
        logging.info(f"Sent message to {telegram_id}: {response.json()}")
        return response.json()
    except Exception as e:
        logging.error(f"Error sending Telegram message to {telegram_id}: {e}")
        return None


def create_temp_invite_link():
    """Create a one-time, expiring Telegram group invite link."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createChatInviteLink"
    data = {
        "chat_id": GROUP_CHAT_ID,
        "expire_date": int(time.time()) + (7 * 24 * 60 * 60),  # 7 days validity
        "creates_join_request": True  # Require approval
    }
    try:
        response = requests.post(url, json=data)
        result = response.json()
        print("result", result)
        raw_link = result.get("result", {}).get("invite_link", "")
        if raw_link:
            logging.info(f"Generated invite link: {raw_link}")
            return raw_link  # Raw link with '+'
        logging.error(f"Invite link error: {result}")
        return None
    except Exception as e:
        logging.error(f"Error generating invite link: {e}")
        return None

def add_user(telegram_id: int, expiry_date: datetime, invite_link: str):
    """Add or update a user in MongoDB."""
    users_collection.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"expiry_date": expiry_date, "invite_link": invite_link, "joined": False}},
        upsert=True
    )
    logging.info(f"[Added] User {telegram_id} added with expiry {expiry_date}.")

def kick_user(telegram_id: int):
    """Kick a user from the Telegram group."""
    kick_url = f"https://api.telegram.org/bot{BOT_TOKEN}/banChatMember?chat_id={GROUP_CHAT_ID}&user_id={telegram_id}"
    unban_url = f"https://api.telegram.org/bot{BOT_TOKEN}/unbanChatMember?chat_id={GROUP_CHAT_ID}&user_id={telegram_id}"
    try:
        response = requests.get(kick_url)
        logging.info(f"Kick response for {telegram_id}: {response.json()}")
        response = requests.get(unban_url)
        logging.info(f"Unban response for {telegram_id}: {response.json()}")
        logging.info(f"[Auto Kick] User {telegram_id} kicked successfully.")
    except Exception as e:
        logging.error(f"Error kicking user {telegram_id}: {e}")


def send_group_subscription_notification(telegram_id: int):
    """Notify group about a new subscription."""
    message = f"🎉 A new user has subscribed and is eligible to join the group! User ID: {telegram_id}"
    telegram_bot_sendtext(message, GROUP_CHAT_ID)


def extend_plan_in_db(telegram_id, new_expiry_date):
    """Extend plan in DB (unused, but if called, mirror to log)."""
    users_collection.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"expiry_date": new_expiry_date}},
        upsert=True
    )
    log_collection.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"expiry_date": new_expiry_date}},
        upsert=True
    )
    logging.info(f"Extended plan for user {telegram_id} in both collections")


# -----------------------------
# Clean phone number
# -----------------------------
def clean_phone_number(phone: Optional[str]) -> Optional[str]:
    """Normalize phone to format +91XXXXXXXXXX"""
    if not phone or (isinstance(phone, float) and pd.isna(phone)):
        return None

    raw = str(phone).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]

    digits = re.sub(r"\D", "", raw)

    if len(digits) == 10:
        return "+91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        return "+91" + digits[1:]
    elif len(digits) == 12 and digits.startswith("91"):
        return "+" + digits
    else:
        return "+" + digits if not raw.startswith("+") else raw


# -----------------------------
# Parse date safely
# -----------------------------
def parse_date(value: Optional[str]) -> Optional[datetime]:
    """
    Convert '19 Dec, 2024' → datetime object in UTC format.
    Returns None if blank or invalid.
    """
    if not value or (isinstance(value, float) and pd.isna(value)):
        return None

    try:
        # Try parsing '19 Dec, 2024' or similar
        dt = datetime.strptime(str(value).strip(), "%d %b, %Y")
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    except Exception:
        return None


# -----------------------------
# Transform each row
# -----------------------------
def transform_row_data(row) -> dict:
    """Map CSV columns → internal profile schema."""
    def clean_field(val):
        """Convert NaN or empty to None"""
        if pd.isna(val) or str(val).strip() in ["", "NaN", "nan", "None"]:
            return None
        return str(val).strip()

    mapped = {
        "phone": clean_phone_number(row.get("Telegram Number")),
        "account_name": clean_field(row.get("Account Name")),
        "full_name": clean_field(row.get("Full Name")),
        "mobile": clean_field(row.get("Mobile")),
        "email": clean_field(row.get("Email")),
        "pan_number": clean_field(row.get("Pan Number")),
        "start_date": parse_date(row.get("Support Start Date")),
        "expiry_date": parse_date(row.get("Support End Date")),
        "telegram_name": clean_field(row.get("Telegram Name")),
        "status": clean_field(row.get("Status")),
        "calling_status": clean_field(row.get("Calling status")),
        "telegram_id": None,
        "telegram_username": None,
        "joined": True
    }

    return mapped



async def get_telegram_id_by_phone(phone: str):
    """
    Import a phone contact, return Telegram ID and username if exists.
    Handles FloodWait automatically.
    """
    try:
        contact = InputPhoneContact(client_id=0, phone=phone, first_name="Temp", last_name="Temp")

        while True:
            try:
                result = await client(ImportContactsRequest([contact]))
                if result.users:
                    user = result.users[0]
                    await client(DeleteContactsRequest(id=[user.id]))  # optional cleanup
                    return user.id, getattr(user, "username", None)
                return None, None

            except FloodWaitError as e:
                wait_time = e.seconds + 2
                print(f"⚠️ FloodWait: sleeping for {wait_time} seconds...")
                await asyncio.sleep(wait_time)

    except PhoneNumberInvalidError:
        print(f"❌ Invalid phone number: {phone}")
        return None, None

    except Exception as e:
        print(f"⚠️ Unexpected error fetching {phone}: {e}")
        return None, None
