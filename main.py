import requests
import pymongo
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from datetime import datetime, timedelta
import time
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# MongoDB connection
BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
MONGO_URI = os.getenv("MONGO_URI")
DB = os.getenv("DB")
USER_COLLECTION = os.getenv("USER_COLLECTION")



# Initialize FastAPI
app = FastAPI()

# MongoDB Setup
client = pymongo.MongoClient(MONGO_URI)  # Replace with your MongoDB URI
db = client[DB]
users_collection = db[USER_COLLECTION]

# Telegram Bot Setup
BOT_TOKEN = BOT_TOKEN
GROUP_CHAT_ID = GROUP_CHAT_ID

# APScheduler Setup
scheduler = BackgroundScheduler()
scheduler.start()

# Pydantic Model for Subscription Data
class UserSubscription(BaseModel):
    user_chat_id: str

# Function to send a message to a specific chat (user or group)
def telegram_bot_sendtext(bot_message, chat_id):
    send_text = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?chat_id={chat_id}&parse_mode=HTML&text={bot_message}'
    response = requests.get(send_text)
    return response.json()

# Function to create a one-time, expiring Telegram group invite link
def create_temp_invite_link():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/createChatInviteLink"
    data = {
        "chat_id": GROUP_CHAT_ID,
        "expire_date": int(time.time()) + 180,  # Link will expire in 1 minute
        "member_limit": 1
    }
    try:
        response = requests.post(url, json=data)
        result = response.json()
        raw_link = result.get("result", {}).get("invite_link", "")
        if raw_link:
            cleaned_link = raw_link.replace("+", "%2B")
            return cleaned_link
        return None
    except Exception as e:
        print(f"Error generating invite link: {e}")
        return None

# Function to add a new user to MongoDB with subscription date
def add_user(user_chat_id: str):
    subscription_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    users_collection.update_one(
        {"user_chat_id": user_chat_id},
        {"$set": {"subscription_date": subscription_date}},
        upsert=True
    )
    print(f"[Added] User {user_chat_id} added with subscription date {subscription_date}.")

# Function to kick a user from the group
def kick_user(user_chat_id: str):
    kick_url = f"https://api.telegram.org/bot{BOT_TOKEN}/banChatMember?chat_id={GROUP_CHAT_ID}&user_id={user_chat_id}"
    unban_url = f"https://api.telegram.org/bot{BOT_TOKEN}/unbanChatMember?chat_id={GROUP_CHAT_ID}&user_id={user_chat_id}"
    
    try:
        requests.get(kick_url)
        requests.get(unban_url)
        print(f"[Auto Kick] User {user_chat_id} was successfully kicked and unbanned.")
    except Exception as e:
        print(f"Error kicking user {user_chat_id}: {e}")

# Function to check and kick users who have been in the group for more than 60 seconds
def check_and_kick_users():
    current_time = datetime.now()
    
    # Query users with subscriptions older than 60 seconds
    expired_users = users_collection.find({
        "subscription_date": {"$lt": (current_time - timedelta(seconds=60)).strftime("%Y-%m-%d %H:%M:%S")}
    })
    
    for user in expired_users:
        user_chat_id = user["user_chat_id"]
        kick_user(user_chat_id)
        users_collection.delete_one({"user_chat_id": user_chat_id})  # Remove user from database after kick
        print(f"[Auto Kick] User {user_chat_id} was kicked out after 60 seconds.")

# Setup periodic job for expired user checking
def start_expiry_check():
    scheduler.add_job(check_and_kick_users, 'interval', minutes=1)  # Run every 1 minute
    print("Scheduler started, checking for expired users every 1 minute.")

# API Endpoints

# Function to send a message to the group when a new user subscribes
def send_group_subscription_notification(user_chat_id: str):
    message = f"🎉 A new user has subscribed and is eligible to join the premium group! User ID: {user_chat_id}"
    telegram_bot_sendtext(message, GROUP_CHAT_ID)

@app.post("/subscribe")
def subscribe_user(subscription: UserSubscription):
    """API to subscribe a user to the group."""
    user_chat_id = subscription.user_chat_id
    add_user(user_chat_id)
    
    invite_link = create_temp_invite_link()
    if invite_link:
        telegram_bot_sendtext(f"Click here to join the group: {invite_link}", user_chat_id)
        # Notify the group about the new subscription
        send_group_subscription_notification(user_chat_id)
    else:
        telegram_bot_sendtext("❌ Failed to generate group invite link. Please try again later.", user_chat_id)
    
    return {"message": "User subscribed successfully", "invite_link": invite_link}

@app.get("/kick_expired_users")
def kick_expired_users():
    """API to manually trigger checking and kicking expired users."""
    check_and_kick_users()
    return {"message": "Expired users kicked successfully"}


# ==== MAIN ====
if __name__ == "__main__":
    # Start checking for expired users
    start_expiry_check()
    
    # Run FastAPI
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
