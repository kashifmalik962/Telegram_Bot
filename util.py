import requests
import time
from dotenv import load_dotenv
import os
import pymongo
from datetime import datetime

# load environment variables
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
MONGO_URI = os.getenv("MONGO_URI")
DB = os.getenv("DB")
USER_COLLECTION = os.getenv("USER_COLLECTION")

# MongoDB Setup
client = pymongo.MongoClient(MONGO_URI)
db = client[DB]
users_collection = db[USER_COLLECTION]

# -------------------- Utility Functions --------------------

def telegram_bot_sendtext(bot_message, telegram_id):
    """Send message to a specific Telegram user."""
    send_text = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?chat_id={telegram_id}&parse_mode=HTML&text={bot_message}'
    try:
        response = requests.get(send_text)
        return response.json()
    except Exception as e:
        print(f"Error sending Telegram message: {e}")
        return None


def create_temp_invite_link():
    """Create a one-time, expiring Telegram group invite link."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createChatInviteLink"
    data = {
        "chat_id": GROUP_CHAT_ID,
        "expire_date": int(time.time()) + (7 * 24 * 60 * 60),  # 7 days validity
        "member_limit": 1
    }
    try:
        response = requests.post(url, json=data)
        result = response.json()
        raw_link = result.get("result", {}).get("invite_link", "")
        if raw_link:
            return raw_link.replace("+", "%2B")
        return None
    except Exception as e:
        print(f"Error generating invite link: {e}")
        return None

def add_user(telegram_id: int, expiry_date: datetime, invite_link: str):
    """Add or update a user in MongoDB."""
    users_collection.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"expiry_date": expiry_date, "invite_link": invite_link, "joined": False}},
        upsert=True
    )
    print(f"[Added] User {telegram_id} added with expiry {expiry_date}.")


def kick_user(telegram_id: int):
    """Kick a user from the Telegram group."""
    kick_url = f"https://api.telegram.org/bot{BOT_TOKEN}/banChatMember?chat_id={GROUP_CHAT_ID}&user_id={telegram_id}"
    unban_url = f"https://api.telegram.org/bot{BOT_TOKEN}/unbanChatMember?chat_id={GROUP_CHAT_ID}&user_id={telegram_id}"
    try:
        requests.get(kick_url)
        requests.get(unban_url)
        print(f"[Auto Kick] User {telegram_id} kicked successfully.")
    except Exception as e:
        print(f"Error kicking user {telegram_id}: {e}")


def send_group_subscription_notification(telegram_id: int):
    """Notify group about a new subscription."""
    message = f"🎉 A new user has subscribed and is eligible to join the group! User ID: {telegram_id}"
    telegram_bot_sendtext(message, GROUP_CHAT_ID)


def extend_plan_in_db(telegram_id, new_expiry_date):
    users_collection.update_one(
        {"telegram_id": telegram_id},
        {"$set": {"expiry_date": new_expiry_date}},
        upsert=True
    )


