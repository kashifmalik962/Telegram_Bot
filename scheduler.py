import pymongo
from util import kick_user
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from dotenv import load_dotenv
import os

# load environment variables
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
DB = os.getenv("DB")
USER_COLLECTION = os.getenv("USER_COLLECTION")


# MongoDB Setup
client = pymongo.MongoClient(MONGO_URI)
db = client[DB]
users_collection = db[USER_COLLECTION]

# APScheduler Setup
scheduler = BackgroundScheduler()
scheduler.start()

# -------------------- Scheduler Functions --------------------

def check_and_kick_users():
    """Check for expired subscriptions and kick users."""
    print("running check_and_kick_users")
    current_time = datetime.now()
    expired_users = users_collection.find({
        "expiry_date": {"$lt": current_time}
    })

    for user in expired_users:
        telegram_id = user["telegram_id"]
        kick_user(telegram_id)
        users_collection.delete_one({"telegram_id": telegram_id})
        print(f"[Auto Kick] User {telegram_id} kicked after expiry.")

def start_expiry_check():
    """Start periodic check for expired users."""
    scheduler.add_job(check_and_kick_users, trigger='cron', hour=12, minute=0, timezone='UTC')
    # scheduler.add_job(check_and_kick_users, 'interval', minutes=1)
    print("✅ Scheduler started: will check for expired users daily at 12:00 PM UTC.")

