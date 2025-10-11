from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from util import *
from req_body import *
from scheduler import *

# Load environment variables
load_dotenv()

# load environment variables
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
DB = os.getenv("DB")
USER_COLLECTION = os.getenv("USER_COLLECTION")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # This code runs on startup
    start_expiry_check()
    yield
    # This code runs on shutdown (optional)
    print("Shutting down...")


# Initialize FastAPI
app = FastAPI(lifespan=lifespan)

# -------------------- API Endpoints --------------------

# Subscribe plan for user
@app.post("/subscribe")
def subscribe_user(user_sub_details: UserSubscription):
    """Subscribe a new user to the group."""
    telegram_id = user_sub_details.telegram_id
    duration_days = user_sub_details.duration_days

    if not telegram_id or not duration_days or duration_days <= 0:
        return JSONResponse(status_code=400, content={
            "status_code": 0,
            "message": "telegram_id or duration_days missing/invalid"
        })

    expiry_date = datetime.now() + timedelta(days=duration_days)
    add_user(telegram_id, expiry_date)

    invite_link = create_temp_invite_link()
    if invite_link:
        telegram_bot_sendtext(f"Click here to join the group: {invite_link}", telegram_id)
        send_group_subscription_notification(telegram_id)
    else:
        telegram_bot_sendtext("❌ Failed to generate invite link. Please try again later.", telegram_id)

    return {"message": "User subscribed successfully", "invite_link": invite_link, "expiry_date": expiry_date}



@app.post("/extend-plan")
async def extend_plan(user_sub_details: UserSubscription):
    """Extend an existing user's subscription plan dynamically."""
    telegram_id = user_sub_details.telegram_id
    extra_days = user_sub_details.duration_days  # optional, could default to 30

    if not telegram_id:
        return JSONResponse(status_code=400, content={
            "status_code": 0,
            "message": "telegram_id missing"
        })

    # Fetch current user from DB
    user = users_collection.find_one({"telegram_id": telegram_id})
    previous_expiry = user.get("expiry_date") if user else None
    base_date = previous_expiry if previous_expiry and previous_expiry > datetime.now() else datetime.now()

    # Calculate new expiry
    extra_days = extra_days if extra_days and extra_days > 0 else 30
    new_expiry_date = base_date + timedelta(days=extra_days)

    # Calculate duration_days dynamically
    duration_days = (new_expiry_date - datetime.now()).days

    extend_plan_in_db(telegram_id, new_expiry_date)

    telegram_bot_sendtext(f"🎉 Your plan has been extended until {new_expiry_date}", telegram_id)

    return JSONResponse(status_code=200, content={
        "status_code": 1,
        "message": "User plan extended successfully",
        "data": {
            "telegram_id": telegram_id,
            "previous_expiry": jsonable_encoder(previous_expiry),
            "new_expiry": jsonable_encoder(new_expiry_date),
            "duration_days": duration_days
        }
    })


@app.get("/kick_expired_users")
def kick_expired_users():
    """Manually trigger kicking expired users."""
    check_and_kick_users()
    return {"message": "Expired users kicked successfully"}

# -------------------- Main --------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
